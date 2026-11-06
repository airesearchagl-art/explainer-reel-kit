"""注釈位置の確認画像: 画像に marks.json の枠を描き込み、1 枚に並べる。

撮影の結果（capture-web-result.json）でも説明図の結果（diagram-result.json）でも使える。
枠は ``box``（相対座標）から描くので、スライドの段が使う値そのものを確かめられる。
確認画像は撮影素材と同じく commit しない。
"""
from __future__ import annotations

import json
from pathlib import Path

COLORS = [(255, 59, 48), (0, 200, 255), (255, 204, 0), (52, 199, 89), (191, 90, 242)]
FONT_CANDIDATES = (
    "NotoSansCJK-Regular.ttc", "NotoSansCJKjp-Regular.otf", "meiryo.ttc", "msgothic.ttc", "YuGothM.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Windows は名前だけで Fonts から探される
)


def _font(size: int):
    from PIL import ImageFont

    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_marks(image_path: Path, marks_doc: dict, width: int):
    from PIL import Image, ImageDraw

    im = Image.open(image_path).convert("RGB")
    scale = width / im.width
    im = im.resize((width, max(1, round(im.height * scale))))
    dr = ImageDraw.Draw(im)
    font = _font(max(14, width // 50))
    size = getattr(font, "size", 14)
    for i, (name, m) in enumerate((marks_doc.get("marks") or {}).items()):
        c = COLORS[i % len(COLORS)]
        b = m["box"]
        x0, y0 = b["x"] * im.width, b["y"] * im.height
        x1, y1 = x0 + b["w"] * im.width, y0 + b["h"] * im.height
        dr.rectangle([x0, y0, x1, y1], outline=c, width=3)
        label = f"{i + 1} {name}"
        tw = dr.textlength(label, font=font)
        ty = y0 - size - 6 if y0 > size + 6 else y0 + 2
        dr.rectangle([x0, ty, x0 + tw + 8, ty + size + 4], fill=c)
        dr.text((x0 + 4, ty + 1), label, fill=(0, 0, 0), font=font)
    head = f"{marks_doc.get('scene', '?')}  {Path(image_path).name}"
    dr.rectangle([0, 0, dr.textlength(head, font=font) + 12, size + 8], fill=(0, 0, 0))
    dr.text((6, 3), head, fill=(255, 255, 255), font=font)
    return im


def build_overlay(result_json: Path, out: Path, cols: int = 2, width: int = 960) -> list[str]:
    """結果 JSON の順に、marks.json のある画像を並べた確認画像を書く。戻り値は並べたシーン id。"""
    from PIL import Image

    res = json.loads(Path(result_json).read_text(encoding="utf-8"))
    tiles, used = [], []
    for sc in res.get("scenes", []):
        mp = sc.get("marks_path")
        if sc.get("status") != "ok" or not mp or not Path(mp).is_file() or not sc.get("path"):
            continue
        tiles.append(draw_marks(Path(sc["path"]), json.loads(Path(mp).read_text(encoding="utf-8")), width))
        used.append(sc["id"])
    if not tiles:
        raise ValueError(f"marks.json のある結果がありません: {result_json}")
    th = max(t.height for t in tiles)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width, rows * th), (30, 30, 30))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * width, (i // cols) * th))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return used
