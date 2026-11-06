"""Generate → check → ask for a rewrite (AI の出力は必ず検査する).

A common part for every structured AI output (reading candidates now, storyboard drafts later):

1. send the messages;
2. read the answer (JSON by default: ```json fences and surrounding text are removed, thinking
   is already separated by the client) and check it — the JSON Schema, if given, then the
   caller's own ``validate`` function (counts, required items, ranges …);
3. if anything is wrong, show the model its previous answer (when it fits the token budget) and a
   list of short, concrete problems (counts, lengths — never whole values) and ask it to rewrite
   (``retries`` times, default 2);
4. still wrong → a failed result with the reasons. Nothing is guessed or patched up.

Every attempt (ok, problems, seconds, finish_reason, …) is returned so the caller can record it.
This guard works whatever model is used.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .budget import Budget, estimate_messages
from .client import ChatResult, LLMClient
from .errors import LLMError
from .jsonout import extract_json
from .thinking import ThinkingSender

#: (parsed value) -> problems, each a short sentence the model can act on. Empty list = accepted.
Validator = Callable[[Any], list[str]]

DEFAULT_RETRIES = 2
_MAX_SCHEMA_PROBLEMS = 8
_ECHO_MAX_CHARS = 4000
VALUE_MAX_CHARS = 60  # a value quoted in a problem is cut to this (no whole values in requests)


@dataclass
class Attempt:
    index: int  # 0 = first answer, 1.. = rewrites
    ok: bool
    problems: list[str]
    elapsed_sec: float | None
    finish_reason: str | None = None
    thinking_observed: bool = False
    content: str = ""
    error_kind: str | None = None
    estimated_prompt_tokens: int | None = None  # our conservative estimate (budget.py)
    prompt_tokens: int | None = None  # usage.prompt_tokens from the server, when it returns it
    completion_tokens: int | None = None
    previous_answer_sent: bool | None = None  # rewrites: whether the previous answer was sent back
    max_tokens: int | None = None  # the answer budget of this attempt (it may grow after a cut-off)

    def as_dict(self, *, with_content: bool = False) -> dict[str, Any]:
        data = {"index": self.index, "ok": self.ok, "problems": self.problems,
                "elapsed_sec": None if self.elapsed_sec is None else round(self.elapsed_sec, 3),
                "finish_reason": self.finish_reason, "thinking_observed": self.thinking_observed,
                "error_kind": self.error_kind, "estimated_prompt_tokens": self.estimated_prompt_tokens,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "previous_answer_sent": self.previous_answer_sent, "max_tokens": self.max_tokens}
        if with_content:
            data["content"] = self.content
        return data


@dataclass
class StructuredResult:
    ok: bool
    value: Any  # the accepted value; on failure, the last value that could be read (or None)
    attempts: list[Attempt] = field(default_factory=list)
    error: str | None = None
    model: str = ""
    thinking: str = "auto"
    thinking_params: dict[str, Any] = field(default_factory=dict)

    @property
    def rewrites(self) -> int:
        return max(0, len(self.attempts) - 1)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "error": self.error, "model": self.model, "thinking": self.thinking,
                "thinking_params": self.thinking_params, "rewrites": self.rewrites,
                "attempts": [a.as_dict() for a in self.attempts]}


def short_value(value: Any, limit: int = VALUE_MAX_CHARS) -> str:
    """A value for a problem message: JSON, cut to ``limit`` characters."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def _where(path: Any) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "全体"


_TYPES = {"string": "文字列", "array": "配列（[…]）", "object": "オブジェクト（{…}）", "integer": "整数",
          "number": "数値", "boolean": "true / false", "null": "null"}


def _schema_problem(error: Any) -> str:
    """One jsonschema error as a short request the model can act on (never the whole value)."""
    where = _where(error.path)
    kind, expected, value, schema = error.validator, error.validator_value, error.instance, error.schema
    if kind in ("minItems", "maxItems") and isinstance(value, list):
        low, high = schema.get("minItems"), schema.get("maxItems")
        if low is not None and low == high:
            return f"{where} が {len(value)} 件です。{low} 件にしてください"
        if kind == "minItems":
            return f"{where} が {len(value)} 件です。{expected} 件以上にしてください"
        return f"{where} が {len(value)} 件です。{expected} 件以下にしてください"
    if kind in ("minLength", "maxLength") and isinstance(value, str):
        if kind == "maxLength":
            return f"{where} が {len(value)} 字です。{expected} 字以内にしてください"
        return f"{where} が空です。書いてください" if not value else f"{where} が短すぎます（{expected} 字以上）"
    if kind == "required" and isinstance(value, dict):
        missing = [k for k in expected if k not in value]
        return f"{'' if where == '全体' else where + ' に '}{', '.join(missing)} がありません"
    if kind == "enum":
        choices = short_value(", ".join(str(c) for c in expected), 200)
        return f"{where}「{short_value(value)}」は使えません（使えるもの: {choices}）"
    if kind == "type":
        names = expected if isinstance(expected, list) else [expected]
        return f"{'全体は' if where == '全体' else where + ' は '}{' か '.join(_TYPES.get(n, n) for n in names)}で書いてください"
    if kind == "pattern":
        return f"{where}「{short_value(value)}」の形式が違います（{expected}）"
    if kind == "additionalProperties" and isinstance(value, dict):
        extra = [k for k in value if k not in (schema.get("properties") or {})]
        return f"{where} に決めていない項目 {', '.join(extra)} があります。消してください"
    return f"{where} が条件（{kind}: {short_value(expected)}）に合いません（値: {short_value(value)}）"


def schema_problems(value: Any, schema: dict[str, Any]) -> list[str]:
    """Short, concrete problems (counts, lengths, missing items). Values are cut to VALUE_MAX_CHARS."""
    problems = []
    for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(map(str, e.path))):
        problems.append(_schema_problem(error))
        if len(problems) >= _MAX_SCHEMA_PROBLEMS:
            break
    return problems


def read_json(text: str) -> tuple[Any, list[str]]:
    """(value, problems). The value is None when no JSON object could be read."""
    try:
        value, _exact = extract_json(text)
    except ValueError as error:
        return None, [f"JSON として読めません（{error}）"]
    return value, []


def answer_problems(answer: ChatResult, length_advice: str | None = None) -> list[str]:
    """``length_advice``: which items to shorten, said concretely by the caller ."""
    if not answer.content.strip():
        if answer.finish_reason == "length":
            return ["本文が空です（出力の上限に達しました）"]
        return ["本文が空です"]
    if answer.finish_reason == "length":
        return ["出力が上限で途中で切れています。" + (length_advice or "短くまとめてください")]
    return []


def rewrite_request(problems: list[str], *, json_only: bool = True, previous_omitted: bool = False) -> str:
    if previous_omitted:
        lines = ["前の出力（長いため、ここには載せません）には次の問題がありました。最初から書き直してください。"]
    else:
        lines = ["前の出力には次の問題がありました。"]
    lines += [f"- {p}" for p in problems]
    tail = "直したものを、JSON だけでもう一度出力してください。説明文やコードブロックは付けません。" if json_only else \
        "直したものを、もう一度出力してください。"
    lines += ["", tail]
    return "\n".join(lines)


def generate(
    client: LLMClient,
    messages: list[dict[str, str]],
    *,
    model: str,
    parse: Callable[[str], tuple[Any, list[str]]] = read_json,
    schema: dict[str, Any] | None = None,
    validate: Validator | None = None,
    retries: int = DEFAULT_RETRIES,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    thinking: str = "off",
    json_only: bool = True,
    budget: Budget | None = None,
    length_advice: str | None = None,
    what: str = "呼び出し",
    base_tokens: int | None = None,
    max_tokens_cap: int | None = None,
    log: Callable[[str], None] = lambda message: None,
) -> StructuredResult:
    """Run the generate → check → rewrite loop. Transport errors stop the loop (they are not rewrites).

    ``budget``: every call must fit (prompt estimate + ``max_tokens`` + margin <= context). The first call
    raises BudgetError before sending; a rewrite sends the previous answer back only when it fits, else
    only the problems. A rewrite is always the original messages + (previous answer) + the request: the
    earlier rounds are not piled up.

    ``base_tokens``: the measured size of ``messages`` . Used instead of the estimate for that part;
    what a rewrite adds (previous answer, request) is still estimated.
    ``max_tokens_cap``: after an answer cut off at ``max_tokens``, the rewrite may answer longer (×1.5, up to
    the cap and what the budget leaves).
    """
    if retries < 0:
        raise ValueError("retries must be >= 0")
    sender = ThinkingSender(thinking)
    history = list(messages)

    def cost(h: list[dict[str, str]]) -> int:
        if base_tokens is None:
            return estimate_messages(h)
        extra = h[len(messages):]
        return base_tokens + (estimate_messages(extra) - estimate_messages([]) if extra else 0)

    if budget is not None:  # nothing is sent when the first call does not fit
        budget.require(history, max_tokens, what=what, tokens=base_tokens)
    attempts: list[Attempt] = []
    last_value: Any = None
    previous_sent: bool | None = None
    for index in range(retries + 1):
        if index:
            log(f"  書き直し {index}/{retries} …")
        estimate = cost(history)
        started = time.monotonic()
        try:
            answer = sender.call(lambda extra: client.chat(history, model=model, max_tokens=max_tokens,
                                                           temperature=temperature, extra_body=extra))
        except LLMError as error:
            attempts.append(Attempt(index, False, [str(error)], time.monotonic() - started, error_kind=error.kind.value,
                                    estimated_prompt_tokens=estimate, previous_answer_sent=previous_sent,
                                    max_tokens=max_tokens))
            return StructuredResult(False, last_value, attempts, f"応答を得られませんでした: {error}", model, thinking,
                                    sender.params)
        problems = answer_problems(answer, length_advice)
        value = None
        if not problems or answer.content.strip():
            value, parse_problems = parse(answer.content)
            if value is not None:
                last_value = value
            if not problems:
                problems = parse_problems
            if not problems and schema is not None:
                problems = schema_problems(value, schema)
            if not problems and validate is not None:
                problems = list(validate(value))
        ok = not problems
        usage = answer.usage or {}
        attempts.append(Attempt(index, ok, problems, answer.elapsed_sec, answer.finish_reason, bool(answer.reasoning),
                                answer.content, estimated_prompt_tokens=estimate,
                                prompt_tokens=_int(usage.get("prompt_tokens")),
                                completion_tokens=_int(usage.get("completion_tokens")),
                                previous_answer_sent=previous_sent, max_tokens=max_tokens))
        if ok:
            return StructuredResult(True, value, attempts, None, model, thinking, sender.params)
        log(f"  検査で不合格: {'; '.join(problems[:3])}")
        with_answer = list(messages) + [
            {"role": "assistant", "content": answer.content[:_ECHO_MAX_CHARS]},
            {"role": "user", "content": rewrite_request(problems, json_only=json_only)},
        ]
        without = list(messages) + [
            {"role": "user", "content": rewrite_request(problems, json_only=json_only, previous_omitted=True)}]
        if answer.finish_reason == "length" and max_tokens_cap and max_tokens < max_tokens_cap:
            grown = min(max_tokens_cap, max(max_tokens + 256, int(max_tokens * 1.5)))
            if budget is not None:
                grown = min(grown, budget.room(0) - cost(without))
            if grown > max_tokens:
                log(f"  出力の上限を {max_tokens} → {grown} トークンに増やして書き直します")
                max_tokens = grown
        if budget is None or cost(with_answer) <= budget.room(max_tokens):
            history, previous_sent = with_answer, True
        else:
            history, previous_sent = without, False
            if cost(history) > budget.room(max_tokens):
                return StructuredResult(False, last_value, attempts,
                                        f"書き直しの依頼が文脈長に収まらないため送りませんでした: {'; '.join(problems)}",
                                        model, thinking, sender.params)
    reasons = attempts[-1].problems
    return StructuredResult(False, last_value, attempts,
                            f"{retries} 回書き直しても検査に通りませんでした: {'; '.join(reasons)}", model, thinking,
                            sender.params)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
