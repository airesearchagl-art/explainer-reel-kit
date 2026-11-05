"""Error types for the narration CLI.

Engine failures are classified into five kinds. Every failure path
raises one of these instead of degrading into empty audio or an empty voice
list.
"""

from __future__ import annotations

from enum import Enum


class EngineErrorKind(str, Enum):
    """Why an engine call failed."""

    #: Could not reach the engine at all (not running / wrong URL / timeout).
    ENGINE_CONNECTION_FAILED = "ENGINE_CONNECTION_FAILED"
    #: The engine answered, but listing speakers failed (non-2xx on /speakers).
    SPEAKERS_FAILED = "SPEAKERS_FAILED"
    #: The engine answered, but /audio_query failed (non-2xx).
    AUDIO_QUERY_FAILED = "AUDIO_QUERY_FAILED"
    #: The engine answered, but /synthesis failed (non-2xx).
    SYNTHESIS_FAILED = "SYNTHESIS_FAILED"
    #: The engine answered 2xx, but the payload is not the shape we expect.
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


class NarrationError(Exception):
    """Base class for every error this package raises on purpose."""

    exit_code = 1


class EngineError(NarrationError):
    """A speech engine call failed. Carries an explicit kind."""

    exit_code = 1

    def __init__(
        self,
        kind: EngineErrorKind,
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
        parts = [f"[{self.kind.value}]"]
        if self.endpoint:
            parts.append(self.endpoint)
        if self.http_status is not None:
            parts.append(f"HTTP {self.http_status}")
        text = " ".join(parts) + f": {self.args[0]}"
        if self.detail:
            text += f"\n  detail: {self.detail}"
        return text


class InputError(NarrationError):
    """The narration input, dictionary, or CLI arguments are invalid."""

    exit_code = 2


class OutputError(NarrationError):
    """Writing to the output folder failed (permission, locked file, disk full...)."""

    exit_code = 4


class OverwriteRefusedError(NarrationError):
    """Existing WAV files would be overwritten without --force."""

    exit_code = 3

    def __init__(self, item_ids: list[str]) -> None:
        self.item_ids = item_ids
        joined = ", ".join(item_ids)
        super().__init__(
            "既存の WAV と内容が異なるため上書きしません（--force で上書き）: " + joined
        )
