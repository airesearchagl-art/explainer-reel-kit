"""細い画像枠（narrow）の一覧画像の赤枠が、スライド上の赤枠を一覧画像の縮尺に換算した位置と一致する。"""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw
from pptx import Presentation

from deck_helpers import *  # noqa: F401,F403  (sys.path の設定)
from explainer_reel_kit.deck import overlay as ovm
from explainer_reel_kit.deck.builder import IMAGE_BOX, build_deck
from explainer_reel_kit.deck.marks import Annotation
from explainer_reel_kit.deck.zoom import View, fit_rect
from test_deck_marks import _story

W, H = 1920, 1080
# 縦に長い配置の例: 斜め上へ伸びるパスに沿った 7 個（画面上では縦に長い列）→ 最後の 1 個
PTS = [(760 + i * 60, 900 - i * 120) for i in range(7)]
_x0, _y0 = min(p[0] for p in PTS) - 10, min(p[1] for p in PTS) - 10
_x1, _y1 = max(p[0] for p in PTS) + 110, max(p[1] for p in PTS) + 110
SU_BOXES = {"placed_array": {"x": _x0 / W, "y": _y0 / H, "w": (_x1 - _x0) / W, "h": (_y1 - _y0) / H},
            "placed_last": {"x": (PTS[-1][0] - 10) / W, "y": (PTS[-1][1] - 10) / H, "w": 120 / W, "h": 120 / H}}
FH = round(ovm.TILE_W / ovm.FRAME_ASPECT)
TOP = ovm.MARGIN + ovm.HEADER_H  # 1 行目のタイルの画像の上端（一覧画像の座標）


def _red(px) -> bool:
    return px[0] > 180 and px[1] < 90 and px[2] < 90


def _slide_box_in_tile(shape) -> tuple[float, float, float, float]:
    """スライド上の図形（EMU）→ 一覧画像のタイルの座標（画像枠 IMAGE_BOX をタイルの幅 TILE_W × 高さ FH に換算）。"""
    sx, sy = ovm.TILE_W / IMAGE_BOX[2], FH / IMAGE_BOX[3]
    x0, y0 = (shape.left - IMAGE_BOX[0]) * sx, (shape.top - IMAGE_BOX[1]) * sy
    return x0, y0, x0 + shape.width * sx, y0 + shape.height * sy


def _assert_box_at(im, tile_left: int, box: tuple[float, float, float, float]) -> None:
    """一覧画像の赤枠（太さ 4px、内側に描く）が box の位置にある: 4 辺の中点が赤、その 3px 外側は赤でない。"""
    x0, y0, x1, y1 = box
    mx, my = int((x0 + x1) / 2), int((y0 + y1) / 2)
    gx, gy = tile_left, TOP
    for x, y, ox, oy in [(x0 + 1, my, x0 - 3, my), (x1 - 2, my, x1 + 3, my),
                         (mx + 8, y0 + 1, mx + 8, y0 - 3), (mx, y1 - 2, mx, y1 + 3)]:
        assert _red(im.getpixel((gx + int(x), gy + int(y)))), (x, y)
        assert not _red(im.getpixel((gx + int(ox), gy + int(oy)))), (ox, oy)


def _su_story(tmp_path):
    sb = _story(tmp_path, [("s04", "highlight_box",
                            {"mark": ["placed_array", "placed_last"], "zoom": "per_mark", "pad": 0})],
                marks={"s04": SU_BOXES})
    img = Image.new("RGB", (W, H), (236, 240, 244))
    d = ImageDraw.Draw(img)
    for x, y in PTS:
        d.rectangle([x, y, x + 100, y + 100], fill=(120, 150, 200), outline=(30, 50, 90), width=3)
    img.save(tmp_path / "captures/t/s04.png")
    return sb


def test_su_like_narrow_overlay_box_matches_slide(tmp_path):
    res = build_deck(_su_story(tmp_path), tmp_path / "o.pptx", overlay=tmp_path / "ov.png")
    parts = res.split["s04"]
    assert parts[0]["view"].get("narrow") is True  # 縦に長い列は細い画像枠
    prs = Presentation(str(res.output))
    s1 = prs.slides[1]
    box = next(s for s in s1.shapes if s.name == "!!Box")
    pic = next(s for s in s1.shapes if s.name == "!!Shot")
    im = Image.open(tmp_path / "ov.png").convert("RGB")
    # タイルの幅は TILE_W のまま（画像の幅に切り詰めない）。2 枚目のタイルは同じ行の右
    assert im.width == ovm.COLS * ovm.TILE_W + (ovm.COLS + 1) * ovm.MARGIN
    _assert_box_at(im, ovm.MARGIN, _slide_box_in_tile(box))
    # 画像の置き場所もスライドと同じ（左右の余白は白、画像の左端の内側は撮影画像の色）
    px0, _, px1, _ = _slide_box_in_tile(pic)
    assert im.getpixel((ovm.MARGIN + int(px0) - 3, TOP + FH // 2)) == (255, 255, 255)
    assert im.getpixel((ovm.MARGIN + int(px1) + 3, TOP + FH // 2)) == (255, 255, 255)
    assert im.getpixel((ovm.MARGIN + int(px0) + 3, TOP + 3))[:2] == (236, 240)
    # 2 枚目（通常の切り出し）も同じ換算で一致する
    s2 = prs.slides[2]
    box2 = next(s for s in s2.shapes if s.name == "!!Box")
    _assert_box_at(im, 2 * ovm.MARGIN + ovm.TILE_W, _slide_box_in_tile(box2))


@pytest.mark.parametrize("view", [
    View(0.30, 0.10, 0.40, 0.85, narrow=True),   # 画像枠より細い（左右に余白）
    View(0.05, 0.40, 0.90, 0.15, narrow=True),   # 画像枠より横に長い（上下に余白）
])
def test_overlay_uses_same_fit_as_slide(tmp_path, view):
    img = tmp_path / "a.png"
    Image.new("RGB", (W, H), (236, 240, 244)).save(img)
    b = {"x": view.x + view.w * 0.25, "y": view.y + view.h * 0.25, "w": view.w * 0.5, "h": view.h * 0.5}
    a = Annotation(scene="s01", recipe="highlight_box", kind="box", index=0, mark="m", status="ok", box=b)
    scene = {"id": "s01", "recipe": "highlight_box", "image": {"ref": "a.png"}}
    tile = ovm._tile(scene, img, [a], view)
    assert tile.size == (ovm.TILE_W, FH + ovm.HEADER_H)
    # スライドの画像枠で同じ計算（zoom.fit_rect、builder._fit と同じ置き方）をして、タイルの縮尺に換算
    l, t, w, h = fit_rect(view, (W, H), IMAGE_BOX[2], IMAGE_BOX[3])
    sx, sy = ovm.TILE_W / IMAGE_BOX[2], FH / IMAGE_BOX[3]
    mb = view.map_box(b)
    exp = ((l + mb["x"] * w) * sx, (t + mb["y"] * h) * sy,
           (l + (mb["x"] + mb["w"]) * w) * sx, (t + (mb["y"] + mb["h"]) * h) * sy)
    sheet = Image.new("RGB", (ovm.TILE_W + 2 * ovm.MARGIN, FH + ovm.HEADER_H + 2 * ovm.MARGIN), (255, 255, 255))
    sheet.paste(tile, (ovm.MARGIN, ovm.MARGIN))
    _assert_box_at(sheet, ovm.MARGIN, exp)


def test_fit_rect_matches_builder_fit():
    from explainer_reel_kit.deck.builder import _fit
    for v in (View(0.30, 0.10, 0.40, 0.85, narrow=True), View(0.05, 0.40, 0.90, 0.15, narrow=True), View()):
        l, t, w, h = fit_rect(v, (W, H), IMAGE_BOX[2], IMAGE_BOX[3])
        bl, bt, bw, bh = _fit(W * v.w, H * v.h, IMAGE_BOX)
        assert (IMAGE_BOX[0] + l, IMAGE_BOX[1] + t, w, h) == pytest.approx((bl, bt, bw, bh), abs=2)
