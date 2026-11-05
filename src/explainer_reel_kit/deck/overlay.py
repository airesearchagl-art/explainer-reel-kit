"""確認用の一覧画像: 各シーンの撮影画像に、実際に置いた赤枠・矢印を描いて 1 枚に並べる。

座標は marks.py の結果（撮影画像に対する相対座標）をそのまま使う。スライドはこの相対座標を
画像の矩形へ写して置くので、一覧画像とスライドの位置は同じ計算に基づく。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont

from .marks import Annotation
from .zoom import FULL, View, fit_rect, magnification

TILE_W = 640
COLS = 2
HEADER_H = 26
MARGIN = 12
RED = (217, 45, 32)
ORANGE = (240, 140, 0)  # 未確定（既定位置）
BG = (250, 250, 250)
INK = (34, 34, 34)
PLACEHOLDER = (225, 225, 225)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


FRAME_ASPECT = 12.333 / 5.1  # スライドの画像枠（builder.IMAGE_BOX）の縦横比


def zoom_factor(view: View, frame_aspect: float = FRAME_ASPECT, image_aspect: float = 16 / 9) -> float:
    """画像枠に全体を収めたときに比べた表示の大きさ。"""
    full = min(frame_aspect / image_aspect, 1.0)  # 画像枠の高さ 1 に対する、全体表示の高さ
    vw, vh = view.w * image_aspect, view.h
    shown = min(frame_aspect / vw, 1 / vh) * vh
    return shown / full / view.h


def _tile(scene: dict[str, Any], image_path: Path | None, annotations: Sequence[Annotation],
          view: View = FULL, frame_aspect: float = FRAME_ASPECT) -> Image.Image:
    # 注釈を描く範囲（画像が置かれた矩形、body の座標）
    ox = oy = 0.0
    size: tuple[int, int] | None = None
    if image_path is not None and Path(image_path).is_file():
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            iw, ih = size = im.size
            if not view.is_full:  # スライドと同じ範囲を切り出す（拡大）
                im = im.crop((round(view.x * iw), round(view.y * ih),
                              round((view.x + view.w) * iw), round((view.y + view.h) * ih)))
            if view.narrow:
                # 細くした画像枠: スライドと同じ計算（zoom.fit_rect）で、画像枠の縦横比のタイルの
                # 中に置く。左右（横に長い範囲では上下）は背景。注釈も同じ矩形に写す
                fh = round(TILE_W / frame_aspect)
                ox, oy, w, h = fit_rect(view, (iw, ih), TILE_W, fh)
                body = Image.new("RGB", (TILE_W, fh), (255, 255, 255))
                body.paste(im.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS), (round(ox), round(oy)))
            else:
                th = max(1, round(TILE_W * im.height / im.width))
                body = im.resize((TILE_W, th), Image.LANCZOS)
                w, h = body.size
    else:
        th = round(TILE_W * 9 / 16)
        body = Image.new("RGB", (TILE_W, th), PLACEHOLDER)
        card = (scene.get("recipe_params") or {}).get("card")
        what = f"text card: {card.get('title', '')}" if isinstance(card, dict) else f"no image: {scene['image']['ref']}"
        ImageDraw.Draw(body).text((12, th // 2 - 8), what, fill=INK, font=_font(14))
        w, h = body.size
    d = ImageDraw.Draw(body)
    font = _font(18)
    for a in annotations:
        color = RED if a.status != "default" else ORANGE
        if a.kind == "box":
            b = view.map_box(a.box)
            x0, y0 = ox + b["x"] * w, oy + b["y"] * h
            x1, y1 = ox + (b["x"] + b["w"]) * w, oy + (b["y"] + b["h"]) * h
            d.rectangle([x0, y0, x1, y1], outline=color, width=4)
            tag = str(a.index + 1)
            ty = y0 - 24 if y0 >= 24 else y0  # 番号は枠の左上の外側（入らなければ内側）に置き、部品の文字を隠さない
            d.rectangle([x0, ty, x0 + 22, ty + 24], fill=color)
            d.text((x0 + 6, ty + 2), tag, fill=(255, 255, 255), font=font)
        else:
            if a.target is not None:
                t = view.map_box(a.target)
                d.rectangle([ox + t["x"] * w, oy + t["y"] * h, ox + (t["x"] + t["w"]) * w, oy + (t["y"] + t["h"]) * h],
                            outline=color, width=1)
            st, en = view.map_point(a.start), view.map_point(a.end)
            sx, sy, ex, ey = ox + st["x"] * w, oy + st["y"] * h, ox + en["x"] * w, oy + en["y"] * h
            d.line([sx, sy, ex, ey], fill=color, width=5)
            ang = math.atan2(ey - sy, ex - sx)
            head = [(ex, ey),
                    (ex - 18 * math.cos(ang - 0.45), ey - 18 * math.sin(ang - 0.45)),
                    (ex - 18 * math.cos(ang + 0.45), ey - 18 * math.sin(ang + 0.45))]
            d.polygon(head, fill=color)
            d.ellipse([sx - 5, sy - 5, sx + 5, sy + 5], outline=color, width=2)
    tile = Image.new("RGB", (body.width, body.height + HEADER_H), BG)
    tile.paste(body, (0, HEADER_H))
    names = [a.mark or a.status for a in annotations]
    unresolved = any(a.status == "default" for a in annotations)
    header = f"{scene['id']}  {scene['recipe']}  " + (" -> ".join(f"{i + 1}:{n}" for i, n in enumerate(names)) if names else "")
    if not view.is_full:
        zf = magnification(view, size, frame_aspect) if size else zoom_factor(view, frame_aspect)
        header += f"  [zoom {zf:.1f}x{' narrow' if view.narrow else ''}]"
    if unresolved:
        header += "  [UNRESOLVED: default position]"
    ImageDraw.Draw(tile).text((6, 4), header, fill=ORANGE if unresolved else INK, font=_font(15))
    return tile


def render_overlay(entries: Sequence[tuple], out: Path) -> Path:
    """entries: (scene, 撮影画像のパス or None, 置いた注釈[, 表示範囲 View])。シーンの順に COLS 列で並べる。"""
    tiles = [_tile(*e) for e in entries]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not tiles:
        Image.new("RGB", (TILE_W, 40), BG).save(out)
        return out
    rows = math.ceil(len(tiles) / COLS)
    row_h = [max(t.height for t in tiles[r * COLS:(r + 1) * COLS]) for r in range(rows)]
    W = COLS * TILE_W + (COLS + 1) * MARGIN
    H = sum(row_h) + (rows + 1) * MARGIN
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    y = MARGIN
    for r in range(rows):
        for c, t in enumerate(tiles[r * COLS:(r + 1) * COLS]):
            sheet.paste(t, (MARGIN + c * (TILE_W + MARGIN), y))
        y += row_h[r] + MARGIN
    sheet.save(out)
    return out
