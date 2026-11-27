"""固定尺の枠（slot）にナレーションを収める。

場面の長さが決まっているときは、台本の ``slot_sec``（kit-1.2.0）（スライドの表示秒。切替効果の時間は
含まない）を durations.json の ``slide_sec`` にする。ナレーション（前の余白 ＋ WAV ＋ 後ろの余白）が枠を超えるときは、
**音声を伸縮せずに**、次の順に無音を詰める。

1. 文の前後の無音: WAV の頭と終わりの無音（エンジンが付ける）と、後ろの余白（post_pause_sec）
2. 文の間の無音: WAV の中の 0.3 秒以上の無音（すべて同じ割合で、0.2 秒までは残す）

それでも収まらなければ :class:`SlotOverflowError`（超過の秒数と、話速を上げる・文を短くする・枠を延ばすの選択肢）で止まる。
前の余白（pre_pause_sec）は変えない（WAV を置く位置は slides・interactive・mux と同じ）。

詰めた WAV は ``<id>.fit.wav``（合成した ``<id>.wav`` は変えない）。durations.json の item は、置く音声
（``wav``・``audio_sec``・``slide_sec``・``paragraph_starts_sec``）を詰めた後の値にし、合成したときの値を
``fit.source`` に残す（``erkit voice synth``・``erkit make`` のナレーションの段は ``fit.source`` に戻して WAV の使い回しを判定する）。

無音の検出（:func:`silences`）と詰めた WAV の秒への換算（:func:`map_sec`）は、interactive の文の時刻（interactive/sync.py）と同じ決まり。
"""

from __future__ import annotations

import array
import io
import json
import math
import wave
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import NarrationError
from .synth import DURATIONS_FILENAME, FIT_SOURCE_FIELDS, _atomic_write, synthesized_record

WIN_SEC = 0.01           # 音量を測る窓
THRESHOLD = 0.012        # 最大値に対する割合（interactive の文中の無音と同じ）
MIN_EDGE_SEC = 0.05      # WAV の頭・終わりに残す無音
MIN_POST_SEC = 0.1       # 後ろの余白の最小
GAP_MIN_RUN_SEC = 0.3    # 詰める「文の間の無音」の長さ（これより短い読点の間は詰めない）
GAP_KEEP_SEC = 0.2       # 文の間の無音に残す長さ


class SlotOverflowError(NarrationError):
    """無音を詰めても固定尺の枠に収まらない（勝手に伸縮しない）。"""

    exit_code = 2

    def __init__(self, overflows: list["Overflow"]):
        self.overflows = overflows
        super().__init__("固定尺の枠に収まらない場面があります:\n" + "\n".join(o.message() for o in overflows))


@dataclass(frozen=True)
class Overflow:
    id: str
    slot_sec: float
    need_sec: float       # 詰める前（余白を含む）
    min_sec: float        # 詰められるだけ詰めた後
    speech_sec: float     # 声の部分（無音を除く）
    speed: float

    @property
    def over_sec(self) -> float:
        return self.min_sec - self.slot_sec

    def message(self) -> str:
        over = self.over_sec
        speed = self.speed * self.speech_sec / max(self.speech_sec - over, 1e-6)
        ratio = over / max(self.speech_sec, 1e-6)
        return (f"  - {self.id}: 枠 {self.slot_sec:.2f} 秒に対し、ナレーション {self.need_sec:.2f} 秒"
                f"（無音を詰めて {self.min_sec:.2f} 秒）。{over:.2f} 秒超えます。選択肢: "
                f"① 話速を上げる（今 {self.speed:.2f}、目安 {math.ceil(speed * 100) / 100:.2f} 以上。reel.voice.speed）"
                f" ② 文を短くする（声の部分を約 {ratio * 100:.0f}% 減らす）"
                f" ③ 枠を延ばす（slot_sec を {math.ceil(self.min_sec * 100) / 100:.2f} 以上）")


@dataclass(frozen=True)
class FitPlan:
    id: str
    slot_sec: float
    need_sec: float
    cuts: list[tuple[int, int]]   # 合成した WAV から抜くフレーム (開始, 数)
    removed_sec: float
    post_sec: float               # 詰めた後の後ろの余白

    @property
    def squeezed(self) -> bool:
        return bool(self.cuts)


# ---------------------------------------------------------------- 無音の検出

def silences(path: Path) -> tuple[list[tuple[int, int]], int, int]:
    """WAV の無音の区間（フレーム）。戻り値 ([(開始, 終わり), …], 全フレーム数, サンプルレート)。

    16 bit PCM だけ（エンジンの出力）。10 ms ごとの RMS が最大値の 1.2% 未満の窓が続く所を無音とする。
    """
    with wave.open(str(path), "rb") as reader:
        ch, width, rate, n = reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()
        raw = reader.readframes(n)
    if width != 2:
        raise NarrationError(f"16 bit PCM の WAV だけ扱えます: {path}")
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    if ch > 1:
        samples = samples[::ch]
    win = max(1, int(rate * WIN_SEC))
    env = []
    for i in range(0, len(samples), win):
        block = samples[i:i + win]
        env.append(math.sqrt(sum(v * v for v in block) / len(block)) if block else 0.0)
    thr = (max(env) if env else 0.0) * THRESHOLD
    runs: list[tuple[int, int]] = []
    start = None
    for k, v in enumerate(env + [thr + 1.0]):
        if v <= thr:
            if start is None:
                start = k
        elif start is not None:
            runs.append((start * win, min(k * win, n)))
            start = None
    return runs, n, rate


def plan_fit(item: Mapping[str, Any], wav: Path, slot_sec: float, *, pre_pause_sec: float,
             post_pause_sec: float, speed: float = 1.0) -> FitPlan:
    """1 つの item を枠に収める計画。収まらなければ SlotOverflowError。"""
    runs, n, rate = silences(wav)
    audio = n / rate
    need = pre_pause_sec + audio + post_pause_sec
    sid = str(item["id"])
    if need <= slot_sec + 1e-9:
        return FitPlan(sid, slot_sec, need, [], 0.0, slot_sec - pre_pause_sec - audio)

    head = next(((a, b) for a, b in runs if a == 0), None)
    tail = next(((a, b) for a, b in runs if b == n and a > 0), None)
    inner = [(a, b) for a, b in runs if (a, b) not in (head, tail) and (b - a) / rate >= GAP_MIN_RUN_SEC]
    keep_edge = int(MIN_EDGE_SEC * rate)
    keep_gap = int(GAP_KEEP_SEC * rate)

    # 1) 文の前後の無音: WAV の頭・終わり、後ろの余白
    edge_cap = {"head": max(0, (head[1] - head[0]) - keep_edge) if head else 0,
                "tail": max(0, (tail[1] - tail[0]) - keep_edge) if tail else 0}
    post_cap = max(0.0, post_pause_sec - MIN_POST_SEC)
    cap1 = (edge_cap["head"] + edge_cap["tail"]) / rate + post_cap
    # 2) 文の間の無音
    gap_caps = [max(0, (b - a) - keep_gap) for a, b in inner]
    cap2 = sum(gap_caps) / rate
    over = need - slot_sec
    speech = audio - sum(b - a for a, b in runs) / rate
    if over > cap1 + cap2 + 1e-9:
        raise SlotOverflowError([Overflow(sid, slot_sec, need, need - cap1 - cap2, max(speech, 0.0), speed)])

    cuts: list[tuple[int, int]] = []
    r1 = min(1.0, over / cap1) if cap1 > 0 else 0.0
    if head and edge_cap["head"]:
        k = int(math.ceil(edge_cap["head"] * r1))
        if k:
            cuts.append((head[0], k))                                            # 頭の無音は先頭から抜く
    if tail and edge_cap["tail"]:
        k = int(math.ceil(edge_cap["tail"] * r1))
        if k:
            cuts.append((tail[1] - k, k))                                        # 終わりの無音は最後から抜く
    rest = over - cap1 * r1
    if rest > 1e-9 and cap2 > 0:
        r2 = min(1.0, rest / cap2)
        for (a, b), cap in zip(inner, gap_caps):
            k = int(math.ceil(cap * r2))
            if k:
                mid = (a + b) // 2
                cuts.append((mid - k // 2, k))                                   # 無音の真ん中から抜く
    cuts.sort()
    removed = sum(k for _, k in cuts) / rate
    post = slot_sec - pre_pause_sec - (audio - removed)
    if post < MIN_POST_SEC - 1e-6:   # 丸めの分だけ足りないとき（起きない想定）
        raise SlotOverflowError([Overflow(sid, slot_sec, need, pre_pause_sec + audio - removed + MIN_POST_SEC,
                                          max(speech, 0.0), speed)])
    return FitPlan(sid, slot_sec, need, cuts, removed, post)


def map_sec(sec: float, cuts: list[list[float]]) -> float:
    """合成した WAV の秒 → 詰めた WAV の秒（cuts は [[抜いた始まり秒, 終わり秒], …]、合成した WAV の秒）。"""
    out = sec
    for a, b in cuts:
        if sec >= b:
            out -= b - a
        elif sec > a:
            out -= sec - a
    return out


def _write_cut_wav(src: Path, dst: Path, cuts: list[tuple[int, int]]) -> int:
    with wave.open(str(src), "rb") as reader:
        params = reader.getparams()
        data = reader.readframes(reader.getnframes())
    fb = params.nchannels * params.sampwidth
    parts, pos = [], 0
    for a, k in cuts:
        parts.append(data[pos * fb:a * fb])
        pos = a + k
    parts.append(data[pos * fb:])
    body = b"".join(parts)
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(params.nchannels)
        writer.setsampwidth(params.sampwidth)
        writer.setframerate(params.framerate)
        writer.writeframes(body)
    _atomic_write(dst, out.getvalue())
    return len(body) // fb


def fit_slots(narration_dir: Path, slots: Mapping[str, float], *, speed: float = 1.0,
              log: Callable[[str], None] = print) -> dict[str, Any]:
    """durations.json の item を枠に合わせて書き換える。戻り値は記録（run.json に残す形）。

    収まらない場面が 1 つでもあれば、durations.json を変えずに SlotOverflowError（すべての場面を並べる）。
    """
    narration_dir = Path(narration_dir)
    path = narration_dir / DURATIONS_FILENAME
    doc = json.loads(path.read_text(encoding="utf-8"))
    pre = float(doc.get("pre_pause_sec", 0.3))
    post = float(doc.get("post_pause_sec", 0.5))
    items = {it["id"]: i for i, it in enumerate(doc.get("items") or []) if isinstance(it, dict) and "id" in it}
    plans: list[tuple[int, dict[str, Any], FitPlan]] = []
    overflows: list[Overflow] = []
    missing = [sid for sid in slots if sid not in items]
    if missing:
        raise NarrationError(f"固定尺の枠の場面が durations.json にありません: {', '.join(missing)}")
    for sid, slot in slots.items():
        index = items[sid]
        rec = synthesized_record(doc["items"][index])   # 前の実行で詰めた記録は、合成したときの値に戻してから
        try:
            plans.append((index, rec, plan_fit(rec, narration_dir / rec["wav"], float(slot),
                                               pre_pause_sec=pre, post_pause_sec=post, speed=speed)))
        except SlotOverflowError as e:
            overflows += e.overflows
    if overflows:
        raise SlotOverflowError(overflows)

    report: dict[str, Any] = {}
    for index, rec, plan in plans:
        source = {k: rec[k] for k in FIT_SOURCE_FIELDS if k in rec}
        new = dict(rec)
        rate = int(rec.get("sample_rate") or 0) or None
        fit: dict[str, Any] = {"slot_sec": plan.slot_sec, "need_sec": round(plan.need_sec, 3),
                               "removed_sec": round(plan.removed_sec, 3), "post_pause_sec": round(plan.post_sec, 3),
                               "source": source}
        if plan.squeezed:
            src = narration_dir / rec["wav"]
            dst = narration_dir / f"{rec['id']}.fit.wav"
            frames = _write_cut_wav(src, dst, plan.cuts)
            with wave.open(str(dst), "rb") as reader:
                rate = reader.getframerate()
            cuts_sec = [[round(a / rate, 6), round((a + k) / rate, 6)] for a, k in plan.cuts]
            fit["cuts"] = cuts_sec
            new["wav"] = dst.name
            new["audio_sec"] = round(frames / rate, 3)
            new["paragraph_starts_sec"] = [round(map_sec(s, cuts_sec), 3) for s in rec.get("paragraph_starts_sec") or []]
            log(f"[slot] {rec['id']}: 枠 {plan.slot_sec:.2f}s に、無音を {plan.removed_sec:.2f}s 詰めて収めました"
                f"（{len(plan.cuts)} か所、後ろの余白 {plan.post_sec:.2f}s）")
        else:
            log(f"[slot] {rec['id']}: 枠 {plan.slot_sec:.2f}s（ナレーション {plan.need_sec:.2f}s、後ろは無音）")
        new["slide_sec"] = float(Decimal(str(plan.slot_sec)).quantize(Decimal("0.01"), rounding=ROUND_CEILING))
        new["fit"] = fit
        doc["items"][index] = new
        report[rec["id"]] = {k: v for k, v in fit.items() if k != "source"}
    _atomic_write(path, (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return report


def slot_seconds(doc: Mapping[str, Any]) -> dict[str, float]:
    """台本の固定尺の枠（kit-1.2.0 の slot_sec）: {item id: 秒}。item id は intro / シーン id / outro。"""
    nodes = [("intro", doc.get("intro"))] + [(s.get("id"), s) for s in doc.get("scenes") or [] if isinstance(s, dict)] + \
            [("outro", doc.get("outro"))]
    return {str(sid): float(n["slot_sec"]) for sid, n in nodes if isinstance(n, dict) and n.get("slot_sec")}
