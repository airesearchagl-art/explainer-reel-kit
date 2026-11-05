"""台本 → アニメーション付き .pptx。

スライド構成は intro → scenes → outro。全スライド自動切替（クリック進行なし）。
赤枠・矢印の位置は撮影画像・説明図の隣の <画像名>.marks.json から決める（marks.py）。
"""
from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from .. import storyboard as sb
from . import marks as marks_mod
from . import recipes
from .marks import Annotation, Unresolved
from .textfit import fit_scale, one_line_scale
from .zoom import FULL, View, compute_view, is_per_mark, parse_zoom
from .recipes import SceneShapes
from .timing import MORPH_MS, Effect, Step, attach, build_morph_transition, build_timing, build_transition, fit_to_budget, total_ms

SLIDE_W = Emu(12192000)  # 13.333in（PowerPoint 標準のワイド 16:9）
SLIDE_H = Emu(6858000)  # 7.5in
DEFAULT_SLIDE_SEC = 6.0
TRANSITION_MS = 750  # フェード切替（spd=med）の目安
TAIL_MS = 300  # 最後の効果が終わってから切り替わるまでの余裕
MIN_PART_MS = 800  # zoom: per_mark で分けたスライド 1 枚の最短表示（変形の後）
MIN_MORPH_MS = 300
DURATIONS_FORMAT = "explainer-reel/narration-durations"

FONT = "Yu Gothic UI"
PLACEHOLDER_LABEL = "撮影前（仮）"
INK = RGBColor(0x22, 0x22, 0x22)
MUTED = RGBColor(0x6B, 0x6B, 0x6B)
ACCENT = RGBColor(0xD9, 0x2D, 0x20)
PLACEHOLDER_FILL = RGBColor(0xE6, 0xE6, 0xE6)
PLACEHOLDER_LINE = RGBColor(0x99, 0x99, 0x99)

RASTER_OK = {".png", ".jpg", ".jpeg", ".gif"}
RASTER_CONVERT = {".webp"}


class BuildError(Exception):
    """デッキを生成できない（台本不正、manual 画像の欠落、durations.json の形式違い）。"""


@dataclass
class BuildResult:
    output: Path
    slide_count: int
    adv_ms: list[int] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)  # 置いた赤枠・矢印（位置つき）
    unresolved: list[Unresolved] = field(default_factory=list)  # 未確定の注釈（既定位置で置いた）
    marks_files: list[str] = field(default_factory=list)
    views: dict[str, View] = field(default_factory=dict)  # 拡大したシーンの表示範囲（元画像に対する比）
    # zoom: per_mark で分けたシーン: {scene id: [{"part", "view", "adv_ms", "morph_ms"}]}
    split: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    slide_ids: list[str] = field(default_factory=list)  # スライドごとの名前（er:<id> / er:<id>#<n>）
    overlay: Path | None = None
    video_sec: float | None = None  # 動画の長さ（durations.json があるときだけ。イントロの所要時間に表示）
    text_cards: list[str] = field(default_factory=list)  # 文字だけのカードにしたシーン（プレースホルダーではない）

    def unresolved_text(self) -> str:
        return ", ".join(u.text() for u in self.unresolved)


# ---------------------------------------------------------------- storyboard / durations

def load_storyboard(path: Path, assets_root: Path | None) -> dict[str, Any]:
    try:
        doc = sb.load_storyboard(path)
    except sb.ConversionError as e:
        raise BuildError(f"台本を読めません: {e}") from e
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BuildError(f"台本を読めません: {e}") from e
    rep = sb.validate_storyboard(doc, base_dir=assets_root or path.parent)
    if not rep.ok:
        raise BuildError("台本が検証を通りません:\n  " + "\n  ".join(rep.errors))
    return doc


def load_durations(path: Path) -> tuple[dict[str, float], list[str]]:
    """ナレーションの durations.json（narration-durations）から {id: slide_sec} を作る。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise BuildError(f"durations.json を読めません: {e}") from e
    if not isinstance(data, dict) or data.get("format") != DURATIONS_FORMAT:
        raise BuildError(f"durations.json の format が '{DURATIONS_FORMAT}' ではありません")
    warnings = []
    if data.get("complete") is False:
        warnings.append("durations.json が complete=false（途中で失敗した実行の記録）です。不足分は既定秒数を使います")
    out: dict[str, float] = {}
    for item in data.get("items") or []:
        sid, sec = item.get("id"), item.get("slide_sec")
        if isinstance(sid, str) and isinstance(sec, (int, float)) and sec > 0:
            out[sid] = float(sec)
        else:
            warnings.append(f"durations.json の item を読み飛ばしました: {item!r}")
    return out, warnings


def load_cues(path: Path) -> tuple[float, dict[str, list[float]]]:
    """durations.json から、ナレーションの段落ごとの開始時刻（WAV 先頭からの秒）を読む。

     items[].paragraph_starts_sec。無い item は均等割りになる（呼び出し側が警告）。
    戻り値 (pre_pause_sec, {id: [秒, …]})。
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return 0.0, {}
    pre = data.get("pre_pause_sec", 0.3)
    pre = float(pre) if isinstance(pre, (int, float)) else 0.3
    out: dict[str, list[float]] = {}
    for item in data.get("items") or []:
        starts = item.get("paragraph_starts_sec") if isinstance(item, dict) else None
        if isinstance(starts, list) and starts and all(isinstance(v, (int, float)) and v >= 0 for v in starts):
            out[item["id"]] = [float(v) for v in starts]
    return pre, out


# ---------------------------------------------------------------- text helpers

def _set_font(run, size: float, bold: bool = False, color: RGBColor = INK) -> None:
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    f.name = FONT
    rpr = run._r.get_or_add_rPr()
    # 日本語として扱わせる（PowerPoint の行頭禁則・改行規則が日本語の規則になる）
    rpr.set("lang", "ja-JP")
    rpr.set("altLang", "en-US")
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", FONT)


def _add_text(slide, left, top, width, height, paragraphs, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT, name=None,
              fit: bool = False, line_spacing: float | None = None, space_after: float | None = None,
              one_line: bool = False):
    """paragraphs: [(text, size, bold, color)]

    fit=True なら、枠からはみ出さないよう文字サイズを縮める（textfit.py の見積もり）。
    one_line=True（1 段落のとき）は、少し（0.75 倍まで）縮めれば 1 行に収まるなら 1 行にする（タイトル）。
    折り返しの見積もりは行頭禁則を考える。line_spacing は行間の倍率、space_after は段落の後ろの間隔（pt）。
    """
    scale = 1.0
    one = None
    if one_line and len(paragraphs) == 1:
        one = one_line_scale(paragraphs[0][0], paragraphs[0][1], int(width))
    if one is not None:
        scale = one
    elif fit:
        scale = fit_scale([(t, sz) for t, sz, _, _ in paragraphs], int(width), int(height),
                          line_spacing or 1.0, space_after or 0.0)
    tb = slide.shapes.add_textbox(left, top, width, height)
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, (text, size, bold, color) in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p._p.get_or_add_pPr().set("eaLnBrk", "1")  # 東アジアの改行規則（行頭禁則）を使う
        if line_spacing:
            p.line_spacing = line_spacing
        if space_after is not None and i < len(paragraphs) - 1:
            p.space_after = Pt(space_after * scale)
        run = p.add_run()
        run.text = text
        _set_font(run, round(size * scale, 1), bold, color)
    return tb


def _set_notes(slide, narration: str) -> None:
    slide.notes_slide.notes_text_frame.text = narration or ""


# ---------------------------------------------------------------- images

def _fit(img_w: int, img_h: int, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left, top, bw, bh = box
    scale = min(bw / img_w, bh / img_h)
    w, h = int(img_w * scale), int(img_h * scale)
    return left + (bw - w) // 2, top + (bh - h) // 2, w, h


def _placeholder(slide, box, ref: str, reason: str):
    left, top, bw, bh = box
    # 16:9 の枠を領域内に収める
    l, t, w, h = _fit(16, 9, box)
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, l, t, w, h)
    shp.name = "Image Placeholder"
    shp.fill.solid()
    shp.fill.fore_color.rgb = PLACEHOLDER_FILL
    shp.line.color.rgb = PLACEHOLDER_LINE
    shp.line.width = Pt(1.5)
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = f"{reason}: {ref}"
    _set_font(run, 16, False, MUTED)
    return shp, (l, t, w, h)


def _resolve(ref: str, base: Path) -> Path:
    return (base / ref).resolve()


def _image_file(image: dict[str, Any], base: Path) -> Path | None:
    """貼れる撮影画像のファイル（無い・未対応の形式なら None）。"""
    path = _resolve(image["ref"], base)
    if path.is_file() and path.suffix.lower() in RASTER_OK | RASTER_CONVERT:
        return path
    return None


def _add_image(slide, image: dict[str, Any], box, base: Path, result: BuildResult, where: str, view: View = FULL):
    """主画像を置く。戻り値 (shape, 画像の矩形, テキストを持つ図形か, 画像ファイル or None)。"""
    ref = image["ref"]
    path = _resolve(ref, base)
    suffix = path.suffix.lower()
    if not path.is_file():
        if image["source"] == "manual":
            raise BuildError(f"{where}: manual 画像が見つかりません: {ref}（起点 {base}）")
        result.placeholders.append(ref)
        shp, rect = _placeholder(slide, box, ref, "撮影予定")
        return shp, rect, True, None
    if suffix not in RASTER_OK | RASTER_CONVERT:
        result.warnings.append(f"{where}: {suffix} は貼り付けに未対応のためプレースホルダーにしました: {ref}")
        result.placeholders.append(ref)
        shp, rect = _placeholder(slide, box, ref, "未対応の形式")
        return shp, rect, True, None
    with Image.open(path) as im:
        iw, ih = im.size
        # 拡大（view）: 切り出す範囲の縦横比で枠に収め、表示は crop で切り出す（元画像はそのまま埋め込む）
        cw, ch = iw * view.w, ih * view.h
        if suffix in RASTER_CONVERT:
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
            buf.seek(0)
            src: Any = buf
        else:
            src = str(path)
    l, t, w, h = _fit(cw, ch, box)
    pic = slide.shapes.add_picture(src, l, t, w, h)
    if not view.is_full:
        pic.crop_left, pic.crop_top = view.x, view.y
        pic.crop_right, pic.crop_bottom = 1 - view.x - view.w, 1 - view.y - view.h
    if image.get("alt"):
        pic._element.nvPicPr.cNvPr.set("descr", image["alt"])
    return pic, (l, t, w, h), False, path


# ---------------------------------------------------------------- text card

CARD_FILL = RGBColor(0xF3, 0xF5, 0xF8)
CARD_LINE = RGBColor(0xD5, 0xDA, 0xE1)


def parse_card(params: dict[str, Any], warn, where: str) -> dict[str, str] | None:
    """recipe_params.card = {title, text, meta}（文字だけのカード）。title は必須、text / meta は任意。"""
    card = params.get("card")
    if card is None:
        return None
    if not isinstance(card, dict) or not isinstance(card.get("title"), str) or not card["title"].strip() \
            or any(k in card and not isinstance(card[k], str) for k in ("text", "meta")):
        warn(f"{where}: recipe_params.card は {{title: 文字列, text: 文字列, meta: 文字列}} で書いてください。画像として扱います")
        return None
    return {"title": card["title"].strip(), "text": (card.get("text") or "").strip(), "meta": (card.get("meta") or "").strip()}


def _add_card(slide, card: dict[str, str], box):
    """画像の代わりに、表示名・説明文・プラットフォームを大きく見せるカード（1 つの図形。画像と同じくフェードイン）。"""
    left, top, bw, bh = box
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, bw, bh)
    shp.name = "Text Card"
    shp.adjustments[0] = 0.04
    shp.fill.solid()
    shp.fill.fore_color.rgb = CARD_FILL
    shp.line.color.rgb = CARD_LINE
    shp.line.width = Pt(1)
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for m in ("margin_left", "margin_right"):
        setattr(tf, m, Inches(0.8))
    paras = [(card["title"], 44, True, INK, 18)]
    if card["text"]:
        paras.append((card["text"], 26, False, INK, 14))
    if card["meta"]:
        paras.append((card["meta"], 20, False, MUTED, 0))
    scale = fit_scale([(t, sz) for t, sz, _, _, _ in paras], int(bw - Inches(1.6)), int(bh - Inches(0.4)), 1.15, 14)
    for i, (text, size, bold, color, after) in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = 1.15
        if after:
            p.space_after = Pt(after * scale)
        run = p.add_run()
        run.text = text
        _set_font(run, round(size * scale, 1), bold, color)
    return shp


# ---------------------------------------------------------------- recipe params

def _num01(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1


def _lines(scene: dict, params: dict, warn, where: str) -> list[str]:
    v = params.get("lines")
    if v is not None:
        if isinstance(v, list) and v and all(isinstance(s, str) and s for s in v):
            return list(v)
        warn(f"{where}: recipe_params.lines は空でない文字列の配列で指定してください。on_screen_text を使います")
    text = scene.get("on_screen_text") or ""
    return [ln for ln in text.splitlines() if ln.strip()] if text else []


# ---------------------------------------------------------------- slides

HEAD_BOX = (Inches(0.5), Inches(0.3), Inches(12.333), Inches(0.85))
IMAGE_BOX = (Inches(0.5), Inches(1.25), Inches(12.333), Inches(5.1))
TEXT_BOX = (Inches(0.5), Inches(6.45), Inches(10.2), Inches(0.9))
LABEL_BOX = (Inches(10.83), Inches(6.95), Inches(2.0), Inches(0.4))


def to_slide(rect: tuple[int, int, int, int], p: dict[str, float]) -> tuple[float, float]:
    """撮影画像の相対座標 → スライド上の位置（EMU）。rect は画像を縦横比を保って置いた矩形。"""
    l, t, w, h = rect
    return l + w * p["x"], t + h * p["y"]


ARROW_W, ARROW_H = Inches(0.9), Inches(0.45)


def _add_box(slide, rect, b: dict[str, float], name: str):
    x0, y0 = to_slide(rect, {"x": b["x"], "y": b["y"]})
    x1, y1 = to_slide(rect, {"x": b["x"] + b["w"], "y": b["y"] + b["h"]})
    box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, int(round(x0)), int(round(y0)),
                                 max(int(round(x1 - x0)), 1), max(int(round(y1 - y0)), 1))
    box.name = name
    box.fill.background()
    box.line.color.rgb = ACCENT
    box.line.width = Pt(4.5)
    box.shadow.inherit = False
    return box


def _add_arrow(slide, rect, start: dict[str, float], end: dict[str, float]):
    """先端が start にある矢印を置き、end までの移動量（スライド比）を返す。"""
    x0, y0 = to_slide(rect, start)
    x1, y1 = to_slide(rect, end)
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)
    ux, uy = (dx / dist, dy / dist) if dist > 0 else (1.0, 0.0)
    cx, cy = x0 - ux * ARROW_W / 2, y0 - uy * ARROW_W / 2  # 回転は中心まわり。先端 = 中心 + 半長 × 向き
    arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, int(round(cx - ARROW_W / 2)), int(round(cy - ARROW_H / 2)),
                                   ARROW_W, ARROW_H)
    arrow.name = "Moving Arrow"
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = ACCENT
    arrow.line.fill.background()
    arrow.shadow.inherit = False
    arrow.rotation = math.degrees(math.atan2(uy, ux))
    return arrow, (dx / SLIDE_W, dy / SLIDE_H)


def _scene_slide(prs, scene: dict, base: Path, result: BuildResult, warn, adv_ms: int | None = None,
                 cue_ms: list[int] | None = None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    where = f"scene {scene['id']}"
    sh = SceneShapes()
    params = scene.get("recipe_params") or {}
    recipe = scene["recipe"]

    head = _add_text(slide, *HEAD_BOX, [(scene["heading"], 28, True, INK)], anchor=MSO_ANCHOR.MIDDLE, name="Heading")
    sh.heading = head.shape_id

    # 注釈の位置（元画像に対する相対座標）を先に決め、拡大する範囲を求めてから画像を置く
    sm = marks_mod.resolve_scene(scene, _image_file(scene["image"], base))
    view = FULL
    want_zoom, margin, zoom_err = parse_zoom(params.get("zoom"))
    if zoom_err:
        warn(f"{scene['id']}: {zoom_err}")
    if want_zoom:
        file = _image_file(scene["image"], base)
        if recipe not in ("highlight_box", "arrow_move"):
            warn(f"{scene['id']}: zoom は highlight_box / arrow_move でだけ使えます（拡大しません）")
        elif file is None:
            pass  # 撮影前は拡大しない（プレースホルダーとして別に数える）
        elif sm.unresolved:
            warn(f"{scene['id']}: 未確定の注釈があるため拡大しません")
        else:
            with Image.open(file) as im:
                size = im.size
            view, why = compute_view(sm.annotations, size, IMAGE_BOX[2] / IMAGE_BOX[3], margin)
            if why:
                warn(f"{scene['id']}: {why}")
    if not view.is_full:
        result.views[scene["id"]] = view

    card = parse_card(params, warn, where)
    if card is not None:
        # 文字だけのカード（画像が無いツール）: 撮影前ではないのでプレースホルダーに数えず、来歴ラベルも出さない
        img, rect, img_is_shape, img_path = _add_card(slide, card, IMAGE_BOX), IMAGE_BOX, True, None
        result.text_cards.append(scene["id"])
    else:
        img, rect, img_is_shape, img_path = _add_image(slide, scene["image"], IMAGE_BOX, base, result, where, view)
    sh.image = img.shape_id
    sh.image_is_shape = img_is_shape

    lines = _lines(scene, params, warn, where) if recipe == "text_build" else (
        [scene["on_screen_text"]] if scene.get("on_screen_text") else [])
    if lines:
        tb = _add_text(slide, *TEXT_BOX, [(ln, 20, False, INK) for ln in lines], name="On-screen Text")
        sh.text = tb.shape_id
        sh.text_paragraphs = len(lines)
    elif recipe == "text_build":
        warn(f"{where}: text_build ですが on_screen_text がありません。見出しと画像のみ表示します")

    if card is None:
        label_text = PLACEHOLDER_LABEL if img_is_shape else scene["image"]["label"]  # 撮影前は来歴を名乗らない
        label = _add_text(slide, *LABEL_BOX, [(label_text, 10, False, MUTED)],
                          anchor=MSO_ANCHOR.BOTTOM, align=PP_ALIGN.RIGHT, name="Provenance Label")
        sh.label = label.shape_id

    for w in sm.warnings:
        warn(w)
    result.unresolved += sm.unresolved
    if sm.marks_file is not None:
        result.marks_files.append(str(sm.marks_file))

    arrow_delta = (0.0, 0.0)
    for a in sm.annotations:
        if a.kind == "box":
            name = "Highlight Box" if a.index == 0 else f"Highlight Box {a.index + 1}"
            box = _add_box(slide, rect, view.map_box(a.box), name)
            sh.boxes.append(box.shape_id)
            a.slide_emu = {"left": box.left, "top": box.top, "width": box.width, "height": box.height}
        else:
            start, end = view.map_point(a.start), view.map_point(a.end)
            arrow, arrow_delta = _add_arrow(slide, rect, start, end)
            sh.arrow = arrow.shape_id
            x0, y0 = to_slide(rect, start)
            x1, y1 = to_slide(rect, end)
            a.slide_emu = {"start_x": int(round(x0)), "start_y": int(round(y0)),
                           "end_x": int(round(x1)), "end_y": int(round(y1))}
        result.annotations.append(a)
    if sh.boxes:
        sh.box = sh.boxes[0]

    steps, fade = recipes.scene_steps(recipe, sh, params, SLIDE_W, SLIDE_H, arrow_delta, adv_ms=adv_ms, cue_ms=cue_ms)
    _set_notes(slide, scene["narration"])
    return slide, steps, fade, img_path, sm, view


SPLIT_SHOT = "!!Shot"  # 分けたスライドの間で同じものとして扱う図形（Morph の !! 接頭辞）
SPLIT_BOX = "!!Box"


def split_timeline(n: int, scene_ms: int, targets: list[int]) -> tuple[list[int], list[int], list[str]]:
    """枠ごとのスライドの自動切替（advTm）と変形の長さ。

    targets[k] は枠 k を見せ始める時刻（シーン開始からの ms）。スライド k（k ≥ 1）への変形は
    targets[k] に始まる。合計（advTm の和 ＋ 変形の長さの和）は scene_ms と一致する。
    戻り値 (advTm[n], 変形の長さ[n]（[0] は 0）, 警告)。
    """
    warnings: list[str] = []
    ends = [targets[k + 1] if k + 1 < n else scene_ms for k in range(n)]
    adv = [0] * n
    morph = [0] * n
    adv[0] = max(targets[1] if n > 1 else scene_ms, 1)
    for k in range(1, n):
        gap = ends[k] - targets[k]
        morph[k] = int(min(MORPH_MS, max(MIN_MORPH_MS, gap - MIN_PART_MS)))
        adv[k] = gap - morph[k]
        if adv[k] < MIN_PART_MS // 2:
            warnings.append(f"枠 {k + 1} の表示が {adv[k]}ms と短すぎるため {MIN_PART_MS // 2}ms にしました（合計が延びます）")
            adv[k] = MIN_PART_MS // 2
    return adv, morph, warnings


def _scene_split_slides(prs, scene: dict, base: Path, result: BuildResult, warn, sm, scene_ms: int,
                        cue_ms: list[int] | None):
    """zoom: per_mark — 枠の数だけスライドを作り、枠ごとに拡大して Morph でつなぐ。

    見出し・画面テキスト・出所ラベルは全スライドで同じ名前・同じ位置。撮影画像（!!Shot）と赤枠（!!Box）は
    同じ名前にして、変形で「カメラが移動する」ように見せる。ナレーションは最初のスライドのノートに入れる。
    戻り値 [(slide, steps, 切替の種類, advTm, 変形の長さ, 一覧画像用 (scene, 画像, [注釈], View))]。
    """
    sid = scene["id"]
    params = scene.get("recipe_params") or {}
    _, margin, _ = parse_zoom(params.get("zoom"))
    file = _image_file(scene["image"], base)
    with Image.open(file) as im:
        size = im.size
    frame = IMAGE_BOX[2] / IMAGE_BOX[3]
    boxes = [a for a in sm.annotations if a.kind == "box"]
    n = len(boxes)

    # 本体（見出し・画像・画面テキスト）が出る時間 → 枠を見せ始める時刻
    base_end = recipes.LEAD_IN + recipes.FADE + recipes.GAP + recipes.IMAGE_FADE + (
        recipes.GAP + recipes.FADE if scene.get("on_screen_text") else 0)
    targets = recipes.box_targets(n, base_end, scene_ms, cue_ms)
    adv, morph, w = split_timeline(n, scene_ms, targets)
    for x in w:
        warn(f"{sid}: {x}")

    for x in sm.warnings:
        warn(x)
    if sm.marks_file is not None:
        result.marks_files.append(str(sm.marks_file))

    out = []
    parts = []
    for k, a in enumerate(boxes):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        sh = SceneShapes()
        head = _add_text(slide, *HEAD_BOX, [(scene["heading"], 28, True, INK)], anchor=MSO_ANCHOR.MIDDLE,
                         name="Heading")
        sh.heading = head.shape_id
        view, why = compute_view([a], size, frame, margin)
        if why:
            warn(f"{sid}: 枠 {k + 1}（{a.mark}）: {why}")
        img, rect, _, img_path = _add_image(slide, scene["image"], IMAGE_BOX, base, result, f"scene {sid}", view)
        img.name = SPLIT_SHOT
        sh.image = img.shape_id
        if scene.get("on_screen_text"):
            tb = _add_text(slide, *TEXT_BOX, [(scene["on_screen_text"], 20, False, INK)], name="On-screen Text")
            sh.text = tb.shape_id
        _add_text(slide, *LABEL_BOX, [(scene["image"]["label"], 10, False, MUTED)],
                  anchor=MSO_ANCHOR.BOTTOM, align=PP_ALIGN.RIGHT, name="Provenance Label")
        box = _add_box(slide, rect, view.map_box(a.box), SPLIT_BOX)
        a.slide_emu = {"left": box.left, "top": box.top, "width": box.width, "height": box.height}
        a.part = k
        result.annotations.append(a)

        if k == 0:
            sh.boxes = [box.shape_id]
            steps, _ = recipes.scene_steps("highlight_box", sh, params, SLIDE_W, SLIDE_H, adv_ms=adv[0])
            _set_notes(slide, scene["narration"])
        else:
            # 変形で前の枠・前の範囲から移ってくる。着いたら枠を 1 回点滅させる
            steps = [Step([Effect("blink", box.shape_id, dur=recipes.BLINK, delay=recipes.GAP,
                                  is_text_shape=True, anim_bg=True)])]
            _set_notes(slide, "")
        out.append((slide, steps, "morph" if k else "none", adv[k], morph[k], (
            {**scene, "id": f"{sid}#{k + 1}"}, img_path, [a], view)))
        parts.append({"part": k, "mark": a.mark, "view": view.record(), "adv_ms": adv[k], "morph_ms": morph[k]})
    result.split[sid] = parts
    return out


INTRO_THUMB_BOX = (Inches(7.4), Inches(1.2), Inches(5.43), Inches(5.4))


UNMEASURED = ("", "未計測")
DURATION_SAMPLE = "所要時間: 約 10 分 00 秒"  # 文字サイズを決めるときの仮の文字列（後で実際の長さに置き換える）


def format_duration(sec: float) -> str:
    """動画の長さ → 「約 1 分 28 秒」「約 45 秒」（秒は四捨五入）。"""
    total = int(round(sec))
    m, s = divmod(total, 60)
    return f"約 {m} 分 {s} 秒" if m else f"約 {s} 秒"


def _duration_line(intro: dict, measured: bool) -> str | None:
    """台本に具体的な値があればそれ。未計測・空なら、秒数が分かる（durations あり）ときだけ後で入れる。"""
    note = str(intro.get("duration_note") or "").strip()
    if note not in UNMEASURED:
        return f"所要時間: {note}"
    return DURATION_SAMPLE if measured else None


def _intro_slide(prs, doc: dict, base: Path | None = None, measured: bool = False):
    """左にタイトル・概要・前提、右に最初のシーンの撮影画像の縮小（画像が無ければ文字だけ）。

    measured=True（durations.json がある）なら、所要時間が未計測・空のとき、仮の行を置いておき、
    全スライドの秒数が決まった後で動画の長さに置き換える（build_deck）。"""
    reel, intro = doc["reel"], doc["intro"]
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    thumb = None
    if base is not None and doc.get("scenes"):
        thumb = _image_file(doc["scenes"][0]["image"], base)
    text_w = Inches(6.5) if thumb is not None else Inches(11.733)
    order: list[tuple[int, bool]] = []
    t = _add_text(slide, Inches(0.8), Inches(1.0), text_w, Inches(1.9),
                  [(reel["title"], 36, True, INK)], anchor=MSO_ANCHOR.BOTTOM, name="Title", fit=True, one_line=True)
    order.append((t.shape_id, True))
    s = _add_text(slide, Inches(0.8), Inches(3.0), text_w, Inches(1.5),
                  [(intro["summary"], 22, False, INK)], name="Summary", fit=True, line_spacing=1.1)
    order.append((s.shape_id, True))
    meta = []
    prereq = intro.get("prerequisites") or []
    if prereq:
        meta.append(("前提", 16, True, MUTED))
        meta += [(f"・{x}", 16, False, INK) for x in prereq]
    dline = _duration_line(intro, measured)
    if dline is not None:
        meta.append((dline, 16, False, MUTED))
    if meta:
        m = _add_text(slide, Inches(0.8), Inches(4.6), text_w, Inches(2.5), meta, name="Prerequisites",
                      fit=True, line_spacing=1.1, space_after=4)
        order.append((m.shape_id, True))
    if thumb is not None:
        with Image.open(thumb) as im:
            iw, ih = im.size
            src: Any = str(thumb)
            if thumb.suffix.lower() in RASTER_CONVERT:
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, format="PNG")
                buf.seek(0)
                src = buf
        l, tp, w, h = _fit(iw, ih, INTRO_THUMB_BOX)
        pic = slide.shapes.add_picture(src, l, tp, w, h)
        pic.name = "Intro Thumbnail"
        pic.line.color.rgb = PLACEHOLDER_LINE
        pic.line.width = Pt(0.75)
        order.append((pic.shape_id, False))
    _set_notes(slide, intro["narration"])
    return slide, recipes.intro_outro_steps(order)


def _fill_duration(slide, video_sec: float) -> None:
    """イントロの仮の所要時間の行を、動画の長さに置き換える。"""
    for shp in slide.shapes:
        if shp.name != "Prerequisites":
            continue
        for p in shp.text_frame.paragraphs:
            for r in p.runs:
                if r.text == DURATION_SAMPLE:
                    r.text = f"所要時間: {format_duration(video_sec)}"


def _outro_slide(prs, doc: dict, base: Path, result: BuildResult, credit: str | None = None):
    outro = doc["outro"]
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    has_image = isinstance(outro.get("image"), dict)
    text_w = Inches(6.4) if has_image else Inches(12.333)
    order: list[tuple[int, bool]] = []
    h = _add_text(slide, Inches(0.5), Inches(0.3), text_w, Inches(0.85), [("まとめ", 28, True, INK)],
                  anchor=MSO_ANCHOR.MIDDLE, name="Heading")
    order.append((h.shape_id, True))
    s = _add_text(slide, Inches(0.5), Inches(1.3), text_w, Inches(1.4), [(outro["summary"], 22, False, INK)],
                  name="Summary", fit=True, line_spacing=1.1)
    order.append((s.shape_id, True))
    body = []
    checks = outro.get("checks") or []
    if checks:
        body.append(("確認すること", 16, True, MUTED))
        body += [(f"・{c}", 15, False, INK) for c in checks]
    if outro.get("next"):
        body.append((f"次の行動: {outro['next']}", 16, True, INK))
    if body:
        # 確認項目は行間と項目の間隔を空けて並べ、はみ出すなら文字を縮める
        b = _add_text(slide, Inches(0.5), Inches(2.9), text_w, Inches(4.0), body, name="Checks",
                      fit=True, line_spacing=1.25, space_after=8)
        order.append((b.shape_id, True))
    if has_image:
        img, _, is_text, _ = _add_image(slide, outro["image"], (Inches(7.2), Inches(1.3), Inches(5.633), Inches(5.6)),
                                        base, result, "outro")
        order.append((img.shape_id, is_text))
    if credit:
        # クレジットが必要な声（config/kit.yaml の voice.credits）。アニメーションさせず常に表示する
        _add_text(slide, Inches(0.5), Inches(6.95), Inches(9.0), Inches(0.4),
                  [(f"ナレーション音声: {credit}", 12, False, MUTED)], anchor=MSO_ANCHOR.BOTTOM, name="Voice Credit")
    _set_notes(slide, outro["narration"])
    return slide, recipes.intro_outro_steps(order)


# ---------------------------------------------------------------- entry point

def build_deck(storyboard: Path, out: Path, durations: Path | None = None, assets_root: Path | None = None,
               default_sec: float = DEFAULT_SLIDE_SEC, credit: str | None = None,
               overlay: Path | None = None) -> BuildResult:
    """credit: outro に表示する音声クレジット（クレジット必須の声のときだけ渡す）。
    overlay: 確認用の一覧画像（赤枠・矢印を撮影画像に描いたもの）の出力先。
    """
    storyboard = Path(storyboard)
    base = Path(assets_root) if assets_root else storyboard.parent
    doc = load_storyboard(storyboard, Path(assets_root) if assets_root else None)
    result = BuildResult(output=Path(out), slide_count=0)
    warn = result.warnings.append

    dur_map: dict[str, float] = {}
    cues: dict[str, list[float]] = {}
    pre_pause = 0.0
    if durations:
        dur_map, w = load_durations(Path(durations))
        result.warnings.extend(w)
        pre_pause, cues = load_cues(Path(durations))

    def slide_sec(sid: str, fallback: float | None) -> float:
        if durations:
            if sid in dur_map:
                return dur_map[sid]
            warn(f"{sid}: durations.json に id がないため {'duration_sec' if fallback else '既定秒数'} を使います")
        return float(fallback) if fallback else float(default_sec)

    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    # plan: (slide, steps, 切替の種類 none / fade / morph, スライド名, advTm, 変形の長さ)
    plan: list[tuple[Any, list, str, str, int, int]] = []
    overlay_entries = []
    sl, st = _intro_slide(prs, doc, base, measured=bool(durations))
    intro_slide = sl
    plan.append((sl, st, "none", "intro", int(round(slide_sec("intro", doc["intro"].get("duration_sec")) * 1000)), 0))
    for scene in doc["scenes"]:
        sid = scene["id"]
        sec = slide_sec(sid, scene.get("duration_sec"))
        scene_ms = int(round(sec * 1000))
        cue_ms = [int(round((pre_pause + c) * 1000)) for c in cues[sid]] if sid in cues else None
        image_file = _image_file(scene["image"], base)
        sm = marks_mod.resolve_scene(scene, image_file)
        n_boxes = sum(1 for a in sm.annotations if a.kind == "box")
        if n_boxes > 1 and cue_ms is not None and len(cue_ms) != n_boxes:
            warn(f"{sid}: 枠 {n_boxes} 個とナレーションの段落 {len(cue_ms)} 個が合わないため、時刻は均等に割りました")
            cue_ms = None
        elif n_boxes > 1 and durations and cue_ms is None:
            warn(f"{sid}: durations.json に段落の開始時刻（paragraph_starts_sec）がないため、枠の時刻は均等に割りました")

        params = scene.get("recipe_params") or {}
        if is_per_mark(params.get("zoom")) and scene["recipe"] == "highlight_box" and n_boxes > 1:
            if image_file is None or sm.unresolved:
                warn(f"{sid}: zoom: per_mark は撮影画像と全注釈の位置がそろったときだけ使えます（1 枚のスライドで作ります）")
            else:
                parts = _scene_split_slides(prs, scene, base, result, warn, sm, scene_ms, cue_ms)
                for k, (sl, st, kind, adv, morph, entry) in enumerate(parts):
                    plan.append((sl, st, kind, f"{sid}#{k + 1}", adv, morph))
                    overlay_entries.append(entry)
                continue
        elif is_per_mark(params.get("zoom")) and scene["recipe"] != "highlight_box":
            warn(f"{sid}: zoom: per_mark は highlight_box でだけ使えます")

        sl, st, fade, img_path, sm, view = _scene_slide(prs, scene, base, result, warn, scene_ms, cue_ms)
        kind = "morph" if scene["recipe"] == "morph_transition" else ("fade" if fade else "none")
        plan.append((sl, st, kind, sid, scene_ms, MORPH_MS if kind == "morph" else 0))
        overlay_entries.append((scene, img_path, sm.annotations, view))
    sl, st = _outro_slide(prs, doc, base, result, credit=credit)
    plan.append((sl, st, "none", "outro", int(round(slide_sec("outro", doc["outro"].get("duration_sec")) * 1000)), 0))

    if durations:
        known = {p[3].split("#")[0] for p in plan}
        extra = sorted(set(dur_map) - known)
        if extra:
            warn(f"durations.json に台本にない id があります（無視）: {', '.join(extra)}")

    total_video_ms = 0
    for slide, steps, kind, name, adv, morph in plan:
        budget = adv - TAIL_MS - (TRANSITION_MS if kind == "fade" else 0)
        before = total_ms(steps)
        steps, shrunk = fit_to_budget(steps, max(budget, 0))
        if shrunk:
            warn(f"{name}: アニメーション合計 {before}ms が切替 {adv}ms に収まらないため {total_ms(steps)}ms に縮めました")
        if kind == "morph":
            transition = build_morph_transition(adv, morph)
        else:
            transition = build_transition(adv, fade=kind == "fade")
        attach(slide, transition, build_timing(steps))
        # スライドとシーンの対応を残す（音声の合成が、分けたスライドをシーンにまとめるのに使う）
        slide._element.cSld.set("name", f"er:{name}")
        result.slide_ids.append(name)
        result.adv_ms.append(adv)
        # 動画の長さ（音声の合成と同じ: advTm ＋ 切替効果。フェードは 0.75 秒、Morph は変形の長さ）
        total_video_ms += adv + (TRANSITION_MS if kind == "fade" else morph if kind == "morph" else 0)
    result.video_sec = total_video_ms / 1000 if durations else None
    if result.video_sec is not None:
        _fill_duration(intro_slide, result.video_sec)

    result.output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(result.output))
    result.slide_count = len(prs.slides)
    if overlay is not None:
        from .overlay import render_overlay

        result.overlay = render_overlay(overlay_entries, Path(overlay))
    return result
