# -*- coding: utf-8 -*-
"""見出しの部品: header（画面の上の見出し）・heading（段の見出し・一行の見出し）・title（中央の題）。"""
from __future__ import annotations

from ..engine import LINE, STEP_DONE, TEAL, TEXT, TEXT2, TEXT3, W, Frame, tw
from .base import COLOR, LINES, SIZE, Part, as_lines, color

TEXT_ENTER = ("fade-in", "stagger-T03", "typewriter", "cut", "fade")


def _chars(f: Frame, part: Part, s: str, x: float, y: float, *, size: int, color_: str, weight: str, a: float,
           t: float, t0: float, anchor: str = "l") -> None:
    """1 文字ずつ現れる動き（見本帳 T03 文字送り・T02 タイプ表示）。"""
    total = tw(s, weight, size)
    x0 = x - (total / 2 if anchor == "c" else total if anchor == "r" else 0)
    for i, ch in enumerate(s):
        p, _, dy = part.appear(t, t0, i, size)
        if p > 0:
            f.text(ch, x0 + tw(s[:i], weight, size), y + dy, size=size, color=color_, w=weight, a=a * p)


def text_line(f: Frame, part: Part, s: str, x: float, y: float, *, size: int, color_: str, weight: str, a: float,
              t: float, t0: float, anchor: str = "l", maxw: float | None = None, i: int = 0) -> None:
    """1 行の文字を、部品の現れ方で書く。"""
    if maxw is not None:
        part.check_fits(s, size, weight, maxw, "文字")
    m = part.enter
    if m is not None and m.id in ("stagger-T03", "typewriter"):
        _chars(f, part, s, x, y, size=size, color_=color_, weight=weight, a=a, t=t, t0=t0, anchor=anchor)
        return
    p, dx, dy = part.appear(t, t0, i, size)
    if p > 0:
        f.text(s, x + dx, y + dy, size=size, color=color_, w=weight, a=a * p, anchor=anchor, maxw=maxw)


class Header(Part):
    TYPE = "header"
    TITLE = "見出し"
    DOC = ("画面の上の見出し（左の色の帯＋題＋罫線）。右上に進行表示（progress）と札（label）、左下に注記（foot）。"
           "題は現れ方の動きで出し、罫線・進行表示・札は場面をまたいで動かさない")
    SCHEMA = {
        "title": {"type": "string", "minLength": 1, "description": "題"},
        "size": dict(SIZE, description="題の文字の大きさ（既定 48）"),
        "label": {"type": "string", "description": "右上の札（薄い色）"},
        "label_accent": {"type": "string", "description": "右上の札のうち、強調する部分（TEAL・太字。label の右）"},
        "progress": {"type": "object", "additionalProperties": False, "required": ["total"],
                     "properties": {"total": {"type": "integer", "minimum": 1, "maximum": 12},
                                    "current": {"type": "integer", "minimum": 0, "maximum": 12},
                                    "done": {"type": "integer", "minimum": 0, "maximum": 12}},
                     "description": "右上の進行表示（全体の段の数・今の段・済んだ段の数。今の段は TEAL、済んだ段は暗い色）"},
        "foot": {"type": "string", "description": "左下の注記（y 894、薄い色）"},
    }
    REQUIRED = ("title",)
    MOTION_FIELDS = {"motion": TEXT_ENTER}
    DEFAULTS = {"motion": "fade-in"}
    FIXED_BOX = (96, 60, 1728, 84)

    def build(self):
        self.size = self.spec.get("size", 48)
        self.check_fits(self.spec["title"], self.size, "B", 1824 - 126 - self._right_width() - 40, "見出し")

    def _right_width(self) -> float:
        w = 0.0
        if self.spec.get("label_accent"):
            w += tw(self.spec["label_accent"], "B", 26) + 6
        if self.spec.get("label"):
            w += tw(self.spec["label"], "R", 24)
        pr = self.spec.get("progress")
        if pr:
            w = max(w, 372 if pr["total"] > 4 else 360)
        return w

    def draw(self, f, t):
        live = self.alive(t)
        a, _, _ = self.appear(t, self.cue.t, 0, self.size)
        a *= live
        f.rr(96, 60, 8, 62, r=4, fill=TEAL, a=a)
        text_line(f, self, self.spec["title"], 126, 67 - (self.size - 48) * 0.5, size=self.size, color_=TEXT,
                  weight="B", a=live, t=t, t0=self.cue.t)
        f.rr(96, 142, 1728, 2, r=0, fill=LINE, a=live)
        pr = self.spec.get("progress")
        if pr:
            n = pr["total"]
            gap = 8 if n <= 4 else 6
            sw = (360 if n <= 4 else 372) - gap * (n - 1)
            sw = int(round(sw / n))
            x0 = 1824 - (n * sw + (n - 1) * gap)
            cur = pr.get("current", 0)
            done = pr.get("done", max(0, cur - 1))
            for i in range(n):
                col = TEAL if i == cur - 1 else (STEP_DONE if i < max(done, cur - 1) else LINE)
                f.rr(x0 + i * (sw + gap), 106, sw, 6, r=3, fill=col, a=live)
        x = 1824
        acc = self.spec.get("label_accent")
        if acc:
            f.text(acc, x, 64, size=26, color=TEAL, w="B", a=live, anchor="r")
            x -= tw(acc, "B", 26) + 6
        if self.spec.get("label"):
            f.text(self.spec["label"], x, 66, size=24, color=TEXT3, a=live, anchor="r")
        if self.spec.get("foot"):
            f.text(self.spec["foot"], 96, 894, size=24, color=TEXT3, a=a, maxw=1728)


class Heading(Part):
    TYPE = "heading"
    TITLE = "段の見出し"
    DOC = ("場面の中の見出し 1 行（番号の丸 badge・続きの文 sub・上の罫線 rule を付けられる）。"
           "「1 段階目」の見出し、要点の一言、表の上の条件の書き添えなど")
    SCHEMA = {
        "text": {"type": "string", "minLength": 1},
        "size": dict(SIZE, description="文字の大きさ（既定 40）"),
        "bold": {"type": "boolean", "description": "太字（既定 true）"},
        "color": COLOR,
        "badge": {"type": "integer", "minimum": 0, "maximum": 99, "description": "左に番号の丸（段の見出し）"},
        "sub": {"type": "string", "description": "見出しの右に続ける文（薄い色、30）"},
        "align": {"enum": ["left", "center", "right"]},
        "rule": {"type": "boolean", "description": "上に罫線（区切り）"},
        "height": {"type": "number", "minimum": 20},
    }
    REQUIRED = ("text",)
    MOTION_FIELDS = {"motion": TEXT_ENTER}
    DEFAULTS = {"motion": "fade-in"}

    @classmethod
    def natural_height(cls, spec):
        if "height" in spec:
            return spec["height"]
        size = spec.get("size", 40)
        return int(size * 1.4) + (24 if spec.get("rule") else 0) + (16 if spec.get("badge") else 0)

    def build(self):
        self.size = self.spec.get("size", 40)
        self.weight = "B" if self.spec.get("bold", True) else "R"
        self.color = color(self.spec.get("color"), TEXT)
        left = 72 if self.spec.get("badge") else 0
        sub_w = tw(self.spec["sub"], "R", 30) + 28 if self.spec.get("sub") else 0
        self.check_fits(self.spec["text"], self.size, self.weight, self.w - left - sub_w, "見出し")

    def draw(self, f, t):
        live = self.alive(t)
        t0 = self.cue.t
        y = self.y
        if self.spec.get("rule"):
            a, _, _ = self.appear(t, t0)
            f.rr(self.x, y, self.w, 2, r=0, fill=LINE, a=a * live)
            y += 24
        x = self.x
        if self.spec.get("badge"):
            a, dx, dy = self.appear(t, t0, 0, self.size)
            f.badge(self.spec["badge"], x + 28 + dx, y + 28 + dy, a=a * live, dia=56)
            x += 72
            y += 4
        align = self.spec.get("align", "left")
        anchor = {"left": "l", "center": "c", "right": "r"}[align]
        tx = {"l": x, "c": self.x + self.w / 2, "r": self.x + self.w}[anchor]
        text_line(f, self, self.spec["text"], tx, y, size=self.size, color_=self.color, weight=self.weight, a=live,
                  t=t, t0=t0, anchor=anchor)
        if self.spec.get("sub") and anchor == "l":
            a, dx, dy = self.appear(t, t0, 1, 30)
            f.text(self.spec["sub"], x + tw(self.spec["text"], self.weight, self.size) + 28 + dx,
                   y + (self.size - 30) * 0.6 + dy, size=30, color=TEXT2, a=a * live, maxw=self.x + self.w)


class Title(Part):
    TYPE = "title"
    TITLE = "中央の題"
    DOC = "画面の中央に、大きさの違う行を縦に並べる（導入・区切り・終わりの一枚）。行ごとにきっかけを付けられる"
    SCHEMA = {
        "lines": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["text"],
            "properties": {"text": {"type": "string", "minLength": 1}, "size": SIZE, "color": COLOR,
                           "bold": {"type": "boolean"}, "at": {"type": "string", "minLength": 1},
                           "sentence": {"type": "integer", "minimum": 1}}}},
        "height": {"type": "number", "minimum": 40},
        "show": {"enum": ["each", "all"]},
    }
    REQUIRED = ("lines",)
    MOTION_FIELDS = {"motion": TEXT_ENTER}
    DEFAULTS = {"motion": "fade-in"}
    ITEMS = "lines"
    HEIGHT = 520

    def build(self):
        self.rows = []
        for ln in self.items:
            size = ln.get("size", 56)
            weight = "B" if ln.get("bold", size >= 56) else "R"
            self.check_fits(ln["text"], size, weight, self.w, "題")
            self.rows.append((ln["text"], size, weight, color(ln.get("color"), TEXT)))
        total = sum(int(s * 1.5) for _, s, _, _ in self.rows)
        if total > self.h + 0.5:
            from ..engine import LayoutError
            raise LayoutError(f"題の行が枠に入りません（高さ {total}px ＞ {self.h:.0f}px）")
        self.top = self.y + (self.h - total) / 2

    def draw(self, f, t):
        y = self.top
        live = self.alive(t)
        for i, (s, size, weight, col) in enumerate(self.rows):
            text_line(f, self, s, W / 2 if self.w == 1728 and self.x == 96 else self.x + self.w / 2, y + size * 0.2,
                      size=size, color_=col, weight=weight, a=live, t=t, t0=self.item_start(i), anchor="c",
                      i=i if self.show_all or self.cues[i] is None else 0)
            y += int(size * 1.5)


PARTS = [Header, Heading, Title]
