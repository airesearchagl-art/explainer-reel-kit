# -*- coding: utf-8 -*-
"""数値の部品: number（数値のカードを読み上げの順に出す。数字は見本帳 T08 のカウントアップ、割合は帯で）。"""
from __future__ import annotations

import re

from ..engine import LINE, PANEL, TEAL, TEAL_D, TEXT, TEXT2, TEXT3, LayoutError, tw
from .base import COLOR, DIM, ITEM_CUE, KEEP, SHOW, Part, color

_NUM = re.compile(r"^([^\d]*)([\d,]+(?:\.\d+)?)(.*)$")
BAR_COLORS = [LINE, TEAL_D, TEAL]


def count_text(value: str, p: float) -> str:
    """'12,480' を p（0..1）の割合まで数えた文字。数字でなければそのまま。桁の区切り・小数の桁は元のまま。"""
    m = _NUM.match(value)
    if not m or p >= 1:
        return value
    head, num, tail = m.groups()
    decimals = len(num.split(".")[1]) if "." in num else 0
    v = float(num.replace(",", "")) * p
    s = f"{v:,.{decimals}f}" if "," in num else f"{v:.{decimals}f}"
    return head + s + tail


class Number(Part):
    TYPE = "number"
    TITLE = "数値の強調"
    DOC = ("数値のカード（大きな数字・単位・説明）を横に並べ、読み上げの順に出す。数字は見本帳 T08 のカウントアップ"
           "（motion: counter）。ratio を書くと、カードの下に割合の帯（0〜1）と目盛りを出す")
    SCHEMA = {
        "items": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False, "required": ["value"],
            "properties": dict(ITEM_CUE, value={"type": "string", "minLength": 1},
                               unit={"type": "string"}, caption={"type": "string"},
                               ratio={"type": "number", "minimum": 0, "maximum": 1},
                               color=COLOR)}},
        "card_width": {"type": "number", "minimum": 80},
        "height": {"type": "number", "minimum": 60, "description": "カードの高さ（既定 138）"},
        "gap": {"type": "number", "minimum": 0, "description": "カードの間（既定 20）"},
        "size": {"type": "integer", "minimum": 30, "maximum": 160, "description": "数字の大きさ（既定 76）"},
        "bar_width": {"type": "number", "minimum": 80, "description": "割合の帯の幅（既定は枠の幅）"},
        "show": SHOW, "dim": DIM, "keep": KEEP,
    }
    REQUIRED = ("items",)
    MOTION_FIELDS = {"motion": ("counter", "stagger", "fade-in", "cut"), "emphasis": ("roomhighlight", "underline", "none")}
    DEFAULTS = {"motion": "counter", "emphasis": "none"}
    ITEMS = "items"

    @classmethod
    def natural_height(cls, spec):
        h = spec.get("height", 138)
        if any(isinstance(i, dict) and "ratio" in i for i in spec.get("items") or []):
            h += 26 + 22 + 50
        return h

    def build(self):
        n = len(self.items)
        gap = self.spec.get("gap", 20)
        cw = self.spec.get("card_width", (self.w - gap * (n - 1)) / n)
        ch = self.spec.get("height", 138)
        self.size = self.spec.get("size", 76)
        self.boxes = [(self.x + i * (cw + gap), self.y, cw, ch) for i in range(n)]
        for i, (it, (x, y, w, h)) in enumerate(zip(self.items, self.boxes)):
            need = tw(it["value"], "B", self.size) + (tw(it.get("unit", ""), "B", 36) + 8 if it.get("unit") else 0) + 60
            if need > w + 0.5:
                raise LayoutError(f"{self.ctx.where}.items[{i}]: 数字が枠に入りません（幅 {need:.0f}px ＞ {w:.0f}px）")
        self.bar = any("ratio" in it for it in self.items)
        self.bar_w = self.spec.get("bar_width", self.w)

    def _p(self, t, i):
        """数え上げの進み（counter は説明動画の既定 0.8 秒、ease-out-cubic。見本帳は 0.2s 後から 1.6s）。"""
        m = self.enter
        return m.progress(t, self.item_start(i), speed=self.speed) if m else 1.0

    def draw(self, f, t):
        live = self.alive(t)
        for i, (it, (x, y, w, h)) in enumerate(zip(self.items, self.boxes)):
            t0 = self.item_start(i)
            if t < t0:
                continue
            counting = self.enter is not None and self.enter.id == "counter"
            if counting:
                a = min(1.0, (t - t0) / 0.35) * live if t >= t0 else 0.0   # 枠は先に出す（数字だけ数える）
                dx = dy = 0.0
            else:
                a, dx, dy = self.item_alpha(t, i, self.size, w)
            if a <= 0:
                continue
            x, y = x + dx, y + dy
            f.rr(x, y, w, h, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
            p = self._p(t, i) if counting else 1.0
            val = count_text(it["value"], p)
            f.text(val, x + 30, y + 12, size=self.size, w="B", a=a, maxw=w - 40)
            if it.get("unit"):
                f.text(it["unit"], x + 30 + tw(val, "B", self.size) + 8, y + 12 + self.size * 0.5, size=36, w="B",
                       a=a)
            if it.get("caption"):
                f.text(it["caption"], x + 32, y + h - 42, size=28, color=TEXT2, a=a, maxw=w - 44)
            if self.bar and "ratio" in it:
                by = max(b[1] + b[3] for b in self.boxes) + 26
                grow = p if counting else self._p(t, i)
                col = color(it.get("color"), BAR_COLORS[min(i, len(BAR_COLORS) - 1)])
                f.rr(self.x, by, max(8, int(self.bar_w * it["ratio"] * grow)), 22, r=6, fill=col, a=a)
                tx = self.x + self.bar_w * it["ratio"]
                f.rr(tx - 1, by + 26, 2, 10, r=0, fill=TEXT3, a=a)
                f.text(it["value"], tx, by + 40, size=22, color=TEXT2, a=a, anchor="r" if i == 0 else "c")
            self.emphasize(f, t, i, (x, y, w, h), a)


PARTS = [Number]
