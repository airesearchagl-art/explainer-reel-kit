# -*- coding: utf-8 -*-
"""文の時刻を WAV の実尺から測る・作り直した前後を比べる。

**文の時刻**（:func:`measure`）: durations.json の item の WAV（場面ごと）について、

1. 合成の分割（chunk）の境目は ``chunk_frames`` から正確に分かる（分割は段落をまたがない）
2. 1 つの分割に文が 2 つ以上あるときは、文字の重みで按分した境目を、WAV の無音（0.15 秒以上）に寄せる。
   無音の終わり（次の文の声の始まり）の 0.1 秒前を次の文の始まりにする（無音の始まりより前にはしない）
3. 固定尺の枠で無音を詰めた item（``fit.cuts``）は、詰めた後の WAV の秒に直す

``chunk_frames`` の無い古い記録は、段落の開始（``paragraph_starts_sec``）と文字の重みだけで推定する（``timing: estimated``）。

**作り直した前後の比較**（:func:`resync_report`）: 前の中間データと新しい中間データの、場面の境界と文の時刻を並べ、
再合成した段落の文と、時刻が動いた文の前後を checks/resync.md・resync.json に一覧で出す。

無音の検出（``silences``）と、詰めた WAV の秒への換算（``map_sec``）は、ナレーションの固定尺の枠
（``narration.fit``。slot_sec で無音を詰める処理）のものを使う（10 ms ごとの RMS が最大値の 1.2% 未満の窓が続く所が無音）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from ..narration.fit import map_sec, silences
from .convert import paragraph_sentences
from .convert import paragraphs_of as split_paragraphs
from .timeline import DEFAULT_WEIGHTS, char_weight

__all__ = ["map_sec", "measure", "resync_report", "silences", "snap", "split_by_weight", "split_piece_times"]

MIN_GAP_SEC = 0.15     # 文の境目に使う無音の長さ
LEAD_SEC = 0.10        # 次の文の字幕を、声の始まりより少し前に出す
PIECE_GAP_SEC = 0.08   # 1 つの文を字幕で分けるときに使う無音（読点の間）


def _weights(texts: Sequence[str], w: dict) -> list[float]:
    return [max(sum(char_weight(ch, w) for ch in t), 1e-6) for t in texts]


def split_by_weight(a: float, b: float, texts: Sequence[str], w: dict | None = None) -> list[tuple[float, float]]:
    """区間 [a, b] を文字の重みで按分する。"""
    w = dict(DEFAULT_WEIGHTS, **(w or {}))
    ws = _weights(texts, w)
    total = sum(ws)
    out, cur = [], a
    for x in ws:
        nxt = cur + (b - a) * x / total
        out.append((cur, nxt))
        cur = nxt
    if out:
        out[-1] = (out[-1][0], b)
    return out


def snap(bounds: list[float], runs: Sequence[tuple[float, float]], *, min_gap: float, window: float,
         lead: float = LEAD_SEC) -> tuple[list[float], int]:
    """推定の境目を近くの無音に寄せる。戻り値 (境目, 寄せた数)。

    bounds は内側の境目だけ（両端は含めない）。各境目について、window 秒以内にある min_gap 秒以上の無音のうち、
    いちばん近いものを使う（同じ無音を 2 回は使わない。順序が逆になる寄せ方はしない）。
    """
    used: set[int] = set()
    out: list[float] = []
    hits = 0
    prev = float("-inf")
    for x in bounds:
        best, best_d = None, None
        for k, (s, e) in enumerate(runs):
            if k in used or e - s < min_gap:
                continue
            mid = (s + e) / 2
            d = abs(mid - x)
            if d <= window and (best_d is None or d < best_d):
                best, best_d = k, d
        if best is not None:
            s, e = runs[best]
            y = max(s, e - lead)
            if y > prev:
                used.add(best)
                out.append(y)
                prev = y
                hits += 1
                continue
        out.append(max(x, prev + 1e-3))
        prev = out[-1]
    return out, hits


def item_silences(wav: Path) -> list[tuple[float, float]]:
    """WAV の無音（秒）。"""
    runs, _, rate = silences(wav)
    return [(a / rate, b / rate) for a, b in runs]


def measure(text: str, record: dict, wav: Path, *, weights: dict | None = None,
            runs: Sequence[tuple[float, float]] | None = None) -> dict[str, Any]:
    """1 つの item の文の時刻（WAV の先頭からの秒）。

    戻り値 {"timing": "measured" | "estimated", "paragraphs": [[(始まり, 終わり), …], …], "snapped": 寄せた数,
    "warnings": [...]}。段落・文の分け方は narration の textproc と同じ（原稿の文）。
    """
    paragraphs = [paragraph_sentences(p) or [p] for p in split_paragraphs(text)]
    audio = float(record.get("audio_sec") or 0.0)
    warnings: list[str] = []
    fit = record.get("fit") if isinstance(record.get("fit"), dict) else {}
    cuts = fit.get("cuts") or []
    frames, counts = record.get("chunk_frames"), record.get("chunk_sentences")
    rate = record.get("sample_rate")
    if runs is None:
        runs = item_silences(wav) if Path(wav).is_file() else []
    # 段落ごとの分割（文の数）を、chunk_sentences と段落の文の数で突き合わせる
    layout: list[list[int]] | None = None
    if isinstance(frames, list) and isinstance(counts, list) and len(frames) == len(counts) and rate:
        layout, k = [], 0
        for sents in paragraphs:
            group, need = [], len(sents)
            while need > 0 and k < len(counts):
                group.append(k)
                need -= int(counts[k])
                k += 1
            if need != 0:
                layout = None
                break
            layout.append(group)
        if layout is not None and k != len(counts):
            layout = None
        if layout is None:
            warnings.append("分割ごとの文の数が原稿と合わないため、文の時刻を推定します")
    out: list[list[tuple[float, float]]] = []
    snapped = 0
    if layout is not None:
        starts, acc = [], 0
        for n in frames:
            starts.append(acc)
            acc += int(n)
        chunk_bounds = [(map_sec(starts[k] / rate, cuts), map_sec((starts[k] + int(frames[k])) / rate, cuts))
                        for k in range(len(frames))]
        for sents, group in zip(paragraphs, layout):
            times: list[tuple[float, float]] = []
            i = 0
            for k in group:
                n = int(counts[k])
                a, b = chunk_bounds[k]
                part = sents[i:i + n]
                i += n
                est = split_by_weight(a, b, part, weights)
                if n > 1:
                    inner = [e for _, e in est[:-1]]
                    avg = (b - a) / n
                    inner, hits = snap(inner, [r for r in runs if a < r[0] and r[1] < b],
                                       min_gap=MIN_GAP_SEC, window=max(0.4, 0.4 * avg))
                    snapped += hits
                    edges = [a, *inner, b]
                    est = [(edges[j], edges[j + 1]) for j in range(n)]
                times += est
            out.append(times)
        timing = "measured"
    else:
        pstarts = record.get("paragraph_starts_sec") or []
        if len(pstarts) != len(paragraphs):
            joined = [s for p in paragraphs for s in p]
            out = [split_by_weight(0.0, audio, joined, weights)]
            sizes = [len(p) for p in paragraphs]
            flat, out = out[0], []
            for n in sizes:
                out.append(flat[:n])
                flat = flat[n:]
            warnings.append(f"段落の数（{len(paragraphs)}）と paragraph_starts_sec（{len(pstarts)}）が違うため、"
                            "全体を文字の重みで按分します")
        else:
            for i, sents in enumerate(paragraphs):
                p0 = float(pstarts[i])
                p1 = float(pstarts[i + 1]) if i + 1 < len(pstarts) else audio
                out.append(split_by_weight(p0, p1, sents, weights))
        timing = "estimated"
    return {"timing": timing, "paragraphs": out, "sentences": paragraphs, "snapped": snapped, "warnings": warnings}


def split_piece_times(a: float, b: float, pieces: Sequence[str], runs: Sequence[tuple[float, float]],
                      weights: dict | None = None) -> list[tuple[float, float]]:
    """1 つの文を字幕で分けるときの時刻（文字の重みで按分し、読点の間の無音に寄せる）。"""
    est = split_by_weight(a, b, pieces, weights)
    if len(pieces) < 2:
        return est
    inner = [e for _, e in est[:-1]]
    inner, _ = snap(inner, [r for r in runs if a < r[0] and r[1] < b], min_gap=PIECE_GAP_SEC,
                    window=max(0.3, 0.3 * (b - a) / len(pieces)), lead=0.0)
    edges = [a, *inner, b]
    return [(edges[j], edges[j + 1]) for j in range(len(pieces))]


# ---------------------------------------------------------------- 作り直した前後の比較

def resync_report(old: dict | None, new: dict, durations: dict | None, out_dir: Path) -> dict:
    """checks\\resync.json・resync.md を書き、記録を返す。

    初めての作成（前の中間データが無く、使い回した WAV も無い）は ``first: true``。合成した段落を「再合成」とは
    書かず、文の一覧も出さない（比べる相手が無い）。"""
    fps = new.get("fps", 30)
    resynth: dict[str, list[int]] = {}
    for it in (durations or {}).get("items") or []:
        if isinstance(it, dict) and it.get("synthesized_paragraphs"):
            resynth[it["id"]] = list(it["synthesized_paragraphs"])
    reused = any(isinstance(it, dict) and it.get("reused_from") for it in (durations or {}).get("items") or [])
    first = old is None and not reused
    rec: dict[str, Any] = {"compared": old is not None, "first": first, "fps": fps, "synthesized_paragraphs": resynth,
                           "scenes": [], "sentences": [], "cues_before": None, "cues_after": len(new.get("cues") or [])}
    old_scenes = {s["id"]: s for s in (old or {}).get("scenes") or []}
    for s in new["scenes"]:
        o = old_scenes.get(s["id"])
        row = {"id": s["id"], "start_frame": s["start_frame"], "end_frame": s["end_frame"]}
        if o is not None:
            row.update(old_start_frame=o["start_frame"], old_end_frame=o["end_frame"],
                       shift_frames=s["start_frame"] - o["start_frame"],
                       length_change_frames=(s["end_frame"] - s["start_frame"]) - (o["end_frame"] - o["start_frame"]))
        rec["scenes"].append(row)
    old_sent = {e["id"]: e for e in (old or {}).get("sentences") or []}
    sents = new.get("sentences") or []
    changed_idx: set[int] = set()
    for i, e in enumerate(sents):
        o = old_sent.get(e["id"])
        para = e.get("paragraph")
        redone = para is not None and para in resynth.get(e["scene"], [])
        moved = o is not None and (abs(o["start_sec"] - e["start_sec"]) > 0.5 / fps
                                   or abs(o["end_sec"] - e["end_sec"]) > 0.5 / fps)
        length = o is not None and abs((o["end_sec"] - o["start_sec"]) - (e["end_sec"] - e["start_sec"])) > 0.5 / fps
        if redone or length or (o is not None and o.get("spoken") != e.get("spoken")):
            changed_idx.add(i)
        e["_moved"] = moved
        e["_redone"] = redone
    show = [] if first else sorted({j for i in changed_idx for j in (i - 1, i, i + 1) if 0 <= j < len(sents)})
    for j in show:
        e = sents[j]
        o = old_sent.get(e["id"])
        row = {"id": e["id"], "scene": e["scene"], "paragraph": e.get("paragraph"), "spoken": e["spoken"],
               "start_sec": e["start_sec"], "end_sec": e["end_sec"],
               "role": "再合成" if e["_redone"] else ("変わった文" if j in changed_idx else "前後の文")}
        if o is not None:
            row.update(old_start_sec=o["start_sec"], old_end_sec=o["end_sec"],
                       shift_sec=round(e["start_sec"] - o["start_sec"], 3) + 0.0,   # + 0.0: -0.0 を 0.0 に
                       length_change_sec=round((e["end_sec"] - e["start_sec"]) - (o["end_sec"] - o["start_sec"]), 3) + 0.0)
        rec["sentences"].append(row)
    for e in sents:
        e.pop("_moved", None)
        e.pop("_redone", None)
    if old is not None:
        rec["cues_before"] = len(old.get("cues") or [])
        rec["total_frames"] = {"before": old.get("total_frames"), "after": new.get("total_frames")}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "resync.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out_dir / "resync.md").write_text(_resync_md(rec), encoding="utf-8")
    return rec


def _f(frame: int | None, fps: int) -> str:
    return "—" if frame is None else f"{frame}（{frame / fps:.3f}s）"


def _resync_md(rec: dict) -> str:
    fps = rec["fps"]
    if rec.get("first"):
        lines = ["# 作り直した前後の比較（resync）", "",
                 "合成: 初めての合成（前の出力なし）。すべての段落を合成しました。",
                 "比べる相手が無いので、時刻の比較はありません（読みや字幕を直して作り直すときに "
                 "--reuse-run で前の出力を渡すと、変わった文と前後をここに出します）。", "",
                 "## 場面の境界", "", "| 場面 | 始まり | 終わり |", "|---|---|---|"]
        for s in rec["scenes"]:
            lines.append(f"| {s['id']} | {_f(s['start_frame'], fps)} | {_f(s['end_frame'], fps)} |")
        return "\n".join(lines) + "\n"
    lines = ["# 作り直した前後の比較（resync）", ""]
    if rec["synthesized_paragraphs"]:
        lines.append("再合成した段落: " + "、".join(f"{k} の段落 {', '.join(map(str, v))}"
                                                 for k, v in rec["synthesized_paragraphs"].items()))
    else:
        lines.append("再合成した段落: なし（WAV はすべて使い回し）")
    lines.append("")
    if not rec["compared"]:
        lines += ["前の中間データが無いため、時刻は比べていません（erkit make --reuse-run か、同じ出力フォルダへの作り直しで比べる）。", ""]
    else:
        tf = rec.get("total_frames") or {}
        lines += [f"全体: {_f(tf.get('before'), fps)} → {_f(tf.get('after'), fps)}、字幕 {rec['cues_before']} → {rec['cues_after']}", ""]
    lines += ["## 場面の境界", "", "| 場面 | 始まり（前） | 始まり（後） | ずれ | 長さの変化 |", "|---|---|---|---|---|"]
    for s in rec["scenes"]:
        lines.append(f"| {s['id']} | {_f(s.get('old_start_frame'), fps)} | {_f(s['start_frame'], fps)} | "
                     f"{s.get('shift_frames', '—')} | {s.get('length_change_frames', '—')} |")
    lines += ["", "## 変わった文とその前後", ""]
    if not rec["sentences"]:
        lines.append("（なし）")
    else:
        lines += ["| 文 | 区分 | 段落 | 前 | 後 | ずれ（秒） | 長さの変化（秒） | 原稿 |", "|---|---|---|---|---|---|---|---|"]
        for e in rec["sentences"]:
            before = f"{e['old_start_sec']:.3f}–{e['old_end_sec']:.3f}" if "old_start_sec" in e else "—"
            lines.append(f"| {e['id']} | {e['role']} | {e.get('paragraph') or '—'} | {before} | "
                         f"{e['start_sec']:.3f}–{e['end_sec']:.3f} | {e.get('shift_sec', '—')} | "
                         f"{e.get('length_change_sec', '—')} | {e['spoken']} |")
    lines.append("")
    return "\n".join(lines)
