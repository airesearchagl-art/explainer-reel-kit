"""The thinking switch : what is sent for auto / off / on, with one fallback.

Which parameter a server honours can only be seen on the real server, so callers record what
was sent (``params``), what was rejected (``rejected``) and whether thinking actually appeared.
"""

from __future__ import annotations

from typing import Any, Callable

from .errors import LLMError, LLMErrorKind

THINKING_MODES = ("auto", "off", "on")

THINKING_PARAMS: dict[str, list[dict[str, Any]]] = {
    "auto": [{}],
    # first try: Qwen/vLLM style template switch + OpenAI style effort; fallback if the server rejects it
    "off": [
        {"chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"},
        {"chat_template_kwargs": {"enable_thinking": False}},
    ],
    "on": [
        {"chat_template_kwargs": {"enable_thinking": True}, "reasoning_effort": "medium"},
        {"chat_template_kwargs": {"enable_thinking": True}},
    ],
}


class ThinkingSender:
    """Sends the thinking parameters; on HTTP 400/422 falls back to the simpler set and remembers it."""

    def __init__(self, mode: str) -> None:
        if mode not in THINKING_MODES:
            raise ValueError(mode)
        self.mode = mode
        self.options = THINKING_PARAMS[mode]
        self.index = 0
        self.rejected: list[dict[str, Any]] = []

    @property
    def params(self) -> dict[str, Any]:
        return self.options[self.index]

    def call(self, fn: Callable[[dict[str, Any]], Any]):
        while True:
            try:
                return fn(self.params)
            except LLMError as error:
                rejectable = error.kind is LLMErrorKind.HTTP_ERROR and error.http_status in (400, 422)
                if rejectable and self.index + 1 < len(self.options):
                    self.rejected.append({"params": self.params, "error": str(error)})
                    self.index += 1
                    continue
                raise
