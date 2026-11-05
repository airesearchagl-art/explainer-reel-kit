"""注釈位置（marks）の形式 ``explainer-reel/marks@1`` — 撮影と説明図の段が共通で使う。

- 画像の隣に ``<画像名>.marks.json`` を置く（例 ``s01_page.png`` → ``s01_page.marks.json``）
- ``box`` は画像に対する 0〜1 の相対座標、``px`` は画像のピクセル。両方書く
- 見つからない・非表示・幅か高さが 8px 未満・面積の 95% 未満しか画像内にない mark は記録せず、
  そのシーンを失敗にする（既定の位置で出さない）

仕様は ``docs/design/marks.md``。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

FORMAT = "explainer-reel/marks@1"
MARK_NAME = re.compile(r"^[a-z0-9_]+$")
MIN_PX = 8            # 幅か高さがこれ未満なら失敗
MIN_INSIDE = 0.95     # 面積のこの割合以上が画像内にないと失敗
MARK_RECIPES = ("highlight_box", "arrow_move")
SOURCES = ("web", "generated")


class MarksError(ValueError):
    """marks.json が形式に合わない。"""


def marks_path(image_path: Path) -> Path:
    """``s01_page.png`` → ``s01_page.marks.json``（画像の隣）。"""
    image_path = Path(image_path)
    return image_path.with_name(image_path.stem + ".marks.json")


def storyboard_mark_refs(scene: dict[str, Any]) -> list[str]:
    """台本の ``recipe_params`` が参照している mark 名（``mark`` / ``to.mark`` / ``from.mark``）。"""
    out: list[str] = []

    def add(v: Any) -> None:
        for x in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
            if isinstance(x, str) and x not in out:
                out.append(x)

    params = scene.get("recipe_params") or {}
    if isinstance(params, dict):
        add(params.get("mark"))
        for k in ("to", "from"):
            if isinstance(params.get(k), dict):
                add(params[k].get("mark"))
    return out


def to_image(measured: dict[str, Any], origin: tuple[float, float], scale: float,
             img_w: int, img_h: int) -> tuple[dict[str, Any], list[str]]:
    """測った枠を画像の座標に直して検証する。

    measured: ``{名前: {"css": (x, y, w, h), "how": "…"}}``（ビューポート座標、CSS px）か ``{名前: {"error": "…"}}``。
    origin は画像の左上に当たるビューポート座標、scale は device_scale_factor。
    戻り値は (記録する marks, 失敗の理由)。
    """
    ok: dict[str, Any] = {}
    errors: list[str] = []
    for name, m in measured.items():
        if "error" in m:
            errors.append(f"mark {name}: {m['error']}")
            continue
        x, y, w, h = m["css"]
        px_x, px_y = (x - origin[0]) * scale, (y - origin[1]) * scale
        px_w, px_h = w * scale, h * scale
        if px_w < MIN_PX or px_h < MIN_PX:
            errors.append(f"mark {name}: 小さすぎます（{px_w:.0f}×{px_h:.0f}px、{MIN_PX}px 未満）")
            continue
        ix0, iy0 = max(0.0, px_x), max(0.0, px_y)
        ix1, iy1 = min(float(img_w), px_x + px_w), min(float(img_h), px_y + px_h)
        inside = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0) / (px_w * px_h)
        if inside < MIN_INSIDE:
            errors.append(f"mark {name}: 画像からはみ出しています（画像内 {inside:.0%}）")
            continue
        # わずかなはみ出し（5% 以内）は画像の範囲に切り詰めて記録する
        ok[name] = {
            "box": {"x": round(ix0 / img_w, 4), "y": round(iy0 / img_h, 4),
                    "w": round((ix1 - ix0) / img_w, 4), "h": round((iy1 - iy0) / img_h, 4)},
            "px": {"x": round(ix0), "y": round(iy0), "w": round(ix1 - ix0), "h": round(iy1 - iy0)},
            "how": m["how"],
        }
    return ok, errors


def build_doc(scene_id: str, source: str, image: Path, size: tuple[int, int], marks: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "scene": scene_id,
        "source": source,
        "image": Path(image).name,
        "image_size": {"w": size[0], "h": size[1]},
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "marks": marks,
    }


def write(path: Path, doc: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_doc(doc: Any) -> list[str]:
    """marks.json の形式の検査（スライドの段が読む前提）。"""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["最上位はオブジェクトにしてください"]
    if doc.get("format") != FORMAT:
        errs.append(f"format は {FORMAT} です")
    if doc.get("source") not in SOURCES:
        errs.append(f"source は {' / '.join(SOURCES)} のどれかです")
    for k in ("scene", "image"):
        if not isinstance(doc.get(k), str) or not doc[k]:
            errs.append(f"{k} がありません")
    size = doc.get("image_size")
    if not (isinstance(size, dict) and all(isinstance(size.get(k), int) and size[k] > 0 for k in ("w", "h"))):
        errs.append("image_size は {w, h}（正の整数）です")
        size = None
    marks = doc.get("marks")
    if not isinstance(marks, dict):
        return errs + ["marks がありません"]
    for name, m in marks.items():
        where = f"marks.{name}"
        if not MARK_NAME.match(str(name)):
            errs.append(f"{where}: mark 名は英小文字・数字・_ です")
        if not isinstance(m, dict):
            errs.append(f"{where}: オブジェクトにしてください")
            continue
        box, px = m.get("box"), m.get("px")
        if not (isinstance(box, dict) and all(isinstance(box.get(k), (int, float)) for k in "xywh")):
            errs.append(f"{where}: box は {{x, y, w, h}} です")
        else:
            if not (0 <= box["x"] and 0 <= box["y"] and box["w"] > 0 and box["h"] > 0
                    and box["x"] + box["w"] <= 1.0001 and box["y"] + box["h"] <= 1.0001):
                errs.append(f"{where}: box は画像の中（0〜1）に収めてください")
        if not (isinstance(px, dict) and all(isinstance(px.get(k), int) for k in "xywh")):
            errs.append(f"{where}: px は {{x, y, w, h}}（整数）です")
        elif size and (px["x"] + px["w"] > size["w"] or px["y"] + px["h"] > size["h"]):
            errs.append(f"{where}: px が画像からはみ出しています")
    return errs


def load(path: Path) -> dict[str, Any]:
    """marks.json を読み、形式を確かめて返す。"""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise MarksError(f"marks.json を読めません: {path}（{e}）") from e
    errs = validate_doc(doc)
    if errs:
        raise MarksError(f"{path}: " + " / ".join(errs))
    return doc


def resolve_refs(scene: dict[str, Any], doc: dict[str, Any]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """台本のシーンが参照する mark 名を、marks.json の box に引く。戻り値は (名前 → box, 見つからない名前)。"""
    found, missing = {}, []
    for name in storyboard_mark_refs(scene):
        m = (doc.get("marks") or {}).get(name)
        if m is None:
            missing.append(name)
        else:
            found[name] = dict(m["box"])
    return found, missing
