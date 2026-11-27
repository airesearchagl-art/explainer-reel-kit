# -*- coding: utf-8 -*-
"""音声から、各文の中の短い無音（読点の間）を取り出す。

音声そのものは変えない（解析用に 16 kHz で読み出すだけ）。10 ms ごとの音量（RMS）を計算し、最大値の 1.2% 未満が
100 ms 以上続く区間を「文中の無音」とする（文の始まりから 50 ms 以内に始まるものは除く）。
結果は ``{文の id: [[無音の始まり秒, 終わり秒], …]}``（data\\pauses.json）。T.at が語の時刻をここに合わせる。
"""
from __future__ import annotations

import array
import json
import math
import subprocess
from pathlib import Path
from typing import Iterable

RATE = 16000
WIN = 160            # 10 ms
THRESHOLD = 0.012    # 最大値に対する割合
MIN_RUN = 10         # 100 ms
SKIP_HEAD = 5        # 文の始まりから 50 ms 以内に始まる無音は除く


def envelope(audio: Path, ffmpeg: str = 'ffmpeg', stream: str = '0:a:0') -> list[float]:
    """10 ms ごとの RMS（16 kHz モノラルで読み出す）。"""
    raw = subprocess.check_output([ffmpeg, '-nostdin', '-v', 'error', '-i', str(audio), '-map', stream, '-ac', '1',
                                   '-ar', str(RATE), '-f', 's16le', '-'])
    a = array.array('h')
    a.frombytes(raw[:len(raw) // 2 * 2])
    env = []
    for i in range(0, len(a) - WIN, WIN):
        s = 0
        for v in a[i:i + WIN]:
            s += v * v
        env.append(math.sqrt(s / WIN))
    return env


def find_pauses(env: list[float], sentences: Iterable[dict], offset_sec: float = 0.0) -> dict[str, list[list[float]]]:
    """sentences: 中間データの sentences（id・start_sec・end_sec）。offset_sec は env の 0 が動画の何秒か。"""
    thr = max(env) * THRESHOLD if env else 0.0
    out: dict[str, list[list[float]]] = {}
    for e in sentences:
        i0 = int((e['start_sec'] - offset_sec) * 100)
        i1 = min(int((e['end_sec'] - offset_sec) * 100), len(env))
        runs, run = [], None
        for i in range(max(0, i0), i1):
            if env[i] < thr:
                if run is None:
                    run = i
            elif run is not None:
                if i - run >= MIN_RUN and run > i0 + SKIP_HEAD:
                    runs.append([run / 100.0 + offset_sec, i / 100.0 + offset_sec])
                run = None
        out[str(e['id'])] = runs
    return out


def analyze(audio: Path, timeline_doc: dict, out: Path | None = None, ffmpeg: str = 'ffmpeg') -> dict:
    """音声（MP4・WAV）と中間データから pauses を作る。out があれば JSON で書く。"""
    pauses = find_pauses(envelope(audio, ffmpeg), timeline_doc['sentences'])
    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(pauses, ensure_ascii=False, indent=1), encoding='utf-8')
    return pauses
