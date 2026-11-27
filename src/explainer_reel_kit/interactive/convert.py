# -*- coding: utf-8 -*-
"""台本から中間データ（render timeline）を作る（``erkit make`` の interactive）。

:func:`from_storyboard`: 場面の境界は .pptx のスライドの時刻（slides と同じ。mux が音声を置く位置と同じ）、
文はナレーションの段落の文、字幕は文ごと（2 行に入らなければ分ける）。
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Sequence

from .engine import LayoutError, wrap_text
from .subtitles import SUB_MAXW, SUB_SIZE, SUB_WEIGHT, fits_subtitle, wrap_subtitle_info
from .timeline import DEFAULT_WEIGHTS, FORMAT, char_weight

FPS, WIDTH, HEIGHT = 30, 1920, 1080


def _base(total_frames: int, source: dict) -> dict:
    return {"format": FORMAT, "fps": FPS, "width": WIDTH, "height": HEIGHT, "total_frames": total_frames,
            "source": source, "scenes": [], "sentences": [], "cues": []}


def paragraph_sentences(paragraph: str) -> list[str]:
    """1 つの段落の文（ナレーションの合成と同じ分け方。narration.textproc）。"""
    from ..narration.textproc import paragraph_sentences as _paragraph_sentences

    return _paragraph_sentences(paragraph)


def paragraphs_of(text: str) -> list[str]:
    """原稿 → 段落（改行で区切ったまとまり。ナレーションの合成と同じ）。"""
    from ..narration.textproc import split_paragraphs

    return split_paragraphs(text or "")


# ---------------------------------------------------------------- 台本から

def _frame_at(sec: float) -> int:
    """その時刻以降の最初のフレーム（浮動小数の誤差は 1 µs まで丸める）。"""
    return int(math.ceil(sec * FPS - 1e-6))


def _split_by_weight(start: float, end: float, texts: Sequence[str], weights: dict) -> list[tuple[float, float]]:
    """[start, end) を文字の重みで比例配分する。"""
    ws = [max(1e-6, sum(char_weight(c, weights) for c in t)) for t in texts]
    total = sum(ws)
    out, t = [], start
    for w in ws:
        t1 = t + (end - start) * w / total
        out.append((t, t1))
        t = t1
    if out:
        out[-1] = (out[-1][0], end)
    return out


def _comma_ok(text: str) -> bool:
    """1 行に収まるか、読点・句点の直後で 2 行に折れる。"""
    try:
        lines, at_comma = wrap_subtitle_info(text)
    except LayoutError:
        return False
    return len(lines) == 1 or at_comma


def split_for_subtitles(text: str) -> list[str]:
    """字幕 1 つに入らない文を分ける（字幕の中の改行は読点の直後だけ）。

    読点で区切った断片を前から詰め、1 行に収まるか読点の直後で 2 行に折れる所までを 1 つの字幕にする。
    読点の無い 1 行より長い断片だけは、2 行に入れば読点以外で折り（verify の記録に残る）、入らなければ幅で分ける
    （英数字の途中・禁則では切らない）。
    """
    if _comma_ok(text):
        return [text]
    parts = [p for p in re.findall(r"[^、]*、?", text) if p]   # 読点の直後で区切った断片
    out: list[str] = []
    cur = ""
    for p in parts:
        if cur and not _comma_ok(cur + p):
            out.append(cur)
            cur = ""
        cur += p
    if cur:
        out.append(cur)
    fixed: list[str] = []
    for s in out:   # 読点の無い長い断片は、幅で 2 行ずつに分ける（英数字の途中・禁則では切らない）
        if fits_subtitle(s):
            fixed.append(s)
            continue
        lines = wrap_text(s, SUB_WEIGHT, SUB_SIZE, SUB_MAXW * 0.98)
        for k in range(0, len(lines), 2):
            chunk = "".join(lines[k:k + 2])
            if not fits_subtitle(chunk):
                chunk_lines = lines[k:k + 2]
                fixed.extend(chunk_lines)
            else:
                fixed.append(chunk)
    for s in fixed:
        if not fits_subtitle(s):
            raise LayoutError(f"字幕を 2 行に収められません: {s}")
    return fixed


def subtitle_text(sentence: str) -> str:
    """字幕に出す文（文末の句点だけ落とす）。"""
    return sentence[:-1] if sentence.endswith("。") and len(sentence) > 1 else sentence


def _scene_card(doc: dict, sid: str) -> dict:
    """既定の場面の見出し・文（画像が無い場面用）。文字だけのカード（recipe_params.card）は、その見出しと文。"""
    if sid == "intro":
        intro = doc.get("intro") or {}
        body = [intro.get("summary", "")] + [f"・{p}" for p in intro.get("prerequisites") or []]
        return {"title": doc["reel"]["title"], "body": [b for b in body if b]}
    if sid == "outro":
        outro = doc.get("outro") or {}
        body = [outro.get("summary", "")] + [f"・{c}" for c in outro.get("checks") or []]
        if outro.get("next"):
            body.append(str(outro["next"]))
        return {"title": "まとめ", "body": [b for b in body if b]}
    sc = next(s for s in doc["scenes"] if s["id"] == sid)
    card = (sc.get("recipe_params") or {}).get("card")
    if isinstance(card, dict) and isinstance(card.get("title"), str) and card["title"].strip():
        body = [str(card[k]) for k in ("text", "meta") if isinstance(card.get(k), str) and card[k].strip()]
        return {"title": card["title"], "body": body}
    body = sc.get("on_screen_text") or []
    if isinstance(body, str):
        body = [body]
    return {"title": sc.get("heading", ""), "body": [str(b) for b in body]}


def storyboard_subtitles(doc: dict) -> dict[str, dict[int, str]]:
    """台本の字幕の別表記（kit-1.2.0 の subtitles）: {場面 id: {段落の番号（1 から）: 字幕の文}}。合成には使わない。"""
    nodes = [("intro", doc.get("intro"))] + [(s.get("id"), s) for s in doc.get("scenes") or []] + \
            [("outro", doc.get("outro"))]
    out: dict[str, dict[int, str]] = {}
    for sid, node in nodes:
        if isinstance(node, dict) and isinstance(node.get("subtitles"), list):
            out[sid] = {int(x["paragraph"]): str(x["text"]) for x in node["subtitles"]
                        if isinstance(x, dict) and "paragraph" in x and "text" in x}
    return out


def from_storyboard(doc: dict, timings: Sequence[Any], durations: dict, narration_items: dict[str, str], *,
                    images: dict[str, str] | None = None, credit: str | None = None,
                    total_ms: int | None = None, weights: dict | None = None,
                    source: dict | None = None, wav_dir: Path | None = None,
                    readings: dict[str, str] | None = None) -> tuple[dict, list[str]]:
    """台本 → 中間データ。戻り値 (中間データ, 警告)。

    timings: reel.mux.read_slide_timings の結果（SlideTiming: id・start_ms・adv_ms・transition_ms）。
    durations: ナレーションの段の記録（durations.json。pre_pause_sec・items[].wav・audio_sec・chunk_frames・
    chunk_sentences・sample_rate・paragraph_starts_sec・fit.cuts）。narration_items: {場面 id: 原稿}。
    場面の境界はスライドの開始（切替効果の始まり）。ナレーションの WAV はスライド開始 ＋ 切替効果 ＋ pre_pause に置かれる
    （mux と同じ）。

    文の時刻（sync.measure）: 合成の分割の境目は durations.json の chunk_frames から正確に、分割の中の文の
    境目は WAV の無音に寄せる（wav_dir に WAV があるとき。無ければ文字の重みの按分）。chunk_frames の無い古い記録は、
    段落の開始（paragraph_starts_sec）から文字の重みで推定する。
    字幕: 文ごと（文末の句点を落とす）。2 行に入らなければ読点の直後で分け、字幕の中の改行も読点の直後だけ
    （split_for_subtitles）。改行は cues の lines に書く（焼き込みと SRT が同じ行になる）。
    字幕の別表記（台本の subtitles）があれば、その段落の字幕は別表記の文。文の数が原稿と同じなら文ごと、違えば段落の
    時間を文字の重みで分ける。
    images: {場面 id: 画像のパス（中間データのフォルダからの相対か絶対）}。readings: {場面 id: 合成入力（辞書の後）}。
    """
    from . import sync
    from .subtitles import wrap_subtitle

    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    warnings: list[str] = []
    if total_ms is None:
        total_ms = sum(t.adv_ms + t.transition_ms for t in timings)
    # 時刻 → フレーム: その時刻以降の最初のフレーム（字幕と同じ規則。動画はナレーションのトラックより短くならない）
    total = _frame_at(total_ms / 1000)
    out = _base(total, source or {"kind": "storyboard", "reel_id": doc["reel"]["id"]})
    out["meta"] = {"title": doc["reel"]["title"], "credit": credit}
    starts = [_frame_at(t.start_ms / 1000) for t in timings] + [total]
    for k, t in enumerate(timings):
        card = _scene_card(doc, t.id)
        sc = {"id": t.id, "title": card["title"], "start_frame": starts[k], "end_frame": starts[k + 1]}
        if images and images.get(t.id):
            sc["image"] = images[t.id]
        if card["body"]:
            sc["body"] = card["body"]
        out["scenes"].append(sc)

    pre = float(durations.get("pre_pause_sec", 0.3))
    items = {it["id"]: it for it in durations.get("items") or [] if isinstance(it, dict) and "id" in it}
    alt = storyboard_subtitles(doc)
    cue_list: list[dict] = []

    def add_cues(sentence_id: str, text: str, a: float, b: float, runs: list[tuple[float, float]]) -> None:
        pieces = split_for_subtitles(subtitle_text(text))
        for (ca, cb), piece in zip(sync.split_piece_times(a, b, pieces, runs, w), pieces):
            cue_list.append({"sentence": sentence_id, "text": piece, "lines": wrap_subtitle(piece),
                             "start_frame": _frame_at(ca), "end_frame": _frame_at(cb)})

    for t in timings:
        item = items.get(t.id)
        text = narration_items.get(t.id, "")
        if item is None or not text.strip():
            if text.strip():
                warnings.append(f"{t.id}: durations.json に記録が無いため、文と字幕を作りません")
            continue
        wav0 = (t.start_ms + t.transition_ms) / 1000 + pre
        wav = Path(wav_dir) / str(item.get("wav", f"{t.id}.wav")) if wav_dir else None
        runs_local = sync.item_silences(wav) if wav is not None and wav.is_file() else []
        m = sync.measure(text, item, wav or Path("-"), weights=w, runs=runs_local)
        warnings += [f"{t.id}: {x}" for x in m["warnings"]]
        runs = [(wav0 + s, wav0 + e) for s, e in runs_local]
        prepared = [paragraph_sentences(p) for p in paragraphs_of(readings[t.id])] if readings and \
            readings.get(t.id) else None
        n = 0
        for i, (sents, times) in enumerate(zip(m["sentences"], m["paragraphs"])):
            reads = prepared[i] if prepared and i < len(prepared) and len(prepared[i]) == len(sents) else None
            sub = alt.get(t.id, {}).get(i + 1)
            sub_sents = (paragraph_sentences(sub) or [sub]) if sub else None
            per_sentence = sub_sents is None or len(sub_sents) == len(sents)
            ids = []
            for j, (s, (a, b)) in enumerate(zip(sents, times)):
                n += 1
                sid = f"{t.id}-{n}"
                ids.append((sid, wav0 + a, wav0 + b))
                entry = {"id": sid, "scene": t.id, "paragraph": i + 1, "spoken": s,
                         "start_sec": round(wav0 + a, 3), "end_sec": round(wav0 + b, 3), "timing": m["timing"]}
                if reads:
                    entry["reading"] = reads[j]
                if sub_sents and per_sentence:
                    entry["subtitle"] = sub_sents[j]
                out["sentences"].append(entry)
                if per_sentence:
                    add_cues(sid, sub_sents[j] if sub_sents else s, wav0 + a, wav0 + b, runs)
            if not per_sentence:   # 別表記の文の数が原稿と違う: 段落の時間を、別表記の文字の重みで分ける
                for entry in out["sentences"][-len(sents):]:
                    entry["subtitle"] = sub
                pa, pb = ids[0][1], ids[-1][2]
                pieces = [p for s2 in sub_sents for p in split_for_subtitles(subtitle_text(s2))]
                for (ca, cb), piece in zip(sync.split_piece_times(pa, pb, pieces, runs, w), pieces):
                    owner = next((x[0] for x in ids if x[1] <= ca + 1e-6 < x[2]), ids[-1][0])
                    cue_list.append({"sentence": owner, "text": piece, "lines": wrap_subtitle(piece),
                                     "start_frame": _frame_at(ca), "end_frame": _frame_at(cb)})
    prev = 0
    for c in cue_list:   # 丸めで重なったら後ろへ寄せる。場面の外へ出たら切る
        c["start_frame"] = max(c["start_frame"], prev)
        c["end_frame"] = min(c["end_frame"], total)
        if c["end_frame"] <= c["start_frame"]:
            warnings.append(f"字幕「{c['text']}」は表示が 0 フレームになるため出しません")
            continue
        out["cues"].append(c)
        prev = c["end_frame"]
    return out, warnings


def storyboard_images(doc: dict, assets_dir: Path, rel_to: Path | None = None) -> dict[str, str]:
    """場面 id → 画像（work/assets の複製）。rel_to があればそこからの相対パス（/ 区切り）。

    文字だけのカード（recipe_params.card）の場面は画像を使わない（既定の場面はカードを描く）。
    """
    out: dict[str, str] = {}
    entries = [(sc["id"], None if _is_card(sc) else sc.get("image")) for sc in doc.get("scenes") or []]
    entries.append(("outro", (doc.get("outro") or {}).get("image")))
    for sid, img in entries:
        ref = img.get("ref") if isinstance(img, dict) else None
        if not ref:
            continue
        p = Path(assets_dir) / ref
        if not p.is_file():
            continue
        if rel_to is not None:
            try:
                out[sid] = p.resolve().relative_to(Path(rel_to).resolve()).as_posix()
                continue
            except ValueError:
                pass
        out[sid] = str(p)
    return out


def _is_card(scene: dict) -> bool:
    card = (scene.get("recipe_params") or {}).get("card")
    return isinstance(card, dict) and isinstance(card.get("title"), str) and bool(card["title"].strip())
