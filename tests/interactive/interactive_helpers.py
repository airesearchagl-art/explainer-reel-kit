"""tests/interactive 共通: 小さい中間データ（render timeline）を作る。"""
from __future__ import annotations

import json
from pathlib import Path

FORMAT = "explainer-reel/render-timeline@1"


def timeline_doc(total: int = 90, scenes=None, sentences=None, cues=None, **extra) -> dict:
    scenes = scenes if scenes is not None else [("a", 0, 45), ("b", 45, total)]
    sentences = sentences if sentences is not None else [
        {"id": "a-1", "scene": "a", "spoken": "空気には、水蒸気が含まれています。", "start_sec": 0.3, "end_sec": 1.3},
        {"id": "b-1", "scene": "b", "spoken": "冷えると、水滴になります。", "start_sec": 1.6, "end_sec": 2.7},
    ]
    cues = cues if cues is not None else [
        {"sentence": "a-1", "text": "空気には、水蒸気が含まれています", "start_frame": 9, "end_frame": 39},
        {"sentence": "b-1", "text": "冷えると、水滴になります", "start_frame": 48, "end_frame": 81},
    ]
    doc = {"format": FORMAT, "fps": 30, "width": 1920, "height": 1080, "total_frames": total,
           "scenes": [{"id": i, "title": f"場面 {i}", "start_frame": a, "end_frame": b} for i, a, b in scenes],
           "sentences": sentences, "cues": cues}
    doc.update(extra)
    return doc


def write_doc(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 文ごとに音と無音を並べた WAV（文の時刻を WAV から測る確かめ）

RATE = 24000
SEC_PER_CHAR = 0.02  # 1 文字の音の長さ（テストを短く保つ）
GAP_SEC = 0.35       # 分割の中の文と文の間の無音
EDGE_SEC = 0.05      # 分割の頭・終わりの無音


def speech_pcm(text: str, rate: int = RATE, sec_per_char: float = SEC_PER_CHAR) -> bytes:
    """文ごとに「音（1 文字 sec_per_char 秒）＋無音」を並べた 16 bit モノラルの PCM。"""
    import math
    import struct

    sentences = [s for s in text.replace("。", "。\n").split("\n") if s]
    pcm = bytearray()

    def silence(sec):
        pcm.extend(b"\x00\x00" * round(sec * rate))

    def tone(sec, freq=330.0):
        n = round(sec * rate)
        pcm.extend(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)))

    silence(EDGE_SEC)
    for k, s in enumerate(sentences):
        if k:
            silence(GAP_SEC)
        tone(len(s) * sec_per_char)
    silence(EDGE_SEC)
    return bytes(pcm)


def wav_bytes(pcm: bytes, rate: int = RATE) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def speech_wav(text: str, rate: int = RATE, sec_per_char: float = SEC_PER_CHAR) -> bytes:
    return wav_bytes(speech_pcm(text, rate, sec_per_char), rate)


class SentenceEngine:
    """合成に送られた文を記録し、文ごとに音と無音を返す偽の音声合成エンジン（AivisSpeech の形）。"""

    def __init__(self, sec_per_char: float = SEC_PER_CHAR) -> None:
        self.synthesized: list[str] = []
        self.sec_per_char = sec_per_char

    def __call__(self, method, url, headers, body, timeout):
        import json
        import urllib.parse

        from explainer_reel_kit.narration.tts.aivisspeech import HttpResponse

        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if parsed.path == "/speakers":
            data = [{"name": "Test", "speaker_uuid": "test-speaker-uuid", "version": "1",
                     "styles": [{"name": "ノーマル", "id": 808373280}]}]
            return HttpResponse(200, json.dumps(data).encode(), "application/json")
        if parsed.path == "/aivm_models":
            return HttpResponse(200, b"{}", "application/json")
        if parsed.path == "/audio_query":
            q = {"accent_phrases": [], "speedScale": 1.0, "volumeScale": 1.0, "outputSamplingRate": RATE,
                 "outputStereo": False, "kana": query["text"]}
            return HttpResponse(200, json.dumps(q, ensure_ascii=False).encode(), "application/json")
        if parsed.path == "/synthesis":
            text = json.loads(body.decode("utf-8"))["kana"]
            self.synthesized.append(text)
            return HttpResponse(200, speech_wav(text, sec_per_char=self.sec_per_char), "audio/wav")
        if parsed.path == "/version":
            return HttpResponse(200, b'"1.1.0"', "application/json")
        return HttpResponse(404, b"{}", "application/json")
