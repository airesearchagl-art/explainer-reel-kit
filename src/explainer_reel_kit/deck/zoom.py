"""注釈まわりの拡大（recipe_params.zoom）。

1920×1080 の画面を丸ごと縮めると文字が読めないため、そのシーンの注釈（枠・矢印）を囲む範囲を
切り出して画像枠いっぱいに表示する。

- 範囲 = 全注釈を囲む矩形 + 余白（既定 0.08、画像幅に対する比。縦は画像の縦横比で換算）
- スライドの画像枠と同じ縦横比に広げ、元画像からはみ出さないよう平行移動する
- 拡大しすぎない: 切り出す幅は元画像の 40% 以上（拡大は最大 2.5 倍）
- 注釈の座標は「元画像に対する相対座標」→「切り出した範囲に対する相対座標」に写す（View.map_*）
  スライド（builder.py）と一覧画像（overlay.py）は同じ View を使う
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .marks import Annotation

DEFAULT_MARGIN = 0.08
MIN_WIDTH = 0.40  # 切り出す幅の下限（元画像の幅に対する比）


@dataclass(frozen=True)
class View:
    """表示する範囲（元画像に対する相対座標）。全体なら (0, 0, 1, 1)。"""

    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0
    # 縦長の部品: 画像枠の縦横比では切り出せないため、切り出す範囲の縦横比のまま表示する。
    # 画像枠より細くなり、左右に余白（スライドの背景）が入る。見出し・画面テキストの位置は変わらない
    narrow: bool = False

    @property
    def is_full(self) -> bool:
        return self.x <= 1e-9 and self.y <= 1e-9 and self.w >= 1 - 1e-9 and self.h >= 1 - 1e-9

    def map_point(self, p: dict[str, float]) -> dict[str, float]:
        return {"x": (p["x"] - self.x) / self.w, "y": (p["y"] - self.y) / self.h}

    def map_box(self, b: dict[str, float]) -> dict[str, float]:
        return {"x": (b["x"] - self.x) / self.w, "y": (b["y"] - self.y) / self.h,
                "w": b["w"] / self.w, "h": b["h"] / self.h}

    def record(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: round(getattr(self, k), 4) for k in ("x", "y", "w", "h")}
        if self.narrow:
            out["narrow"] = True
        return out


FULL = View()


PER_MARK = "per_mark"


def is_per_mark(value: Any) -> bool:
    """zoom: per_mark— 複数の枠を 1 枠 1 スライドに分け、枠ごとに拡大して Morph でつなぐ。"""
    return value == PER_MARK or (isinstance(value, dict) and value.get("mode") == PER_MARK)


def parse_zoom(value: Any) -> tuple[bool, float, str | None]:
    """recipe_params.zoom → (拡大するか, 余白, 書き方の誤り)。

    true / false / per_mark / {margin: 数} / {mode: per_mark, margin: 数}。per_mark も「拡大する」に含む。
    """
    if value is None or value is False:
        return False, DEFAULT_MARGIN, None
    if value is True or value == PER_MARK:
        return True, DEFAULT_MARGIN, None
    if isinstance(value, dict) and set(value) - {"margin", "mode"}:
        return True, DEFAULT_MARGIN, "zoom に使えない項目があります（margin / mode のみ）"
    if isinstance(value, dict) and value.get("mode") not in (None, PER_MARK):
        return True, DEFAULT_MARGIN, "zoom.mode は per_mark だけ指定できます"
    if isinstance(value, dict):
        m = value.get("margin", DEFAULT_MARGIN)
        if isinstance(m, (int, float)) and not isinstance(m, bool) and 0 <= m <= 0.5:
            return True, float(m), None
        return True, DEFAULT_MARGIN, "zoom.margin は 0〜0.5 の数で指定してください"
    return False, DEFAULT_MARGIN, "zoom は true / false / per_mark / {margin: 数} で指定してください"


def _extent(annotations: Sequence[Annotation]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for a in annotations:
        for b in (a.box, a.target):
            if b is not None:
                xs += [b["x"], b["x"] + b["w"]]
                ys += [b["y"], b["y"] + b["h"]]
        for p in (a.start, a.end):
            if p is not None:
                xs.append(p["x"])
                ys.append(p["y"])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


MAX_ZOOM = 1 / MIN_WIDTH  # 2.5 倍
NARROW_MARGIN_Y = 0.02  # 細い画像枠のときの縦の余白（画像の高さに対する比）
# 通常の切り出し（画像枠の縦横比）の拡大率がこれ未満で、細い画像枠の方が大きく見えるなら細い枠にする。
# 16:9 の撮影画像では、幅いっぱいの通常の切り出しでも計算上 約 1.36 倍になるため、1.2 では縦長の部品を拾えない
NARROW_PREFER_BELOW = 1.5


def fit_rect(view: View, image_size: tuple[int, int], frame_w: float, frame_h: float) -> tuple[float, float, float, float]:
    """切り出した範囲を、縦横比を保って画像枠（frame_w × frame_h）の中央に置いた矩形 (left, top, w, h)。

    スライド（builder._fit：画像枠に収めて中央に置く）と一覧画像（overlay.py）で同じ置き方にするための計算。
    細い画像枠（narrow）では左右、横に長い範囲では上下に余白が入る。
    """
    W, H = image_size
    cw, ch = view.w * W, view.h * H
    scale = min(frame_w / cw, frame_h / ch)
    w, h = cw * scale, ch * scale
    return (frame_w - w) / 2, (frame_h - h) / 2, w, h


def magnification(view: View, image_size: tuple[int, int], frame_aspect: float) -> float:
    """表示の拡大率: 画像全体を画像枠に縦横比を保って収めたときに比べ、元画像の 1 ピクセルが何倍に見えるか。"""
    W, H = image_size
    full = min(frame_aspect / W, 1 / H)
    return min(frame_aspect / (view.w * W), 1 / (view.h * H)) / full


def _narrow_view(px0: float, py0: float, px1: float, py1: float, W: int, H: int, frame_aspect: float) -> View | None:
    """縦長の部品: 注釈＋余白の範囲を、その縦横比のまま切り出す（画像枠を細くして表示する）。

    拡大率（画像枠に全体を収めたときに比べた大きさ）は最大 2.5 倍。範囲は元画像の内側。
    """
    cw, ch = px1 - px0, py1 - py0
    if cw <= 0 or ch <= 0:
        return None
    # 画像枠の高さを 1、幅を frame_aspect としたときの表示倍率
    full = min(frame_aspect / W, 1 / H)
    mag = min(frame_aspect / cw, 1 / ch) / full
    if mag > MAX_ZOOM:
        k = mag / MAX_ZOOM
        cw, ch = min(W, cw * k), min(H, ch * k)
    cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
    left = min(max(cx - cw / 2, 0.0), W - cw)
    top = min(max(cy - ch / 2, 0.0), H - ch)
    v = View(left / W, top / H, cw / W, ch / H, narrow=True)
    if v.w >= 0.98 and v.h >= 0.98:
        return None
    return v


def compute_view(annotations: Sequence[Annotation], image_size: tuple[int, int], frame_aspect: float,
                 margin: float = DEFAULT_MARGIN, min_width: float = MIN_WIDTH,
                 allow_narrow: bool = True) -> tuple[View, str | None]:
    """注釈を囲む範囲を、frame_aspect（幅/高さ）の縦横比で元画像の中に切り出す。

    画像枠の縦横比では注釈が収まらない（縦に長い部品など）ときは、allow_narrow なら
    注釈＋余白の縦横比のまま切り出し、画像枠を細くして表示する（View.narrow）。
    収まる場合も、通常の切り出しの拡大率が NARROW_PREFER_BELOW 未満で、細い枠の方が大きく見えるなら
    細い枠を選ぶ。
    戻り値 (View, 拡大しなかった理由)。拡大できないときは FULL。
    """
    ext = _extent(annotations)
    if ext is None:
        return FULL, "拡大の基準になる注釈がありません"
    W, H = image_size
    x0, y0, x1, y1 = ext
    # ピクセルで計算する（縦横比を正しく扱うため）
    mx = margin * W
    px0, py0 = max(0.0, x0 * W - mx), max(0.0, y0 * H - mx)
    px1, py1 = min(float(W), x1 * W + mx), min(float(H), y1 * H + mx)
    cw, ch = px1 - px0, py1 - py0
    cw = max(cw, min_width * W)
    # 画像枠の縦横比に広げる
    if cw / max(ch, 1e-9) < frame_aspect:
        cw = ch * frame_aspect
    else:
        ch = cw / frame_aspect
    # 元画像に収める（縦横比は保つ）
    if cw > W:
        cw, ch = W, W / frame_aspect
    if ch > H:
        ch, cw = H, H * frame_aspect
    cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
    left = min(max(cx - cw / 2, 0.0), W - cw)
    top = min(max(cy - ch / 2, 0.0), H - ch)
    view = View(left / W, top / H, cw / W, ch / H)
    if view.w >= 1 - 1e-6 and view.h >= 1 - 1e-6:
        view = FULL
    # 細い画像枠の候補（縦の余白は画像の高さの 2%。縦長の部品は高さで拡大率が決まるため、
    # 横と同じ余白を取ると、ほとんど拡大されない）
    narrow: View | None = None
    if allow_narrow:
        my = min(mx, NARROW_MARGIN_Y * H, max(0.0, (H - (y1 - y0) * H) / 2))
        narrow = _narrow_view(px0, max(0.0, y0 * H - my), px1, min(float(H), y1 * H + my), W, H, frame_aspect)
    # 注釈（余白なし）が範囲に収まらなければ、通常の切り出しは使えない
    eps = 1e-6
    if x0 < view.x - eps or y0 < view.y - eps or x1 > view.x + view.w + eps or y1 > view.y + view.h + eps:
        if narrow is not None:
            return narrow, None
        return FULL, "注釈が広い範囲にあり、画像枠の縦横比で切り出すと一部が外れるため拡大しません"
    # 両方の拡大率を比べ、通常の切り出しがあまり拡大できないときは、大きく見える方を選ぶ
    if narrow is not None:
        m_normal = magnification(view, image_size, frame_aspect)
        m_narrow = magnification(narrow, image_size, frame_aspect)
        if m_normal < NARROW_PREFER_BELOW and m_narrow > m_normal * 1.01:
            return narrow, None
    return view, None
