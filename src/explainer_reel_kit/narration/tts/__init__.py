"""音声合成エンジンの口（TTSEngine）。

差し替える側がするのは「1 分割の文章を WAV にする」ことだけ。分割・読み辞書の置換・WAV の連結・
durations.json・再生成の判定は、口の外の共通部分（narration.synth）が受け持つ。

- 既定は ``aivisspeech``（AivisSpeech Engine の HTTP、既定 ``http://127.0.0.1:10101``）
- 他のエンジンは、パッケージの entry point（グループ ``explainer_reel_kit.tts``）に
  ``名前 = モジュール:ファクトリ`` を登録すると選べる。ファクトリは ``(url, timeout_sec=..., transport=...)``
  を受け取り、TTSEngine を返す
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable, Protocol, runtime_checkable

from ..errors import InputError

DEFAULT_ENGINE = "aivisspeech"
ENTRY_POINT_GROUP = "explainer_reel_kit.tts"


@dataclass(frozen=True)
class Voice:
    """エンジンの声の 1 つ（AivisSpeech では話者のスタイル 1 つ）。"""

    style_id: int
    speaker_name: str
    speaker_uuid: str
    style_name: str

    @property
    def label(self) -> str:
        return f"{self.speaker_name} / {self.style_name}"


@dataclass(frozen=True)
class EngineInfo:
    name: str
    url: str
    version: str
    models: list[dict[str, Any]] | None = None  # 声のモデルの一覧（エンジンが返すときだけ）


@runtime_checkable
class TTSEngine(Protocol):
    name: str
    url: str

    def check(self) -> EngineInfo:
        """接続と版（環境の確認・voice list が使う）。つながらなければ EngineError。"""

    def voices(self) -> list[Voice]:
        """声の一覧。"""

    def synthesize(self, text: str, voice: int, *, speed: float, volume: float) -> bytes:
        """1 分割の文章を WAV（44.1kHz モノラル）にする。"""

    def reading(self, text: str, voice: int) -> str | None:
        """読みのカナ（読みの確認用）。分からなければ None。"""


Factory = Callable[..., TTSEngine]


def _builtin() -> dict[str, Factory]:
    from .aivisspeech import AivisSpeechEngine

    return {"aivisspeech": AivisSpeechEngine}


def available_engines() -> dict[str, Factory]:
    engines = dict(_builtin())
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python < 3.10 の形
        eps = metadata.entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    for ep in eps:
        engines.setdefault(ep.name, ep.load())
    return engines


def default_url(name: str) -> str | None:
    if name == "aivisspeech":
        from .aivisspeech import DEFAULT_ENGINE_URL

        return DEFAULT_ENGINE_URL
    return None


def get_engine(name: str | None, url: str | None = None, **kwargs: Any) -> TTSEngine:
    name = name or DEFAULT_ENGINE
    engines = available_engines()
    if name not in engines:
        raise InputError(f"音声合成エンジン '{name}' はありません（使えるもの: {', '.join(sorted(engines))}）")
    url = url or default_url(name)
    if url is None:
        raise InputError(f"音声合成エンジン '{name}' の URL を指定してください（--engine-url）")
    return engines[name](url, **kwargs)
