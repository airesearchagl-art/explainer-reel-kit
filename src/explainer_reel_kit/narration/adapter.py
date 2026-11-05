"""台本 → ナレーションの入力（narration-input）の変換。

- item の id は intro / シーン id / outro（スライドの durations の対応と同じ）
- 声は reel.voice.speaker ＞ 設定の voice.speaker ＞ 既定（ほのか / ノーマル）
- エンジンは reel.voice.engine ＞ 設定の voice.engine
- speed / volume は台本にあるときだけ渡す（無ければナレーションの段の既定）
- 余白（pre / post_pause_sec）はナレーションの段の既定に任せる
"""
from __future__ import annotations

from typing import Any

from ..config import DEFAULT_SPEAKER

NARRATION_INPUT_VERSION = 1


class AdapterError(ValueError):
    """台本をナレーションの入力に変換できない。"""


def resolve_speaker(value: Any, default: int = DEFAULT_SPEAKER) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise AdapterError("reel.voice.speaker が真偽値です。style id（整数）を指定してください")
    if isinstance(value, int):
        if value < 0:
            raise AdapterError("reel.voice.speaker は 0 以上の style id にしてください")
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise AdapterError(
        f"reel.voice.speaker '{value}' は声の名前のため変換できません。"
        "`erkit voice list` で style id（整数）を確認して指定してください"
    )


def slide_ids(doc: dict[str, Any]) -> list[str]:
    """スライド順の id（intro → scenes → outro）。"""
    return ["intro", *[s["id"] for s in doc["scenes"]], "outro"]


def storyboard_to_narration_input(doc: dict[str, Any], *, default_speaker: int = DEFAULT_SPEAKER,
                                  default_engine: str | None = None) -> dict[str, Any]:
    voice = doc["reel"].get("voice") or {}
    out: dict[str, Any] = {
        "version": NARRATION_INPUT_VERSION,
        "speaker": resolve_speaker(voice.get("speaker"), default_speaker),
    }
    engine = voice.get("engine") or default_engine
    if engine:
        out["engine"] = engine
    for key in ("speed", "volume"):
        if key in voice:
            out[key] = voice[key]
    texts = [doc["intro"]["narration"], *[s["narration"] for s in doc["scenes"]], doc["outro"]["narration"]]
    out["items"] = [{"id": i, "text": t} for i, t in zip(slide_ids(doc), texts)]
    return out
