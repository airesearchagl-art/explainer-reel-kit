"""Token budget for one call: instructions + input (+ previous answer and request) + max_tokens <= context .

The draft task assumes a server Context Length of 8192 by default (``tasks.*.expected_context``).
Character limits are not a token budget (Japanese and English mixed text), so every call is estimated
**conservatively** before it is sent:

- a non-ASCII character (Japanese, full-width, symbols) ≈ 1 token;
- ASCII text ≈ 1 token per 4 characters (rounded up per run of ASCII);
- a few tokens per message for the chat template, and a safety margin.

Real tokenizers (Qwen) are usually below this estimate — much below for READMEs with many ASCII
letters and symbols. So the decisions that matter (does the full input fit? does the condensed input
fit?) use the **measured** count when the server gives one (``Measurer``): a call with
``max_tokens=1`` returns ``usage.prompt_tokens`` (only the prompt is processed). The estimate is the
fallback when it cannot be measured, and is still used for the small parts added on a rewrite.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .client import LLMClient

from .errors import LLMToolError

DEFAULT_CONTEXT = 8192  # config/llm.yaml tasks.*.expected_context
MESSAGE_OVERHEAD = 8  # role markers of the chat template, per message
REQUEST_OVERHEAD = 16
SAFETY_MARGIN = 256

_ASCII_RUN = re.compile(r"[\x00-\x7f]+")


class BudgetError(LLMToolError):
    """A call would not fit the context. Nothing was sent."""

    exit_code = 2


def estimate_tokens(text: str) -> int:
    ascii_tokens = 0
    ascii_chars = 0
    for run in _ASCII_RUN.findall(text):
        ascii_chars += len(run)
        ascii_tokens += math.ceil(len(run) / 4)
    return ascii_tokens + (len(text) - ascii_chars)


def estimate_messages(messages: list[dict[str, Any]]) -> int:
    return REQUEST_OVERHEAD + sum(MESSAGE_OVERHEAD + estimate_tokens(str(m.get("content", ""))) for m in messages)


@dataclass(frozen=True)
class Budget:
    context: int = DEFAULT_CONTEXT
    margin: int = SAFETY_MARGIN

    def room(self, max_tokens: int) -> int:
        """Tokens left for the prompt when the answer may use ``max_tokens``."""
        return self.context - self.margin - max_tokens

    def fits(self, messages: list[dict[str, Any]], max_tokens: int) -> bool:
        return estimate_messages(messages) <= self.room(max_tokens)

    def require(self, messages: list[dict[str, Any]], max_tokens: int, *, what: str,
                tokens: int | None = None) -> int:
        """The prompt's tokens (``tokens`` if measured, else the estimate); BudgetError (before sending) if it does not fit."""
        count = estimate_messages(messages) if tokens is None else tokens
        if count > self.room(max_tokens):
            kind = "実測" if tokens is not None else "見積もり"
            raise BudgetError(
                f"{what}: 送る内容の{kind} {count} トークン＋出力の上限 {max_tokens}＋余裕 {self.margin} が、"
                f"文脈長 {self.context} を超えるため送りませんでした"
            )
        return count


@dataclass
class Measurer:
    """The real prompt size from the server: one call with ``max_tokens=1`` → ``usage.prompt_tokens`` .

    ``None`` when it cannot be measured (no usage, a server error, the prompt over the server's context);
    the caller then uses the conservative estimate. Every measurement is kept for the record.
    """

    client: "LLMClient"
    model: str
    thinking: str = "off"
    enabled: bool = True
    log: list[dict[str, Any]] = field(default_factory=list)

    def count(self, messages: list[dict[str, Any]], *, what: str) -> int | None:
        from .errors import LLMError
        from .thinking import ThinkingSender

        estimate = estimate_messages(messages)
        entry: dict[str, Any] = {"what": what, "estimated": estimate, "measured": None, "sec": None, "error": None}
        self.log.append(entry)
        if not self.enabled:
            entry["error"] = "測らない設定"
            return None
        started = time.monotonic()
        try:
            answer = ThinkingSender(self.thinking).call(
                lambda extra: self.client.chat(messages, model=self.model, max_tokens=1, temperature=0,
                                               extra_body=extra))
        except LLMError as error:
            entry.update(sec=round(time.monotonic() - started, 3), error=str(error)[:200])
            return None
        entry["sec"] = round(time.monotonic() - started, 3)
        tokens = (answer.usage or {}).get("prompt_tokens")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
            entry["error"] = "usage.prompt_tokens が返りませんでした"
            return None
        entry["measured"] = tokens
        return tokens

    def cost(self, messages: list[dict[str, Any]], *, what: str) -> tuple[int, bool]:
        """(tokens, measured?)"""
        tokens = self.count(messages, what=what)
        return (tokens, True) if tokens is not None else (estimate_messages(messages), False)
