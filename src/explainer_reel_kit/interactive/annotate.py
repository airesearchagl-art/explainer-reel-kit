# -*- coding: utf-8 -*-
"""台本のシーンの「画面の決まり」を中間データの場面に写す（既定の場面が slides と同じものを出すため）。

slides（deck/builder.py の ``_scene_slide``）と同じものを、同じ順・同じ段落で出す:

- 見出し（``heading``）・画像・画面テキスト（``text``。text_build は 1 行ずつ）・来歴ラベル（``label``）
- 来歴ラベルは画像の ``image.label``（実キャプチャ／途中成果／説明用再構成図）。撮影前（画像が無い・貼れない形式）は
  「撮影前（仮）」。文字だけのカード（``recipe_params.card``）は出さない（slides と同じ）
- 注釈（赤枠・矢印）の位置は slides と同じ ``deck.marks.resolve_scene``（marks.json・recipe_params.box / to）、
  拡大の範囲は ``deck.zoom.compute_view``（slides の画像枠の縦横比で切り出す）
- 出す時刻は slides のアニメーション（``deck.recipes``）と同じ決め方: 枠が複数でナレーションの段落の数と同じなら、
  枠 k は段落 k の始まり（その段落の最初の文の start_sec）。違えば本体が出た後の残りを均等に割る。矢印は本体の後に
  現れて 1.2 秒で動く。zoom: per_mark は枠ごとの範囲へ、段落の始まりから移る（slides の Morph の代わり）

位置は元の画像に対する 0〜1 の相対座標のまま記録し、画面の座標には既定の場面（scenes.default_scene）が写す。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ..deck import recipes as rc

PLACEHOLDER_LABEL = "撮影前（仮）"   # deck.builder.PLACEHOLDER_LABEL と同じ
DEFAULT_LABEL = "説明用再構成図"      # 来歴の分からない画像（台本から作っていない中間データ・scenes.yaml の静止画）
RASTER = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# slides の画像枠（deck.builder.IMAGE_BOX: 12.333 × 5.1 インチ）の縦横比。拡大の範囲は slides と同じに切り出す
DECK_FRAME_ASPECT = 12.333 / 5.1
MORPH_SEC = 1.0


def _sec(ms: float) -> float:
    return round(ms / 1000.0, 3)


def parse_card(params: Mapping[str, Any]) -> dict[str, str] | None:
    """recipe_params.card（文字だけのカード）。title が無ければ None（slides の parse_card と同じ判定）。"""
    card = params.get("card")
    if not isinstance(card, dict) or not isinstance(card.get("title"), str) or not card["title"].strip() \
            or any(k in card and not isinstance(card[k], str) for k in ("text", "meta")):
        return None
    out = {"title": card["title"].strip()}
    for k in ("text", "meta"):
        if (card.get(k) or "").strip():
            out[k] = card[k].strip()
    return out


def screen_lines(scene: Mapping[str, Any]) -> list[str]:
    """画面テキスト（slides の TEXT_BOX）: text_build は recipe_params.lines か on_screen_text の行、ほかは on_screen_text。"""
    params = scene.get("recipe_params") or {}
    text = scene.get("on_screen_text") or ""
    if scene.get("recipe") == "text_build":
        v = params.get("lines")
        if isinstance(v, list) and v and all(isinstance(s, str) and s for s in v):
            return list(v)
        return [ln for ln in str(text).splitlines() if ln.strip()]
    return [str(text)] if text else []


def appear_times(start: float, recipe: str | None, n_text: int) -> tuple[dict, float]:
    """見出し・画像・画面テキストの出る時刻（slides の _base_sequence と text_build）。戻り値 (appear, 本体の終わり ms)。"""
    if recipe == "morph_transition":   # slides はフェード切替で、中身は最初から出ている
        return {"heading": start, "image": start, "text": [start] * n_text}, 0
    t = rc.LEAD_IN
    heading = t
    t += rc.FADE
    image = t + rc.GAP
    t = image + rc.IMAGE_FADE
    texts: list[float] = []
    if n_text and recipe != "text_build":
        texts = [t + rc.GAP] * n_text
        t += rc.GAP + rc.FADE
    base_end = t
    if n_text and recipe == "text_build":
        for _ in range(n_text):
            texts.append(t + rc.GAP)
            t += rc.GAP + rc.FADE
    return ({"heading": round(start + _sec(heading), 3), "image": round(start + _sec(image), 3),
             "text": [round(start + _sec(x), 3) for x in texts]}, base_end)


def chain_end(recipe: str | None, base_end: int, n_text: int, n_boxes: int, targets: Sequence[int] = ()) -> int:
    """slides の効果の連鎖が終わる ms（スライドの始まりから）。"""
    end = base_end
    if recipe == "text_build":
        end += n_text * (rc.GAP + rc.FADE)
    if recipe == "highlight_box" and n_boxes:
        cursor = base_end
        for k, t in enumerate(targets):
            delay = max(t - cursor, rc.GAP if k else 0)
            cursor += delay + (rc.BOX_EXIT if k else 0) + rc.BOX_FADE + rc.BLINK
        end = cursor
    if recipe == "arrow_move":
        end = base_end + rc.GAP + rc.ARROW_FADE + rc.ARROW_MOVE
    return end


def _scale_times(out: dict, start: float, k: float) -> None:
    """slides の fit_to_budget と同じく、効果の時刻と長さを同じ比率で縮める（スライドの秒に収まらないとき）。"""
    def sc(v: float) -> float:
        return round(start + (v - start) * k, 3)

    ap = out["appear"]
    ap["heading"], ap["image"] = sc(ap["heading"]), sc(ap["image"])
    ap["text"] = [sc(v) for v in ap["text"]]
    for a in out.get("annotations") or []:
        for key in ("at_sec", "until_sec", "move_sec"):
            if a.get(key) is not None:
                a[key] = sc(a[key])
        if "move_dur_sec" in a:
            a["move_dur_sec"] = round(a["move_dur_sec"] * k, 3)


def box_schedule(base_end: int, targets: Sequence[int]) -> list[tuple[int, int]]:
    """枠ごとの (前の枠を消し始める ms, 枠が現れ始める ms)。slides の recipes._box_steps と同じ連鎖。"""
    out: list[tuple[int, int]] = []
    cursor = base_end
    prev = False
    for t in targets:
        delay = max(t - cursor, rc.GAP if prev else 0)
        start = cursor + delay
        fin = start + (rc.BOX_EXIT if prev else 0)
        out.append((start, fin))
        cursor += delay + (rc.BOX_EXIT if prev else 0) + rc.BOX_FADE + rc.BLINK
        prev = True
    return out


def paragraph_starts(sentences: Sequence[Mapping[str, Any]], sid: str) -> list[float]:
    """場面の段落ごとの始まり（その段落の最初の文の start_sec）。"""
    firsts: dict[int, float] = {}
    for s in sentences:
        if s.get("scene") == sid and isinstance(s.get("paragraph"), int):
            p = s["paragraph"]
            firsts[p] = min(firsts.get(p, s["start_sec"]), s["start_sec"])
    return [firsts[k] for k in sorted(firsts)]


def _image_size(path: Path | None) -> tuple[int, int] | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except OSError:
        return None


def _view_rec(v) -> dict:
    return {k: round(getattr(v, k), 4) for k in ("x", "y", "w", "h")}


def _box_rec(b: Mapping[str, float]) -> dict:
    return {k: round(float(b[k]), 4) for k in b}


def scene_display(scene: Mapping[str, Any], *, start: float, scene_ms: int, image_file: Path | None,
                  has_image: bool, sentences: Sequence[Mapping[str, Any]]) -> tuple[dict, list[str]]:
    """台本のシーン 1 つ → 中間データの場面に足す項目（heading・label・placeholder・card・text・appear・recipe・view・
    annotations）。戻り値 (項目, 警告)。

    start: 場面の始まり（秒、スライドの開始）。scene_ms: スライドの秒（ms。枠の時刻を均等に割るときに使う）。
    image_file: 画像のファイル（marks.json は隣）。has_image: 既定の場面が画像を出すか（False なら撮影前）。
    """
    from ..deck import marks as dmarks
    from ..deck.zoom import FULL, compute_view, is_per_mark, parse_zoom

    sid = scene["id"]
    warnings: list[str] = []
    recipe = scene.get("recipe")
    params = scene.get("recipe_params") or {}
    if not isinstance(params, dict):
        params = {}
    out: dict[str, Any] = {"heading": str(scene.get("heading") or "")}
    if recipe:
        out["recipe"] = recipe
    card = parse_card(params)
    img = scene.get("image") if isinstance(scene.get("image"), dict) else {}
    usable = has_image and image_file is not None and Path(image_file).suffix.lower() in RASTER
    if card is not None:
        out["card"] = card
    elif usable:
        out["label"] = str(img.get("label") or DEFAULT_LABEL)
    else:
        out["label"] = PLACEHOLDER_LABEL   # 撮影前は来歴を名乗らない（slides と同じ）
        reason = "未対応の形式" if has_image else "撮影予定"
        out["placeholder"] = {"ref": str(img.get("ref") or ""), "reason": reason}
    lines = screen_lines(scene)
    if lines:
        out["text"] = lines
    appear, base_end = appear_times(start, recipe, len(lines))
    out["appear"] = appear

    budget = scene_ms - rc.TAIL_MS - (750 if recipe == "morph_transition" else 0)
    if recipe not in ("highlight_box", "arrow_move") or card is not None:   # カードに注釈は描かない
        end = chain_end(recipe, base_end, len(lines), 0)
        if recipe != "morph_transition" and 0 < budget < end:
            _scale_times(out, start, budget / end)
        return out, warnings
    sm = dmarks.resolve_scene(dict(scene), Path(image_file) if usable else None)
    warnings += sm.warnings
    warnings += [f"{u.text()}（既定の位置に置きます）" for u in sm.unresolved]
    size = _image_size(image_file) if usable else None

    # 拡大（slides と同じ範囲）
    view = FULL
    want_zoom, margin, _ = parse_zoom(params.get("zoom"))
    if want_zoom and size is not None and not sm.unresolved:
        view, _why = compute_view(sm.annotations, size, DECK_FRAME_ASPECT, margin)
    boxes = [a for a in sm.annotations if a.kind == "box"]
    per_mark = (is_per_mark(params.get("zoom")) and recipe == "highlight_box" and len(boxes) > 1
                and size is not None and not sm.unresolved)
    if not view.is_full and not per_mark:
        out["view"] = _view_rec(view)

    paras = paragraph_starts(sentences, sid)
    cue_ms = [int(round((p - start) * 1000)) for p in paras] if paras else None
    anns: list[dict[str, Any]] = []
    end = chain_end(recipe, base_end, len(lines), 0)   # 効果の連鎖の終わり（枠は下で数え直す）
    if recipe == "highlight_box" and boxes:
        n = len(boxes)
        if per_mark:
            from ..deck.builder import split_timeline

            # slides: 本体（見出し・画像・画面テキスト）の後に枠 1、枠 k（k ≥ 2）は段落 k の始まりから変形で移る
            targets = rc.box_targets(n, base_end, scene_ms, cue_ms if cue_ms and len(cue_ms) == n else None)
            _, morph, _ = split_timeline(n, scene_ms, targets)
            for k, a in enumerate(boxes):
                v, _ = compute_view([a], size, DECK_FRAME_ASPECT, margin)
                rec = {"kind": "box", "mark": a.mark, "status": a.status, "box": _box_rec(a.box), "view": _view_rec(v)}
                if k == 0:
                    rec["at_sec"] = round(start + _sec(base_end + rc.GAP), 3)
                else:
                    rec["morph_sec"] = round(start + _sec(targets[k]), 3)
                    rec["morph_dur_sec"] = _sec(morph[k])
                    rec["at_sec"] = round(start + _sec(targets[k] + morph[k]), 3)
                if cue_ms and len(cue_ms) == n:
                    rec["paragraph"] = k + 1
                anns.append(rec)
            for k in range(n - 1):
                anns[k]["until_sec"] = anns[k + 1]["morph_sec"]
            out["view"] = anns[0]["view"]
        else:
            use_cue = cue_ms if cue_ms is not None and len(cue_ms) == n else None
            targets = rc.box_targets(n, base_end, scene_ms, use_cue)
            sched = box_schedule(base_end, targets)
            end = chain_end(recipe, base_end, len(lines), n, targets)
            for k, (a, (_, fin)) in enumerate(zip(boxes, sched)):
                rec = {"kind": "box", "mark": a.mark, "status": a.status, "box": _box_rec(a.box),
                       "at_sec": round(start + _sec(fin), 3)}
                if use_cue is not None:
                    rec["paragraph"] = k + 1
                if k + 1 < n:
                    rec["until_sec"] = round(start + _sec(sched[k + 1][0]), 3)
                anns.append(rec)
    elif recipe == "arrow_move":
        for a in sm.annotations:
            if a.kind != "arrow":
                continue
            t0 = base_end + rc.GAP
            anns.append({"kind": "arrow", "mark": a.mark, "status": a.status, "start": _box_rec(a.start),
                         "end": _box_rec(a.end), "at_sec": round(start + _sec(t0), 3),
                         "move_sec": round(start + _sec(t0 + rc.ARROW_FADE), 3), "move_dur_sec": _sec(rc.ARROW_MOVE)})
    if anns:
        out["annotations"] = anns
    if not per_mark and 0 < budget < end:   # per_mark は slides でも枠ごとのスライドの秒で決まる
        _scale_times(out, start, budget / end)
    return out, warnings
