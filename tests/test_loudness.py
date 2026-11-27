"""ナレーションのトラックの音量そろえ（-16 LUFS・true peak -1.5 dBTP 以下）。

ダミーの音（声に近い揺れのある音）で、小さい声・大きい声・ピークの高い声・無音を作り、出来上がりを ffmpeg の
ebur128 で測る（そろえる側の loudnorm とは別の測り方）。段落ごとの WAV と durations.json は変わらないこと。
ffmpeg が無ければ飛ばす。
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from reel_helpers import SEC_PER_CHAR, FakeEngine, needs_ffmpeg
from test_mux import _build, _fake_exporter

from explainer_reel_kit.reel import mux as mux_mod


def speech_like_wav(seconds: float, sample_rate: int, amplitude: float, spike: float = 0.0) -> bytes:
    """声に近いダミー音（220 Hz と 660 Hz を 4 Hz で揺らす）。amplitude は 0〜1（0 なら無音）。

    spike > 0 なら、0.5 秒ごとに 1 ms だけ振幅 spike の音を混ぜる（平均の音量に比べて true peak が高い音）。
    """
    n = round(seconds * sample_rate)
    frames = bytearray()
    burst, every = round(0.001 * sample_rate), round(0.5 * sample_rate)
    for i in range(n):
        t = i / sample_rate
        env = 0.55 + 0.45 * math.sin(2 * math.pi * 4 * t)
        v = amplitude * env * (0.7 * math.sin(2 * math.pi * 220 * t) + 0.3 * math.sin(2 * math.pi * 660 * t))
        if spike and i % every < burst:
            v = spike * math.sin(2 * math.pi * 1000 * t + math.pi / 2)
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))
    return out.getvalue()


class LevelEngine(FakeEngine):
    """合成の音量を変えた偽エンジン（小さい声・大きい声・無音）。"""

    def __init__(self, amplitude: float, sec_per_char: float = SEC_PER_CHAR * 25, spike: float = 0.0):
        super().__init__()
        self.amplitude, self.sec_per_char, self.spike = amplitude, sec_per_char, spike

    def __call__(self, method, url, headers, body, timeout):
        res = super().__call__(method, url, headers, body, timeout)
        if url.split("?")[0].endswith("/synthesis"):
            q = json.loads(body.decode("utf-8"))
            res = type(res)(200, speech_like_wav(len(q["kana"]) * self.sec_per_char, q["outputSamplingRate"],
                                                  self.amplitude, self.spike), "audio/wav")
        return res


def ebur128(path: Path) -> tuple[float, float]:
    """ffmpeg の ebur128（true peak つき）で、統合ラウドネス（LUFS）と true peak（dBTP）を測る。"""
    res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "a:0",
                          "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    summary = res.stderr[res.stderr.rfind("Summary:"):]
    i = re.search(r"\bI" + r":\s+(-?[\d.]+|-inf) LUFS", summary).group(1)
    tp = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary).group(1)
    return float(i), float(tp)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_wav(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


# ------------------------------------------------------------------ フィルタの形（ffmpeg 不要）

def test_gain_filter_is_linear_gain_then_oversampled_true_peak_limiter():
    f = mux_mod.gain_filter(7.25)
    assert f.startswith("volume=7.25dB,aresample=176400,alimiter=")
    assert "level=0" in f and "attack=1" in f and "release=50" in f and f.endswith("aresample=44100")
    limit = float(re.search(r"limit=([\d.]+)", f).group(1))
    assert 20 * math.log10(limit) == pytest.approx(mux_mod.LIMIT_DBTP, abs=0.01)
    assert "loudnorm" not in f and "dynaudnorm" not in f
    assert (mux_mod.TARGET_LUFS, mux_mod.TARGET_TP, mux_mod.LIMIT_DBTP) == (-16.0, -1.5, -2.0)


def test_check_loudness_warns_outside_the_target():
    rec: dict = {}
    assert mux_mod.check_loudness(rec, {"i": -16.4, "tp": -1.9}) == [] and rec["after"]["lufs"] == -16.4
    warns = mux_mod.check_loudness({}, {"i": -18.2, "tp": -0.8})
    assert len(warns) == 2 and "LUFS" in warns[0] and "true peak" in warns[1]
    assert mux_mod.check_loudness({}, None)


# ------------------------------------------------------------------ トラックをそろえる

@needs_ffmpeg
@pytest.mark.parametrize("amplitude, spike", [(0.03, 0.0), (0.6, 0.0)], ids=["quiet", "loud"])
def test_normalize_track_reaches_the_target(tmp_path, amplitude, spike):
    track = write_wav(tmp_path / "in.wav", speech_like_wav(6.0, 44100, amplitude, spike))
    out = tmp_path / "out.wav"
    rec, _ = mux_mod.normalize_track("ffmpeg", track, out)
    assert "skipped" not in rec and rec["method"] == "linear gain + true-peak limiter"
    assert 1 <= len(rec["passes"]) <= mux_mod.GAIN_PASSES and rec["limiter"]["limit_dbtp"] == -2.0
    lufs, tp = ebur128(out)
    assert lufs == pytest.approx(-16.0, abs=1.0)
    assert tp <= -1.5


@needs_ffmpeg
def test_silent_track_is_passed_through(tmp_path):
    track = write_wav(tmp_path / "in.wav", speech_like_wav(2.0, 44100, 0.0))
    out = tmp_path / "out.wav"
    rec, warns = mux_mod.normalize_track("ffmpeg", track, out)
    assert "無音" in rec["skipped"] and warns == [] and sha(out) == sha(track)


# ------------------------------------------------------------------ erkit make の合成で

@needs_ffmpeg
@pytest.mark.parametrize("amplitude, spike", [(0.02, 0.0), (0.95, 0.0), (0.25, 1.0), (0.08, 1.0)],
                         ids=["quiet", "loud", "speech-like-peaks", "quiet-with-peaks"])
def test_make_normalizes_the_narration_track(tmp_path, amplitude, spike):
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(), transport=LevelEngine(amplitude, spike=spike))
    assert res.status == "done"
    lufs, tp = ebur128(res.final_mp4)
    assert lufs == pytest.approx(-16.0, abs=1.0) and tp <= -1.5
    loud = res.run["stages"]["mux"]["loudness"]
    assert loud["method"] == "linear gain + true-peak limiter" and loud["after"]["lufs"] == pytest.approx(-16, abs=1)
    assert loud["before"]["lufs"] is not None and isinstance(loud["gain_db"], float)


@needs_ffmpeg
def test_make_keeps_wavs_and_durations_unchanged(tmp_path):
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(), transport=LevelEngine(0.05))
    # 段落ごとの WAV と durations.json の長さは、音量そろえで変わらない（そろえるのは MP4 に入れるトラックだけ）
    before = {p.name: sha(p) for p in res.narration_dir.glob("*.wav")}
    durations = json.loads(res.durations.read_text(encoding="utf-8"))
    again = _build(tmp_path / "2", platform="win32", exporter=_fake_exporter(), transport=LevelEngine(0.05))
    assert {p.name: sha(p) for p in again.narration_dir.glob("*.wav")} == before and before
    for wav in res.narration_dir.glob("*.wav"):  # 合成のままの小さい音（そろえていない）
        assert ebur128(wav)[0] < -20
    assert json.loads(again.durations.read_text(encoding="utf-8"))["items"] == durations["items"]
    assert not list(res.out.glob("**/er-mux-*"))  # 一時フォルダは残らない


@needs_ffmpeg
def test_make_with_silent_narration_skips_normalization(tmp_path):
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(), transport=LevelEngine(0.0))
    assert res.status == "done"
    loud = res.run["stages"]["mux"]["loudness"]
    assert "無音" in loud["skipped"]
