"""注釈まわりの拡大、段落時刻、出所ラベル、イントロ・アウトロの配置。"""
import json

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Inches

from deck_helpers import SAMPLES
from test_deck_marks import _box_times, _shape, _story

from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.deck import overlay as ov
from explainer_reel_kit.deck.builder import IMAGE_BOX, PLACEHOLDER_LABEL, _fit
from explainer_reel_kit.deck.marks import Annotation
from explainer_reel_kit.deck.textfit import estimate_height_pt, fit_scale, text_units
from explainer_reel_kit.deck.zoom import FULL, MIN_WIDTH, View, compute_view, parse_zoom

FRAME = IMAGE_BOX[2] / IMAGE_BOX[3]
SIZE = (1920, 1080)


def _box_ann(b, i=0):
    return Annotation("s01", "highlight_box", "box", i, "m", "mark", box=b)


def _px_aspect(v: View, size=SIZE):
    return (v.w * size[0]) / (v.h * size[1])


# ------------------------------------------------------------------ 拡大の範囲

def test_view_has_frame_aspect_and_contains_marks_with_margin():
    b = {"x": 0.30, "y": 0.40, "w": 0.10, "h": 0.10}
    v, why = compute_view([_box_ann(b)], SIZE, FRAME, margin=0)
    assert why is None and not v.is_full
    assert _px_aspect(v) == pytest.approx(FRAME, rel=1e-6)
    assert v.w == pytest.approx(MIN_WIDTH)  # 小さい mark でも拡大は最大 2.5 倍まで
    v2, _ = compute_view([_box_ann(b)], SIZE, FRAME)  # 既定の余白 0.08 では少し広く切り出す
    assert v2.w > MIN_WIDTH and _px_aspect(v2) == pytest.approx(FRAME, rel=1e-6)
    assert 0 <= v.x and v.x + v.w <= 1 + 1e-9 and 0 <= v.y and v.y + v.h <= 1 + 1e-9
    cx, cy = v.x + v.w / 2, v.y + v.h / 2
    assert cx == pytest.approx(0.35) and cy == pytest.approx(0.45)  # mark を中心に


def test_view_margin_and_larger_marks():
    b = {"x": 0.20, "y": 0.20, "w": 0.40, "h": 0.30}
    v, _ = compute_view([_box_ann(b)], SIZE, FRAME, margin=0.08)
    assert v.x <= 0.20 - 0.08 + 1e-9 and v.x + v.w >= 0.60 + 0.08 - 1e-9  # 余白（画像幅の 8%）を含む
    assert _px_aspect(v) == pytest.approx(FRAME, rel=1e-6)


def test_view_near_edge_is_shifted_inside_image():
    b = {"x": 0.0, "y": 0.0, "w": 0.08, "h": 0.1}
    v, _ = compute_view([_box_ann(b)], SIZE, FRAME)
    assert v.x == pytest.approx(0) and v.y == pytest.approx(0)
    assert v.x <= b["x"] and v.y <= b["y"]


def test_view_falls_back_to_full_when_marks_are_spread():
    a = _box_ann({"x": 0.05, "y": 0.02, "w": 0.1, "h": 0.1})
    b = _box_ann({"x": 0.5, "y": 0.85, "w": 0.1, "h": 0.12}, 1)
    v, why = compute_view([a, b], SIZE, FRAME, allow_narrow=False)
    assert v is FULL and "外れる" in why
    # 既定では、画像枠を細くして（注釈の範囲の縦横比で）切り出す
    v2, why2 = compute_view([a, b], SIZE, FRAME)
    assert why2 is None and v2.narrow and v2.x <= 0.05 and v2.x + v2.w >= 0.6 and v2.y <= 0.02 and v2.y + v2.h >= 0.97


def test_view_includes_arrow_start_and_target():
    a = Annotation("s04", "arrow_move", "arrow", 0, "m", "mark", start={"x": 0.57, "y": 0.25},
                   end={"x": 0.72, "y": 0.25}, target={"x": 0.72, "y": 0.10, "w": 0.24, "h": 0.30})
    v, why = compute_view([a], SIZE, FRAME)
    assert why is None and v.x <= 0.57 and v.x + v.w >= 0.96


@pytest.mark.parametrize("value,expect", [
    (True, (True, 0.08, None)), (False, (False, 0.08, None)), (None, (False, 0.08, None)),
    ({"margin": 0.12}, (True, 0.12, None)),
])
def test_parse_zoom(value, expect):
    assert parse_zoom(value) == expect


@pytest.mark.parametrize("value", ["yes", 1, {"margin": 2}])
def test_parse_zoom_errors(value):
    assert parse_zoom(value)[2] is not None


# ------------------------------------------------------------------ 拡大したスライド

def test_zoomed_slide_crops_picture_and_maps_marks(tmp_path):
    b = {"x": 0.70, "y": 0.10, "w": 0.24, "h": 0.30}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "m", "pad": 0, "zoom": True})], marks={"s01": {"m": b}})
    res = build_deck(sb, tmp_path / "o.pptx", overlay=tmp_path / "ov.png")
    v = res.views["s01"]
    slide = Presentation(str(res.output)).slides[1]
    pic = next(s for s in slide.shapes if s.shape_type == 13)
    assert (pic.crop_left, pic.crop_top) == pytest.approx((v.x, v.y), abs=1e-4)
    assert pic.crop_right == pytest.approx(1 - v.x - v.w, abs=1e-4)
    assert pic.crop_bottom == pytest.approx(1 - v.y - v.h, abs=1e-4)
    l, t, w, h = _fit(SIZE[0] * v.w, SIZE[1] * v.h, IMAGE_BOX)
    assert (pic.left, pic.top, pic.width, pic.height) == (l, t, w, h)
    assert v.record() == {k: round(getattr(v, k), 4) for k in "xywh"}
    assert w == pytest.approx(IMAGE_BOX[2], abs=2) or h == pytest.approx(IMAGE_BOX[3], abs=2)  # 枠いっぱい
    box = _shape(slide, "Highlight Box")
    mb = v.map_box(b)
    assert box.left == pytest.approx(l + w * mb["x"], abs=2) and box.top == pytest.approx(t + h * mb["y"], abs=2)
    assert box.width == pytest.approx(w * mb["w"], abs=2) and box.height == pytest.approx(h * mb["h"], abs=2)
    unzoomed_w = _fit(*SIZE, IMAGE_BOX)[2] * b["w"]
    assert box.width > unzoomed_w * 1.5  # 拡大しない場合より大きく見える
    # run.json 用の記録は元画像に対する座標のまま
    assert res.annotations[0].box == pytest.approx(b)
    # 一覧画像も拡大後の見た目: 枠の左の辺が赤い
    im = Image.open(tmp_path / "ov.png").convert("RGB")
    th = round(ov.TILE_W * (SIZE[1] * v.h) / (SIZE[0] * v.w))
    px = im.getpixel((ov.MARGIN + int(mb["x"] * ov.TILE_W) + 1, ov.MARGIN + ov.HEADER_H + int((mb["y"] + mb["h"] / 2) * th)))
    assert px[0] > 180 and px[1] < 90


def test_zoomed_arrow_is_mapped(tmp_path):
    target = {"x": 0.72, "y": 0.10, "w": 0.24, "h": 0.30}
    sb = _story(tmp_path, [("s01", "arrow_move", {"to": {"mark": "meter"}, "zoom": True})],
                marks={"s01": {"meter": target}})
    res = build_deck(sb, tmp_path / "o.pptx")
    v = res.views["s01"]
    slide = Presentation(str(res.output)).slides[1]
    pic = next(s for s in slide.shapes if s.shape_type == 13)
    a = res.annotations[0]
    end = v.map_point(a.end)
    assert a.slide_emu["end_x"] == pytest.approx(pic.left + pic.width * end["x"], abs=2)
    assert a.slide_emu["end_y"] == pytest.approx(pic.top + pic.height * end["y"], abs=2)


def test_zoom_skipped_for_unresolved_placeholder_and_other_recipes(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "missing", "zoom": True}),
                           ("s02", "fade_sequence", {"zoom": True})], marks={"s01": {}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.views == {}
    assert any("s01" in w and "未確定" in w and "拡大" in w for w in res.warnings)
    assert any("s02" in w and "zoom" in w for w in res.warnings)
    (tmp_path / "x").mkdir()
    sb2 = _story(tmp_path / "x", [("s01", "highlight_box", {"mark": "m", "zoom": True})], image=False)
    res2 = build_deck(sb2, tmp_path / "o2.pptx")
    assert res2.views == {}


def test_web_zoom_modes(tmp_path):
    from deck_helpers import WEB_MARK_BOXES, scene_mark_names, write_marks
    from explainer_reel_kit.deck.builder import load_storyboard

    doc = load_storyboard(SAMPLES["web"], None)
    assets = tmp_path / "assets"
    for s in doc["scenes"]:
        img = assets / s["image"]["ref"]
        img.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", SIZE, (230, 230, 230)).save(img)
        write_marks(img, s["id"], {n: WEB_MARK_BOXES[n] for n in scene_mark_names(s)})
    res = build_deck(SAMPLES["web"], tmp_path / "d.pptx", assets_root=assets)
    assert res.unresolved == []
    zoomed = set(res.views)
    assert zoomed <= {"s01", "s03", "s04"} and {"s01", "s04"} <= zoomed  # zoom: true（部品が小さいシーンは拡大される）
    assert set(res.split) == {"s02", "s05", "s06"}  # zoom: per_markは枠ごとのスライドに分ける
    assert all(len(p) == 2 for p in res.split.values())


# ------------------------------------------------------------------ 段落時刻

def _dj(tmp_path, item):
    p = tmp_path / "durations.json"
    p.write_text(json.dumps({"format": "explainer-reel/narration-durations", "version": 2, "pre_pause_sec": 0.3,
                             "post_pause_sec": 0.5, "items": [item]}), encoding="utf-8")
    return p


def _two_boxes(tmp_path):
    boxes = {"a": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "b": {"x": 0.6, "y": 0.5, "w": 0.3, "h": 0.3}}
    return _story(tmp_path, [("s01", "highlight_box", {"mark": ["a", "b"]})], marks={"s01": boxes})


def test_boxes_follow_paragraph_starts(tmp_path):
    sb = _two_boxes(tmp_path)
    res = build_deck(sb, tmp_path / "o.pptx",
                     durations=_dj(tmp_path, {"id": "s01", "slide_sec": 12.0, "paragraph_starts_sec": [0.0, 5.0]}))
    slide = Presentation(str(res.output)).slides[1]
    from deck_helpers import slide_roots
    t1 = _box_times(slide_roots(res.output)[1], _shape(slide, "Highlight Box").shape_id)
    assert t1["exit"][0] == pytest.approx(5300, abs=10)
    assert not any("段落" in w for w in res.warnings)


def test_paragraph_count_mismatch_warns(tmp_path):
    sb = _two_boxes(tmp_path)
    res = build_deck(sb, tmp_path / "o.pptx",
                     durations=_dj(tmp_path, {"id": "s01", "slide_sec": 12.0, "paragraph_starts_sec": [0.0]}))
    assert any("段落 1 個" in w and "均等" in w for w in res.warnings)


def test_chunk_starts_are_no_longer_read(tmp_path):
    sb = _two_boxes(tmp_path)
    res = build_deck(sb, tmp_path / "o.pptx",
                     durations=_dj(tmp_path, {"id": "s01", "slide_sec": 12.0, "chunk_starts_sec": [0.0, 5.0]}))
    assert any("paragraph_starts_sec" in w for w in res.warnings)


# ------------------------------------------------------------------ 出所ラベル

def test_label_shows_provenance_only_for_real_images(tmp_path):
    sb = _story(tmp_path, [("s01", "fade_sequence", None)])
    res = build_deck(sb, tmp_path / "o.pptx")
    texts = [s.text_frame.text for s in Presentation(str(res.output)).slides[1].shapes if s.has_text_frame]
    assert "実キャプチャ" in texts and PLACEHOLDER_LABEL not in texts
    (tmp_path / "p").mkdir()
    sb2 = _story(tmp_path / "p", [("s01", "fade_sequence", None)], image=False)
    res2 = build_deck(sb2, tmp_path / "o2.pptx")
    texts2 = [s.text_frame.text for s in Presentation(str(res2.output)).slides[1].shapes if s.has_text_frame]
    assert PLACEHOLDER_LABEL in texts2 and "実キャプチャ" not in texts2


# ------------------------------------------------------------------ イントロ・アウトロ

def test_intro_puts_first_scene_image_on_the_right(tmp_path):
    sb = _story(tmp_path, [("s01", "fade_sequence", None), ("s02", "fade_sequence", None)])
    res = build_deck(sb, tmp_path / "o.pptx")
    intro = Presentation(str(res.output)).slides[0]
    thumb = _shape(intro, "Intro Thumbnail")
    title = _shape(intro, "Title")
    assert thumb.left > title.left + title.width  # 文字は左、画像は右
    assert all(s.left + s.width <= thumb.left for s in intro.shapes if s.has_text_frame)
    assert thumb.width / thumb.height == pytest.approx(16 / 9, rel=0.01)
    # 画像は文字の後にフェードイン
    from deck_helpers import NS, slide_roots
    sld = slide_roots(res.output)[0]
    ids = [t.get("spid") for t in sld.findall(".//p:cTn[@presetClass='entr']//p:spTgt", NS)]
    assert ids[-1] == str(thumb.shape_id)


def test_intro_without_image_is_text_only(tmp_path):
    sb = _story(tmp_path, [("s01", "fade_sequence", None)], image=False)
    res = build_deck(sb, tmp_path / "o.pptx")
    intro = Presentation(str(res.output)).slides[0]
    assert not any(s.name == "Intro Thumbnail" for s in intro.shapes)
    assert _shape(intro, "Title").width > Inches(11)


def test_outro_checks_have_spacing_and_long_text_shrinks(tmp_path):
    sb = _story(tmp_path, [("s01", "fade_sequence", None)])
    doc = json.loads(sb.read_text(encoding="utf-8"))
    doc["outro"]["checks"] = [f"確認項目 {i}: 計算は簡易式による試算で、実測値ではありません。製品資料で開口率と寸法を確かめてください" for i in range(8)]
    doc["outro"]["next"] = "次の行動"
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    res = build_deck(sb, tmp_path / "o.pptx")
    checks = _shape(Presentation(str(res.output)).slides[-1], "Checks")
    paras = checks.text_frame.paragraphs
    assert paras[1].line_spacing == pytest.approx(1.25) and paras[1].space_after is not None
    sizes = [r.font.size.pt for p in paras for r in p.runs]
    assert max(sizes) < 16  # 縮小された
    est = estimate_height_pt([(p.runs[0].text, p.runs[0].font.size.pt) for p in paras], checks.width, 1.25,
                             paras[0].space_after.pt)
    assert est <= (checks.height - 91440) / 12700


def test_short_outro_keeps_size(tmp_path):
    res = build_deck(SAMPLES["web"], tmp_path / "d.pptx")
    checks = _shape(Presentation(str(res.output)).slides[-1], "Checks")
    assert checks.text_frame.paragraphs[0].runs[0].font.size.pt == 16


# ------------------------------------------------------------------ 文字の見積もり

def test_text_units_and_fit_scale():
    assert text_units("あいう") == 3 and text_units("abc") == pytest.approx(1.65)
    w, h = Inches(4), Inches(1)
    assert fit_scale([("短い文", 20)], w, h) == 1.0
    long = [("とても長い文章が続きます。" * 10, 20)]
    s = fit_scale(long, w, h)
    assert s < 1.0 and s >= 0.5
    assert fit_scale([("x" * 1000, 12)], Emu(w), Emu(h)) >= 0.5  # 最小（10pt / 0.5 倍）で止まる


# ------------------------------------------------------------------ 縦長の部品の拡大

TALL = {"x": 0.32, "y": 0.10, "w": 0.34, "h": 0.80}  # 立面図のような縦長の部品


def test_tall_mark_uses_narrow_frame():
    v, why = compute_view([_box_ann(TALL)], SIZE, FRAME)
    assert why is None and v.narrow
    assert v.x <= TALL["x"] and v.x + v.w >= TALL["x"] + TALL["w"] and v.y <= TALL["y"] and v.y + v.h >= TALL["y"] + TALL["h"]
    assert _px_aspect(v) < FRAME  # 画像枠より細い
    assert 0 <= v.x and v.x + v.w <= 1 and 0 <= v.y and v.y + v.h <= 1
    assert v.record()["narrow"] is True


def test_narrow_zoom_never_exceeds_2_5x():
    thin = {"x": 0.50, "y": 0.10, "w": 0.01, "h": 0.80}
    v, _ = compute_view([_box_ann(thin)], SIZE, FRAME, margin=0)
    from explainer_reel_kit.deck.overlay import zoom_factor
    assert v.narrow and zoom_factor(v, FRAME) <= 2.5 + 1e-6


def test_tall_mark_slide_is_narrow_and_centered(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "el", "zoom": True, "pad": 0})], marks={"s01": {"el": TALL}})
    res = build_deck(sb, tmp_path / "o.pptx", overlay=tmp_path / "ov.png")
    v = res.views["s01"]
    assert v.narrow and not any("拡大しません" in w for w in res.warnings)
    slide = Presentation(str(res.output)).slides[1]
    pic = next(s for s in slide.shapes if s.shape_type == 13)
    # 画像枠の高さいっぱい、幅は細く、左右の余白は同じ（中央）
    assert pic.height == pytest.approx(IMAGE_BOX[3], abs=2) and pic.width < IMAGE_BOX[2] * 0.9
    left_gap = pic.left - IMAGE_BOX[0]
    right_gap = IMAGE_BOX[0] + IMAGE_BOX[2] - (pic.left + pic.width)
    assert left_gap == pytest.approx(right_gap, abs=2) and left_gap > 0
    # 拡大していないときより大きい（全体表示は高さ 5.1in に 16:9）
    full_h = _fit(*SIZE, IMAGE_BOX)[3]
    assert pic.height / v.h > full_h * 1.05
    # 見出し・画面テキストの位置は変わらない
    from explainer_reel_kit.deck.builder import HEAD_BOX
    head = _shape(slide, "Heading")
    assert (head.left, head.top, head.width) == (HEAD_BOX[0], HEAD_BOX[1], HEAD_BOX[2])
    box = _shape(slide, "Highlight Box")
    mb = v.map_box(TALL)
    assert box.left == pytest.approx(pic.left + pic.width * mb["x"], abs=2)
    assert box.top == pytest.approx(pic.top + pic.height * mb["y"], abs=2)
    # 一覧画像: 左右は余白（白）、枠の辺は赤
    from explainer_reel_kit.deck import overlay as ovm
    im = Image.open(tmp_path / "ov.png").convert("RGB")
    fh = round(ovm.TILE_W / ovm.FRAME_ASPECT)
    tw = round(fh * (SIZE[0] * v.w) / (SIZE[1] * v.h))
    ox = (ovm.TILE_W - tw) // 2
    y0 = ovm.MARGIN + ovm.HEADER_H
    assert im.getpixel((ovm.MARGIN + 3, y0 + fh // 2)) == (255, 255, 255)
    px = im.getpixel((ovm.MARGIN + ox + int(mb["x"] * tw) + 1, y0 + int((mb["y"] + mb["h"] / 2) * fh)))
    assert px[0] > 180 and px[1] < 90


def test_per_mark_mixes_narrow_and_wide_parts(tmp_path):
    from test_deck_morph_pan import _split_story

    sb = _split_story(tmp_path, boxes={"a": TALL, "b": {"x": 0.70, "y": 0.80, "w": 0.22, "h": 0.12}})
    res = build_deck(sb, tmp_path / "o.pptx")
    parts = res.split["s02"]
    assert parts[0]["view"].get("narrow") is True and "narrow" not in parts[1]["view"]
    assert not any("拡大しません" in w for w in res.warnings)
    prs = Presentation(str(res.output))
    p1 = next(s for s in prs.slides[2].shapes if s.name == "!!Shot")
    p2 = next(s for s in prs.slides[3].shapes if s.name == "!!Shot")
    assert p1.width < p2.width  # 細い画像枠 → 画像枠いっぱいへ、同じ名前のまま変形でつながる


# 通常の切り出しで収まっても、拡大率が小さければ大きく見える方（細い枠）を選ぶ
@pytest.mark.parametrize("h", [0.60, 0.65])
def test_tall_main_view_prefers_narrow_frame(h):
    """画面の中央の大きな図（画像の高さの 60〜70%）に近い大きさ。通常の切り出しでも収まるが拡大率が小さい。"""
    from explainer_reel_kit.deck.zoom import NARROW_PREFER_BELOW, magnification
    el = {"x": 0.32, "y": 0.15, "w": 0.34, "h": h}
    normal, why = compute_view([_box_ann(el)], SIZE, FRAME, allow_narrow=False)
    assert why is None and not normal.narrow
    m_normal = magnification(normal, SIZE, FRAME)
    assert m_normal < NARROW_PREFER_BELOW
    v, why = compute_view([_box_ann(el)], SIZE, FRAME)
    assert why is None and v.narrow
    assert magnification(v, SIZE, FRAME) > m_normal
    assert v.x <= el["x"] and v.x + v.w >= el["x"] + el["w"] and v.y <= el["y"] and v.y + v.h >= el["y"] + el["h"]


@pytest.mark.parametrize("box", [
    {"x": 0.40, "y": 0.40, "w": 0.10, "h": 0.08},   # 小さなボタン
    {"x": 0.05, "y": 0.30, "w": 0.30, "h": 0.25},   # 中くらいの入力欄
])
def test_well_zoomed_mark_keeps_normal_crop(box):
    from explainer_reel_kit.deck.zoom import NARROW_PREFER_BELOW, magnification
    v, why = compute_view([_box_ann(box)], SIZE, FRAME)
    assert why is None and not v.narrow
    assert magnification(v, SIZE, FRAME) >= NARROW_PREFER_BELOW


def test_magnification_of_full_and_full_width_crop():
    from explainer_reel_kit.deck.zoom import magnification
    assert magnification(FULL, SIZE, FRAME) == pytest.approx(1.0)
    # 16:9 の画像を幅いっぱい・画像枠の縦横比で切り出すと 約 1.36 倍
    v = View(0, 0, 1, (SIZE[0] / FRAME) / SIZE[1])
    assert magnification(v, SIZE, FRAME) == pytest.approx(1.36, abs=0.01)
