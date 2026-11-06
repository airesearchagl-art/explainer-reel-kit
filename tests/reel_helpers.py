"""tests/reel 共通: 偽の AivisSpeech Engine、ffmpeg の有無、テスト用動画の生成。"""
from __future__ import annotations

import io
import json
import math
import shutil
import struct
import subprocess
import urllib.parse
import wave
from pathlib import Path

import pytest

from explainer_reel_kit.narration.tts.aivisspeech import HttpResponse

CREDIT_VOICE_ID = 424242  # テスト用の「クレジットが必要な声」の style id
SEC_PER_CHAR = 0.004  # 合成 1 文字 ＝ 4ms（テストを短く保つ）

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg / ffprobe が無い環境")


def tone_wav(seconds: float, sample_rate: int = 44100, freq: float = 440.0) -> bytes:
    """無音ではない WAV（silencedetect で位置を確かめるため）。16bit モノラル。"""
    n = round(seconds * sample_rate)
    frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))) for i in range(n))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)
    return out.getvalue()


class FakeEngine:
    """ナレーションの段が使う AivisSpeech のエンドポイントだけを返す偽エンジン（音は鳴る＝無音ではない WAV）。"""

    def __init__(self) -> None:
        self.speaker_ids: list[int] = []

    def __call__(self, method, url, headers, body, timeout) -> HttpResponse:
        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if parsed.path == "/version":
            return HttpResponse(200, b'"1.1.0"', "application/json")
        if parsed.path == "/speakers":
            styles = [{"name": "ノーマル", "id": 808373280}, {"name": "クレジットが必要な声", "id": CREDIT_VOICE_ID}, {"name": "x", "id": 7}]
            data = [{"name": "Test", "speaker_uuid": "test-speaker-uuid", "styles": styles, "version": "1"}]
            return HttpResponse(200, json.dumps(data).encode(), "application/json")
        if parsed.path == "/aivm_models":
            return HttpResponse(200, b"{}", "application/json")
        if parsed.path == "/audio_query":
            self.speaker_ids.append(int(query["speaker"]))
            q = {"accent_phrases": [], "speedScale": 1.0, "volumeScale": 1.0, "outputSamplingRate": 24000,
                 "outputStereo": True, "kana": query["text"]}
            return HttpResponse(200, json.dumps(q, ensure_ascii=False).encode(), "application/json")
        if parsed.path == "/synthesis":
            q = json.loads(body.decode("utf-8"))
            return HttpResponse(200, tone_wav(len(q["kana"]) * SEC_PER_CHAR, q["outputSamplingRate"]), "audio/wav")
        return HttpResponse(404, b'{"detail":"Not Found"}', "application/json")


def make_black_video(path: Path, seconds: float) -> Path:
    """テスト用の無音・黒画面 MP4（PowerPoint の書き出しの代わり）。"""
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=black:s=320x180:r=30:d={seconds:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def ffprobe_sec(path: Path, stream: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def silence_ends(path: Path) -> list[float]:
    """音声が鳴り始める時刻の一覧（ffmpeg silencedetect の silence_end）。"""
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-map", "0:a:0", "-af", "silencedetect=n=-40dB:d=0.05",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    import re

    return [float(m) for m in re.findall(r"silence_end: ([0-9.]+)", res.stderr)]
