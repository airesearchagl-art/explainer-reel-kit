# -*- coding: utf-8 -*-
"""部品の共通: きっかけ・現れ方・読んでいる箇所の示し方・消え方。

部品は scenes.yaml の 1 つの項目から作り、``draw(f, t)`` で表示リストに積む。色・余白・書体はエンジンの決まり
（engine の色の名前・Noto Sans JP・角丸 16）から取り、文字は ``maxw`` / ``text_box`` で枠に入らなければ LayoutError。

項目の並び（cards・steps・table の行・image・flow・number）は、どの部品でも同じ決まりで動く:

- ``show: each``（既定）: 項目は自分のきっかけ（at / sentence）で現れる。きっかけの無い項目は部品と一緒に
- ``show: all``: 項目は部品のきっかけで一緒に現れ（見本帳の stagger の --i × 秒ずつずれる）、項目のきっかけは示し方だけに使う
- 読んでいる間（項目のきっかけ → 次の項目のきっかけ・until・場面の終わり）は ``emphasis`` の動きで示す
- ``dim``: 読んでいない項目を沈める量（既定は見本帳 30 roomhighlight の「ほかは opacity .45」→ 0.55。0 で沈めない）
- ``keep: true``: 読み終えた項目は沈めない（読む前の項目だけ沈める）
- 部品の ``until``: その時刻で部品を消す（見本帳 26 fadethrough の out .09s）。同じ場所の中身を入れ替える場面に
"""
from __future__ import annotations

from typing import Any

from .. import motion as mo
from ..engine import (AMBER, BLUE, CORAL, GREEN, INK, LINE, PANEL, PANEL2, TEAL, TEAL_D, TEXT, TEXT2, TEXT3, Frame,
                      LayoutError, tw)
from ..spec import CUE_PROPS, Cue, Ctx, SpecError, check_motion

COLORS = {"text": TEXT, "text2": TEXT2, "text3": TEXT3, "teal": TEAL, "teal_d": TEAL_D, "amber": AMBER,
          "blue": BLUE, "green": GREEN, "coral": CORAL, "ink": INK, "line": LINE}
COLOR = {"enum": list(COLORS), "description": "色の名前（engine の色）"}
LINES = {"anyOf": [{"type": "string", "minLength": 1},
                   {"type": "array", "items": {"type": "string"}, "minItems": 1}],
         "description": "文字。文字列なら枠の幅で折り返し、並びなら 1 行ずつ（改行の位置を決める）"}
UNTIL = {"type": "object", "properties": dict(CUE_PROPS), "additionalProperties": False,
         "description": "ここで終える（部品なら消す、項目なら示すのをやめる）"}
SIZE = {"type": "integer", "minimum": 14, "maximum": 160, "description": "文字の大きさ（px）"}
SHOW = {"enum": ["each", "all"], "description": "each: 項目は自分のきっかけで現れる／all: 部品と一緒に現れる"}
DIM = {"type": "number", "minimum": 0, "maximum": 1, "description": "読んでいない項目を沈める量（0 で沈めない）"}
KEEP = {"type": "boolean", "description": "読み終えた項目は沈めない"}

FOCUS = {"anyOf": [{"const": False}, {"type": "object", "additionalProperties": False,
                                        "properties": dict(CUE_PROPS, until=UNTIL)}],
         "description": "示す時間（false で示さない。{at, sentence, until} で現れる時刻とは別に決める）"}
ITEM_CUE = dict(CUE_PROPS, until=UNTIL, focus=FOCUS)

FADE_OUT = mo.MOTIONS["fadethrough"]   # 部品を消す（until）


def color(name: str | None, default: str = TEXT) -> str:
    return COLORS.get(name, default) if name else default


def as_lines(v) -> list[str] | str:
    return list(v) if isinstance(v, list) else v


class Part:
    """部品の基底。サブクラスは TYPE・TITLE・DOC・SCHEMA・(REQUIRED・MOTION_FIELDS・DEFAULTS) と draw を持つ。"""

    TYPE = ""
    TITLE = ""
    DOC = ""
    SCHEMA: dict[str, Any] = {}
    REQUIRED: tuple[str, ...] = ()
    MOTION_FIELDS: dict[str, tuple[str, ...]] = {}
    DEFAULTS: dict[str, str] = {}
    FIXED_BOX: tuple | None = None        # 決まった置き場（見出しなど）。None なら上から積む
    HEIGHT = 200                          # 上から積むときの高さの既定
    ITEMS: str | None = None              # 項目の並びの項目名（items など）

    @classmethod
    def natural_height(cls, spec: dict) -> float:
        return spec.get("height", cls.HEIGHT)

    def __init__(self, spec: dict, ctx: Ctx):
        self.spec = spec
        self.ctx = ctx
        self.T = ctx.T
        check_motion(type(self), spec, ctx.where)
        self.x, self.y, self.w, self.h = ctx.box
        self.speed = float(spec.get("speed", 1.0))
        self.enter = self._motion("motion")
        self.emph = self._motion("emphasis")
        self.cue = ctx.cue(spec, "")
        self.until = ctx.cue(spec["until"], ".until") if "until" in spec else None
        self.scene_end = ctx.scene["end"]
        others = self.emph.params.get("others_opacity") if self.emph else None   # 30 roomhighlight だけが沈める
        self.dim = float(spec.get("dim", (1 - others) if others is not None else 0.0))
        self.keep = bool(spec.get("keep", False))
        self.show_all = spec.get("show", "each") == "all"
        self.items: list[dict] = []
        self.cues: list[Cue] = []
        self.ends: list[float] = []
        self.windows: list[tuple[float, float] | None] = []
        if self.ITEMS:
            self._items(spec.get(self.ITEMS) or [])
        self.build()

    # ---- 名前と確かめ
    @property
    def label(self) -> str:
        return f"{self.TYPE}"

    def cue_points(self) -> list[tuple[Cue, float]]:
        """[(きっかけ, 動きが終わる秒)]。sheet の 3 枚（前・直後・終わり）に使う。"""
        n = len(self.items) if self.show_all else 1
        pts = [(self.cue, self.cue.t + self.enter.end_sec(items=n, speed=self.speed))]
        for c, it in zip(self.cues, self.items):
            if c is not None and abs(c.t - self.cue.t) > 1e-6:
                end = c.t + max(self.enter.end_sec(speed=self.speed),
                                self.emph.end_sec(speed=self.speed) if self.emph else 0.0)
                pts.append((c, end))
        if self.until is not None:
            pts.append((self.until, self.until.t + FADE_OUT.duration))
        return pts

    # ---- 動き
    def _motion(self, key: str):
        if key not in self.MOTION_FIELDS:
            return None
        name = self.spec.get(key, self.DEFAULTS.get(key))
        if name in (None, "none"):
            return None
        return mo.get(name)

    def _items(self, raw: list, names: list[str] | None = None) -> None:
        """項目のきっかけと、読んでいる間の終わりを決める。names は誤りの場所の名前（無ければ <ITEMS>[i]）。"""
        for i, it in enumerate(raw):
            it = it if isinstance(it, dict) else {"text": it}
            where = f".{names[i]}" if names else f".{self.ITEMS}[{i}]"
            has = "at" in it or "sentence" in it
            self.items.append(it)
            self.cues.append(self.ctx.cue(it, where) if has else None)
        starts = [c.t if c else None for c in self.cues]
        self.windows: list[tuple[float, float] | None] = []
        for i, it in enumerate(self.items):
            if "until" in it:
                self.ends.append(self.ctx.cue(it["until"], (f".{names[i]}" if names else f".{self.ITEMS}[{i}]") + ".until").t)
                continue
            nxt = [s for s in starts[i + 1:] if s is not None and starts[i] is not None and s > starts[i]]
            end = nxt[0] if nxt else (self.until.t if self.until else self.scene_end)
            self.ends.append(end)
        for i, it in enumerate(self.items):
            fo = it.get("focus", True)
            loc = (f".{names[i]}" if names else f".{self.ITEMS}[{i}]") + ".focus"
            if fo is False:
                self.windows.append(None)
            elif isinstance(fo, dict):
                c = self.ctx.cue(fo, loc)
                end = self.ctx.cue(fo["until"], loc + ".until").t if "until" in fo else self.ends[i]
                self.windows.append((c.t, max(end, c.t)))
            else:
                self.windows.append((self.cues[i].t, self.ends[i]) if self.cues[i] is not None else None)

    def build(self) -> None:
        """組み立て（置き場の計算・文字の確かめ）。サブクラスで。"""

    def alive(self, t: float) -> float:
        """until で消すときの濃さ（1 → 0）。"""
        if self.until is None:
            return 1.0
        return 1.0 - FADE_OUT.progress(t, self.until.t, speed=self.speed)

    def item_start(self, i: int) -> float:
        c = self.cues[i] if i < len(self.cues) else None
        if self.show_all or c is None:
            return self.cue.t
        return c.t

    def appear(self, t: float, t0: float, i: int = 0, size: int = 32, w: float = 0.0) -> tuple[float, float, float]:
        """現れ方 → (濃さ, x のずれ, y のずれ)。i は同じきっかけで並ぶ順（見本帳の --i）。"""
        m = self.enter
        if m is None:
            return (1.0 if t >= t0 else 0.0), 0.0, 0.0
        p = m.progress(t, t0, i=i, speed=self.speed)
        dx = dy = 0.0
        if "dy" in m.params:
            dy = m.params["dy"] * (1 - p)
        if "dy_em" in m.params:
            dy = m.params["dy_em"] * size * (1 - p)
        if "dx_ratio" in m.params:
            sign = -1 if self.spec.get("direction") == "reverse" else 1
            dx = sign * m.params["dx_ratio"] * w * (1 - p)
        return p, dx, dy

    def item_alpha(self, t: float, i: int, size: int = 32, w: float = 0.0) -> tuple[float, float, float]:
        k = i if (self.show_all or self.cues[i] is None) else 0
        a, dx, dy = self.appear(t, self.item_start(i), k, size, w)
        return a * self.alive(t), dx, dy

    def on(self, t: float, i: int) -> float:
        """項目 i を読んでいる度合い 0..1（示し方の動きの長さで上がり、終わりで同じ長さで下がる）。"""
        win = self.windows[i] if i < len(self.windows) else None
        if self.emph is None or win is None:
            return 0.0
        t0, t1 = win
        up = self.emph.progress(t, t0, speed=self.speed, delay=0.0)
        down = self.emph.progress(t, t1, speed=self.speed, delay=0.0)
        return max(0.0, min(up, 1.0 - down)) * self.alive(t)

    def read(self, t: float, i: int) -> float:
        """項目 i を読み始めたか 0..1。"""
        if i >= len(self.cues) or self.cues[i] is None:
            return 1.0
        return self.emph.progress(t, self.cues[i].t, speed=self.speed, delay=0.0) if self.emph else 1.0

    def veil_amount(self, t: float, i: int) -> float:
        """項目 i を沈める量。読んでいる項目は 0。keep なら読み終えた項目も 0。"""
        if self.emph is None or self.dim <= 0 or not any(c is not None for c in self.cues):
            return 0.0
        if self.cues[i] is None:
            return 0.0
        lit = self.on(t, i)
        if self.keep:
            lit = max(lit, self.read(t, i))
        return self.dim * (1.0 - lit)

    def emphasize(self, f: Frame, t: float, i: int, box, a: float, r: int = 16) -> None:
        """項目 i を示す（読んでいる間）。box は (x, y, w, h)。"""
        x, y, w, h = box
        v = self.veil_amount(t, i) * a
        if v > 0.004:
            f.veil(x - 3, y - 3, w + 6, h + 6, v, r=r)
        on = self.on(t, i)
        if on <= 0 or self.emph is None:
            return
        name = self.emph.id
        t_on = self.windows[i][0]
        if name == "roomhighlight":
            f.focus(x, y, w, h, r=r, a=on * a)
        elif name == "fill":
            p = self.emph.progress(t, t_on, speed=self.speed)
            f.rr(x, y, max(2, w * p), h, r=r, fill="#62c0d029", a=on * a)   # TEAL を .16 の濃さで
            f.rr(x, y, w, h, r=r, outline=TEAL, ow=2, a=on * a)
        elif name == "underline":
            p = self.emph.progress(t, t_on, speed=self.speed)
            f.rr(x, y + h + 6, max(2, w * p), self.emph.params.get("height", 3), r=1, fill=AMBER, a=on * a)
        elif name == "hotspot":
            self.pulse(f, t, x + w / 2, y + h / 2, min(w, h) * 0.5, t_on, a * on)

    def pulse(self, f: Frame, t: float, cx: float, cy: float, dia: float, t0: float, a: float) -> None:
        """見本帳 28 hotspot: 輪が opacity .9→0、scale 1→3.6（1.1s ease-out、2 つ目は .45s 後）を繰り返す。"""
        m = mo.MOTIONS["hotspot"]
        d = m.duration / self.speed
        for k in (0.0, m.params["second"] / self.speed):
            s = t - t0 - k
            if s < 0:
                continue
            p = mo.ease_value(m.easing, (s % d) / d)
            dd = dia * (1 + (m.params["scale_to"] - 1) * p)
            f.circ(cx, cy, int(dd), outline=AMBER, ow=m.params["border"], a=a * m.params["opacity_from"] * (1 - p))
        f.circ(cx, cy, int(dia * 0.5), fill=AMBER, a=a)

    # ---- 文字
    def lines(self, f: Frame, v, x: float, y: float, w: float, h: float, *, size: int, color_: str = TEXT,
              weight: str = "R", a: float = 1.0, lh: int | None = None, align: str = "l", valign: str = "t"):
        """文字（文字列なら折り返し、並びなら 1 行ずつ）を枠に書く。入らなければ LayoutError。"""
        return f.text_box(as_lines(v), x, y, w, h, size=size, color=color_, weight=weight, a=a, lh=lh, align=align,
                          valign=valign)

    def check_fits(self, s: str, size: int, weight: str, maxw: float, what: str) -> None:
        if tw(s, weight, size) > maxw + 0.5:
            raise LayoutError(f"{what}が枠に入りません（幅 {tw(s, weight, size):.0f}px ＞ {maxw:.0f}px）: {s}")

    def draw(self, f: Frame, t: float) -> None:  # pragma: no cover - サブクラスで
        raise NotImplementedError


def grid(n: int, columns: int, box, gap: float, row_gap: float | None = None, height: float | None = None):
    """n 個を columns 列に並べた箱 [(x, y, w, h)]。"""
    x, y, w, h = box
    cols = max(1, min(columns, n))
    rows = (n + cols - 1) // cols
    rg = gap if row_gap is None else row_gap
    cw = (w - gap * (cols - 1)) / cols
    ch = height if height is not None else (h - rg * (rows - 1)) / rows
    return [(x + (i % cols) * (cw + gap), y + (i // cols) * (ch + rg), cw, ch) for i in range(n)]


def badge(f: Frame, n, cx: float, cy: float, a: float, dia: int, on: bool = True) -> None:
    f.badge(n, cx, cy, a=a, dia=dia, on=on)


def check_icon(f: Frame, cx: float, cy: float, a: float = 1.0, dia: int = 30, kind: str = "check") -> None:
    """項目の頭の印: check（TEAL の丸にレ点）・cross（CORAL の丸に ×）・dot・arrow（AMBER の矢印）。"""
    k = dia / 34.0
    if kind == "check":
        f.circ(cx, cy, dia, fill=TEAL, a=a)
        f.path([(cx - 8 * k, cy), (cx - 2 * k, cy + 7 * k), (cx + 9 * k, cy - 7 * k)], color="#06202c", width=3, a=a)
    elif kind == "cross":
        f.circ(cx, cy, dia, fill=CORAL, a=a)
        f.path([(cx - 6 * k, cy - 6 * k), (cx + 6 * k, cy + 6 * k)], color="#2a0c08", width=3, a=a)
        f.path([(cx - 6 * k, cy + 6 * k), (cx + 6 * k, cy - 6 * k)], color="#2a0c08", width=3, a=a)
    elif kind == "dot":
        f.circ(cx, cy, int(dia * 0.4), fill=TEAL, a=a)
    elif kind == "arrow":
        f.path([(cx - 16 * k, cy), (cx + 16 * k, cy)], color=AMBER, width=4, head=True, a=a)


__all__ = ["COLOR", "COLORS", "DIM", "FOCUS", "ITEM_CUE", "KEEP", "LINES", "Part", "SHOW", "SIZE", "SpecError", "UNTIL",
           "as_lines", "badge", "check_icon", "color", "grid", "PANEL", "PANEL2", "LINE", "TEAL", "TEXT", "TEXT2",
           "TEXT3", "AMBER"]
