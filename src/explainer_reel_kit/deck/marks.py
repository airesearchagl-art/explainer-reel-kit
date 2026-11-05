"""撮影時に測った注釈位置（marks）を、赤枠・矢印の位置に変換する。

位置はすべて「撮影画像に対する 0〜1 の相対座標」で決め、スライド（builder.py）と
確認用の一覧画像（overlay.py）はこの結果を共有する。画像は枠に縦横比を保って収めるので、
スライド上の位置 = 画像の矩形の左上 + 相対座標 × 画像の矩形の幅・高さ。

位置が決まらない注釈（未確定の注釈）は Unresolved として返し、既定位置（recipes.DEFAULT_*）で代わりに置く。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

MARKS_FORMAT = "explainer-reel/marks@1"
DEFAULT_PAD = 0.01  # 画像幅に対する比
ARROW_DISTANCE = 0.15  # from_side のとき、mark の辺から離す距離（画像幅に対する比）
SIDES = ("left", "right", "top", "bottom")
MARK_NAME = re.compile(r"^[a-z0-9_]+$")

from .recipes import DEFAULT_BOX, DEFAULT_FROM, DEFAULT_TO  # noqa: E402  既定位置（未確定のときだけ使う）


@dataclass
class Unresolved:
    scene: str
    mark: str | None
    reason: str

    def record(self) -> dict[str, Any]:
        return {"scene": self.scene, "mark": self.mark, "reason": self.reason}

    def text(self) -> str:
        return f"{self.scene}{'（' + self.mark + '）' if self.mark else ''}: {self.reason}"


@dataclass
class Annotation:
    """スライドに置く注釈 1 つ。座標は撮影画像に対する相対値。"""

    scene: str
    recipe: str
    kind: str  # box / arrow
    index: int  # 同じシーン内の順番（0 から）
    mark: str | None
    status: str  # mark（marks.json の位置）/ coords（台本の座標）/ default（未確定のため既定位置）
    box: dict[str, float] | None = None  # kind=box: 余白込みの枠
    start: dict[str, float] | None = None  # kind=arrow: 先端の出発点
    end: dict[str, float] | None = None  # kind=arrow: 先端の到着点（mark の枠の外側の辺）
    target: dict[str, float] | None = None  # kind=arrow: 指す枠（mark の位置）
    slide_emu: dict[str, int] | None = None  # builder が置いた位置（EMU）
    part: int | None = None  # zoom: per_mark で分けたスライドの番号（0 から。分けないときは None）

    def record(self) -> dict[str, Any]:
        out: dict[str, Any] = {"scene": self.scene, "recipe": self.recipe, "kind": self.kind, "index": self.index,
                               "mark": self.mark, "status": self.status}
        if self.part is not None:
            out["part"] = self.part
        for k in ("box", "start", "end", "target", "slide_emu"):
            v = getattr(self, k)
            if v is not None:
                out[k] = {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}
        return out


@dataclass
class SceneMarks:
    annotations: list[Annotation] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    marks_file: Path | None = None


# ---------------------------------------------------------------- marks.json

def marks_path(image_path: Path) -> Path:
    """s01_config.png → s01_config.marks.json（同じフォルダ）。"""
    image_path = Path(image_path)
    return image_path.with_name(image_path.stem + ".marks.json")


def _num01(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1


def _valid_box(b: Any) -> bool:
    return (isinstance(b, dict) and all(_num01(b.get(k)) for k in ("x", "y", "w", "h"))
            and b["w"] > 0 and b["h"] > 0 and b["x"] + b["w"] <= 1.0001 and b["y"] + b["h"] <= 1.0001)


def load_marks(path: Path) -> tuple[dict[str, dict[str, float]] | None, dict[str, Any] | None, str | None]:
    """戻り値 (mark 名 → box, 記録全体, 読めない理由)。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return None, None, f"記録ファイルを読めません（{e}）"
    if not isinstance(data, dict) or data.get("format") != MARKS_FORMAT:
        return None, None, f"記録ファイルの format が {MARKS_FORMAT} ではありません"
    marks = data.get("marks")
    if not isinstance(marks, dict):
        return None, None, "記録ファイルに marks がありません"
    out: dict[str, dict[str, float]] = {}
    for name, m in marks.items():
        if isinstance(m, dict) and _valid_box(m.get("box")):
            out[name] = {k: float(m["box"][k]) for k in ("x", "y", "w", "h")}
    return out, data, None


def image_aspect(image_path: Path | None, record: dict[str, Any] | None = None) -> float:
    """画像の 幅 / 高さ。画像 → 記録の image_size → 16:9 の順。"""
    if image_path is not None and Path(image_path).is_file():
        try:
            with Image.open(image_path) as im:
                return im.width / im.height
        except OSError:
            pass
    size = (record or {}).get("image_size") or {}
    if isinstance(size.get("w"), (int, float)) and isinstance(size.get("h"), (int, float)) and size["h"] > 0:
        return size["w"] / size["h"]
    return 16 / 9


# ---------------------------------------------------------------- geometry

def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def pad_box(b: dict[str, float], pad: float, aspect: float) -> dict[str, float]:
    """枠に余白を足す（pad は画像幅に対する比。縦方向は画像の縦横比で換算）。画像の内側に収める。"""
    px, py = pad, pad * aspect
    x0, y0 = _clamp01(b["x"] - px), _clamp01(b["y"] - py)
    x1, y1 = _clamp01(b["x"] + b["w"] + px), _clamp01(b["y"] + b["h"] + py)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def side_start(b: dict[str, float], side: str, aspect: float, distance: float = ARROW_DISTANCE) -> dict[str, float]:
    cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    dy = distance * aspect
    p = {"left": (b["x"] - distance, cy), "right": (b["x"] + b["w"] + distance, cy),
         "top": (cx, b["y"] - dy), "bottom": (cx, b["y"] + b["h"] + dy)}[side]
    return {"x": _clamp01(p[0]), "y": _clamp01(p[1])}


def edge_point(start: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    """start から枠の中心へ向かう線が、枠の外側の辺に触れる点（start が枠の中なら中心）。"""
    cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    sx, sy = start["x"], start["y"]
    if b["x"] <= sx <= b["x"] + b["w"] and b["y"] <= sy <= b["y"] + b["h"]:
        return {"x": cx, "y": cy}
    dx, dy = cx - sx, cy - sy
    t_enter = 0.0
    for p, d, lo, hi in ((sx, dx, b["x"], b["x"] + b["w"]), (sy, dy, b["y"], b["y"] + b["h"])):
        if abs(d) < 1e-12:
            continue
        t0, t1 = (lo - p) / d, (hi - p) / d
        t_enter = max(t_enter, min(t0, t1))
    return {"x": sx + dx * t_enter, "y": sy + dy * t_enter}


# ---------------------------------------------------------------- resolve

def _mark_list(v: Any) -> list[str] | None:
    if isinstance(v, str) and v:
        return [v]
    if isinstance(v, list) and v and all(isinstance(s, str) and s for s in v):
        return list(v)
    return None


def _point(v: Any) -> dict[str, float] | None:
    if isinstance(v, dict) and _num01(v.get("x")) and _num01(v.get("y")):
        return {"x": float(v["x"]), "y": float(v["y"])}
    return None


def resolve_scene(scene: dict[str, Any], image_path: Path | None) -> SceneMarks:
    """シーン 1 つの注釈の位置を決める。image_path は撮影画像（無ければ None）。"""
    out = SceneMarks()
    recipe = scene.get("recipe")
    if recipe not in ("highlight_box", "arrow_move"):
        return out
    sid = scene["id"]
    params = scene.get("recipe_params") or {}
    if not isinstance(params, dict):
        params = {}

    # ---- 記録ファイル（mark を使うときだけ必要）
    marks: dict[str, dict[str, float]] | None = None
    record: dict[str, Any] | None = None
    marks_reason: str | None = None
    if image_path is None or not Path(image_path).is_file():
        marks_reason = "撮影画像がないため記録ファイルもありません"
    else:
        mp = marks_path(Path(image_path))
        if not mp.is_file():
            marks_reason = f"記録ファイルがありません（{mp.name}）"
        else:
            out.marks_file = mp
            marks, record, marks_reason = load_marks(mp)
            if record is not None:
                if record.get("scene") not in (None, sid):
                    out.warnings.append(f"{sid}: {mp.name} の scene が '{record.get('scene')}' です（取り違えの可能性）")
                if record.get("image") not in (None, Path(image_path).name):
                    out.warnings.append(f"{sid}: {mp.name} の image が '{record.get('image')}' です（取り違えの可能性）")
                size = record.get("image_size") or {}
                if isinstance(size.get("w"), (int, float)) and isinstance(size.get("h"), (int, float)) and size["h"]:
                    rec_aspect = size["w"] / size["h"]
                    if abs(rec_aspect / image_aspect(image_path) - 1) > 0.02:
                        out.warnings.append(f"{sid}: {mp.name} の image_size の縦横比が撮影画像と違います")
    aspect = image_aspect(image_path, record)

    def lookup(name: str) -> tuple[dict[str, float] | None, str | None]:
        if not MARK_NAME.match(name):
            return None, f"mark 名 '{name}' が書式（英小文字・数字・_）に合いません"
        if marks is None:
            return None, marks_reason
        if name not in marks:
            return None, f"mark '{name}' が記録にありません"
        return marks[name], None

    if recipe == "highlight_box":
        pad = params.get("pad", DEFAULT_PAD)
        if not (isinstance(pad, (int, float)) and not isinstance(pad, bool) and 0 <= pad <= 0.2):
            out.warnings.append(f"{sid}: recipe_params.pad は 0〜0.2 の数で指定してください。{DEFAULT_PAD} を使います")
            pad = DEFAULT_PAD
        if "mark" in params:
            names = _mark_list(params["mark"])
            if names is None:
                out.unresolved.append(Unresolved(sid, None, "recipe_params.mark の書き方が正しくありません"))
                out.annotations.append(Annotation(sid, recipe, "box", 0, None, "default", box=dict(DEFAULT_BOX)))
                return out
            for i, name in enumerate(names):
                b, reason = lookup(name)
                if b is None:
                    out.unresolved.append(Unresolved(sid, name, reason or "位置が分かりません"))
                    out.annotations.append(Annotation(sid, recipe, "box", i, name, "default", box=dict(DEFAULT_BOX)))
                else:
                    out.annotations.append(Annotation(sid, recipe, "box", i, name, "mark", box=pad_box(b, pad, aspect)))
            return out
        if "box" in params:
            if _valid_box(params["box"]):
                b = {k: float(params["box"][k]) for k in ("x", "y", "w", "h")}
                out.annotations.append(Annotation(sid, recipe, "box", 0, None, "coords", box=b))
            else:
                out.unresolved.append(Unresolved(sid, None, "recipe_params.box の値が正しくありません（0〜1、画像内）"))
                out.annotations.append(Annotation(sid, recipe, "box", 0, None, "default", box=dict(DEFAULT_BOX)))
            return out
        out.unresolved.append(Unresolved(sid, None, "枠の位置の指定（mark または box）がありません"))
        out.annotations.append(Annotation(sid, recipe, "box", 0, None, "default", box=dict(DEFAULT_BOX)))
        return out

    # ---- arrow_move
    to = params.get("to")
    explicit_from = _point(params.get("from")) if "from" in params else None
    if "from" in params and explicit_from is None:
        out.warnings.append(f"{sid}: recipe_params.from は x, y（0〜1）で指定してください。無視します")
    side = params.get("from_side", "left")
    if side not in SIDES:
        out.warnings.append(f"{sid}: recipe_params.from_side は {' / '.join(SIDES)} のいずれかです。left を使います")
        side = "left"

    def default_arrow(name: str | None, reason: str) -> SceneMarks:
        out.unresolved.append(Unresolved(sid, name, reason))
        out.annotations.append(Annotation(sid, recipe, "arrow", 0, name, "default",
                                          start=dict(DEFAULT_FROM), end=dict(DEFAULT_TO)))
        return out

    if isinstance(to, dict) and "mark" in to:
        name = to["mark"]
        if not isinstance(name, str) or not name:
            return default_arrow(None, "recipe_params.to.mark の書き方が正しくありません")
        b, reason = lookup(name)
        if b is None:
            return default_arrow(name, reason or "位置が分かりません")
        start = explicit_from or side_start(b, side, aspect)
        end = edge_point(start, b)
        if abs(start["x"] - end["x"]) < 1e-6 and abs(start["y"] - end["y"]) < 1e-6:
            out.warnings.append(f"{sid}: 矢印の出発点と到着点が同じです（mark が画像の端にあります）。from を指定してください")
        out.annotations.append(Annotation(sid, recipe, "arrow", 0, name, "mark", start=start, end=end, target=b))
        return out
    if to is not None:
        p = _point(to)
        if p is None:
            return default_arrow(None, "recipe_params.to の値が正しくありません（{mark} または x, y）")
        out.annotations.append(Annotation(sid, recipe, "arrow", 0, None, "coords",
                                          start=explicit_from or dict(DEFAULT_FROM), end=p))
        return out
    return default_arrow(None, "矢印の行き先の指定（to）がありません")
