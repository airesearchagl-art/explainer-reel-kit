"""Errors of the LLM client. Every failure is raised, never turned into an empty answer."""

from __future__ import annotations

from enum import Enum


class LLMErrorKind(str, Enum):
    #: Could not reach the server at all (not running / wrong URL / refused).
    CONNECTION_FAILED = "CONNECTION_FAILED"
    #: The server did not answer within timeout_sec.
    TIMEOUT = "TIMEOUT"
    #: The server answered with a non-2xx status.
    HTTP_ERROR = "HTTP_ERROR"
    #: The server answered 2xx, but not in the OpenAI-compatible shape.
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


class LLMToolError(Exception):
    """Base class. ``exit_code`` is what the CLI returns."""

    exit_code = 1


class LLMError(LLMToolError):
    exit_code = 1

    def __init__(
        self,
        kind: LLMErrorKind,
        message: str,
        *,
        endpoint: str | None = None,
        http_status: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.endpoint = endpoint
        self.http_status = http_status
        self.detail = detail

    def __str__(self) -> str:
        head = f"[{self.kind.value}]"
        if self.endpoint:
            head += f" {self.endpoint}"
        if self.http_status is not None:
            head += f" HTTP {self.http_status}"
        text = f"{head}: {self.args[0]}"
        if self.detail:
            text += f"\n  detail: {self.detail}"
        return text


class ConfigError(LLMToolError):
    """config/llm.yaml or the CLI arguments are invalid."""

    exit_code = 2


class ModelNotFoundError(ConfigError):
    """The model a task (or --model) names is not on the server. No other model is used instead.

    キットの終了コードの考え方では「足りないものがある」なので 1。"""

    exit_code = 1

    def __init__(self, model: str, available: list[str], *, task: str | None = None) -> None:
        self.model = model
        self.available = available
        self.task = task
        whose = f"task {task} の既定のモデル" if task else "指定のモデル"
        listed = ", ".join(available) if available else "（なし）"
        super().__init__(
            f"{whose} {model} がサーバーにありません。LM Studio の Discover で「{model}」を検索してダウンロードし、"
            f"読み込んでから実行してください（別のモデルは使いません）。サーバーにあるモデル: {listed}"
        )


class RouteBlockedError(LLMToolError):
    """送り先が許されていない（社外秘でこの PC 以外、または LAN の外）。何も送っていない。"""

    exit_code = 1


class OutputError(LLMToolError):
    """書き込めない・上書きを止めた。"""

    exit_code = 1
