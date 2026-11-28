# -*- coding: utf-8 -*-
"""要点の部品: callout（要点の囲み・帯・札・面）と flow（札・箱を矢印でつなぐ流れ）。"""
from __future__ import annotations

from .. import motion as mo
from ..engine import (AMBER, CHIP_FILL, CORAL, LINE, PANEL, PANEL2, PILL_FILL, TEAL, TEXT, TEXT2, Frame, LayoutError,
                      tw, with_alpha, wrap_text)
from .base import COLOR, DIM, ITEM_CUE, KEEP, LINES, SHOW, SIZE, UNTIL, Part, as_lines, color

STYLES = {
    "box": "幅いっぱいの囲み（AMBER の枠、文字は中央）",
    "band": "左に色の帯の付いた帯（文字は左。右に添え書き more）",
    "pill": "角の丸い札（中央。arrow で矢印）",
    "panel": "TEAL の枠の面（左上に題。中身はほかの部品を box で重ねる）",
}


class Callout(Part):
    TYPE = "callout"
    TITLE = "要点の囲み・帯"
    DOC = ("要点の一言を囲む（style: " + "／".join(f"{k} {v}" for k, v in STYLES.items()) + "）。"
           "texts で同じ場所の文を読み上げの順に入れ替え（見本帳 26 fadethrough）、mark で語句にマーカー（T13）")
    SCHEMA = {
        "text": LINES,
        "texts": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["text"],
            "properties": dict(ITEM_CUE, text=LINES)},
            "description": "同じ場所で入れ替わる文（読み上げの順）"},
        "title": {"type": "string", "description": "panel の題"},
        "style": {"enum": list(STYLES)},
        "size": SIZE,
        "color": COLOR,
        "align": {"enum": ["left", "center", "right"]},
        "arrow": {"type": "boolean", "description": "pill の右に矢印"},
        "more": {"type": "object", "additionalProperties": False, "required": ["text"],
                 "properties": dict(ITEM_CUE, text={"type": "string"}), "description": "band の右の添え書き"},
        "mark": {"type": "object", "additionalProperties": False, "required": ["text"],
                 "properties": dict(ITEM_CUE, text={"type": "string", "minLength": 1}),
                 "description": "文の中の語句に引くマーカー（見本帳 T13）"},
        "focus": {"type": "object", "additionalProperties": False, "properties": dict(ITEM_CUE),
                  "description": "注目枠を付ける時間（at・sentence から until まで）"},
        "height": {"type": "number", "minimum": 30},
        "width": {"type": "number", "minimum": 60, "description": "pill の幅（既定は文字の幅から）"},
    }
    MOTION_FIELDS = {"motion": ("stagger", "fade-in", "slidein", "cut", "fade"), "switch": ("fadethrough", "cut")}
    DEFAULTS = {"motion": "stagger", "switch": "fadethrough"}
    ITEMS = "texts"
    HEIGHT = 120

    @classmethod
    def natural_height(cls, spec):
        if "height" in spec:
            return spec["height"]
        style = spec.get("style", "box")
        size = spec.get("size", 32 if style == "band" else 44)
        return {"box": int(size * 2.7), "band": 64 if size <= 34 else int(size * 2.2), "pill": int(size * 2.1),
                "panel": 236}[style]

    def build(self):
        sp = self.spec
        self.style = sp.get("style", "box")
        if not sp.get("text") and not sp.get("texts") and self.style != "panel":
            raise LayoutError(f"{self.ctx.where}: text か texts を書きます")
        self.size = sp.get("size", 32 if self.style == "band" else 44)
        self.color = color(sp.get("color"), TEAL if self.style == "panel" else AMBER)
        self.switch = self._motion("switch")
        self.more_cue = self.ctx.cue(sp["more"], ".more") if sp.get("more") else None
        self.mark_cue = self.ctx.cue(sp["mark"], ".mark") if sp.get("mark") else None
        if sp.get("mark") and sp["mark"]["text"] not in "".join(as_lines(sp.get("text") or "")):
            raise LayoutError(f"{self.ctx.where}.mark: 語句「{sp['mark']['text']}」が text にありません")
        f = sp.get("focus")
        if f:
            c = self.ctx.cue(f, ".focus")
            end = self.ctx.cue(f["until"], ".focus.until").t if "until" in f else (self.until.t if self.until else self.scene_end)
            self.focus_win = (c, end)
        else:
            self.focus_win = None
        if self.style == "pill":
            s = sp.get("text") if isinstance(sp.get("text"), str) else "".join(as_lines(sp.get("text") or ""))
            self.pw = sp.get("width", int(tw(s, "B", self.size)) + (190 if sp.get("arrow") else 72))
            if self.pw > self.w + 0.5:
                raise LayoutError(f"{self.ctx.where}: 札が枠に入りません（幅 {self.pw}px ＞ {self.w:.0f}px）: {s}")

    def cue_points(self):
        pts = super().cue_points()
        for c in (self.more_cue, self.mark_cue):
            if c is not None:
                pts.append((c, c.t + 1.0))
        if self.focus_win:
            pts.append((self.focus_win[0], self.focus_win[0].t + 0.3))
        return pts

    def _frame(self, f: Frame, a: float, dx: float, dy: float):
        x, y, w, h = self.x + dx, self.y + dy, self.w, self.h
        if self.style == "box":
            f.rr(x, y, w, h, r=16, fill=CHIP_FILL, outline=AMBER, ow=2, a=a)
        elif self.style == "band":
            f.rr(x, y, w, h, r=10, fill="#1b2a2f", outline=with_alpha(AMBER, 0.55), ow=2, a=a)
            f.rr(x, y, 10, h, r=4, fill=AMBER, a=a)
        elif self.style == "pill":
            x = x + (w - self.pw) / 2
            f.rr(x, y, self.pw, h, r=h // 2, fill=PILL_FILL, outline=AMBER, ow=2, a=a)
            w = self.pw
        else:
            f.rr(x, y, w, h, r=16, fill=PANEL2, outline=TEAL, ow=2, a=a)
            if self.spec.get("title"):
                f.text(self.spec["title"], x + 40, y + 26, size=40, color=TEAL, w="B", a=a, maxw=w - 80)
        return x, y, w, h

    def _text(self, f: Frame, t: float, v, box, a: float) -> None:
        x, y, w, h = box
        st = self.style
        align = self.spec.get("align", "left" if st == "band" else "center")
        pad = 32 if st == "band" else 48
        if st == "pill" and self.spec.get("arrow"):
            f.path([(x + w - 112, y + h / 2), (x + w - 50, y + h / 2)], color=AMBER, width=5, head=True, a=a)
            self.lines(f, v, x + 48, y, w - 190, h, size=self.size, color_=self.color, weight="B", a=a, align="l",
                       valign="c")
            return
        maxw = w - 2 * pad - (self._more_w() if st == "band" else 0)
        rows = list(v) if isinstance(v, list) else wrap_text(v, "B", self.size, maxw)
        if self.mark_cue is not None:   # マーカーは文字の下（見本帳 T13 は背景の帯）
            self._marker(f, t, rows, box, align, pad, a)
        self.lines(f, rows, x + pad, y, maxw, h, size=self.size, color_=self.color, weight="B", a=a,
                   align={"left": "l", "center": "c", "right": "r"}[align], valign="c")

    def _more_w(self) -> float:
        m = self.spec.get("more")
        return tw(m["text"], "R", 26) + 40 if m else 0.0

    def _marker(self, f, t, rows, box, align, pad, a):
        """見本帳 T13: 文字の高さの 58%〜92% に帯、幅 0→100%（1s cubic-bezier(.6,0,.3,1)）。"""
        m = mo.MOTIONS["marker"]
        p = m.progress(t, self.mark_cue.t, speed=self.speed)
        if p <= 0:
            return
        x, y, w, h = box
        phrase = self.spec["mark"]["text"]
        lh = int(self.size * 1.4)
        need = lh * (len(rows) - 1) + self.size
        y0 = y + (h - need) / 2
        for k, s in enumerate(rows):
            j = s.find(phrase)
            if j < 0:
                continue
            lw = tw(s, "B", self.size)
            lx = {"left": x + pad, "center": x + w / 2 - lw / 2, "right": x + w - pad - lw}[align]
            px = lx + tw(s[:j], "B", self.size)
            pw = tw(phrase, "B", self.size)
            b0, b1 = m.params["band"]
            top = y0 + k * lh - self.size * 0.12
            f.rr(px, top + self.size * 1.2 * b0, max(2, pw * p), self.size * 1.2 * (b1 - b0), r=3,
                 fill=with_alpha(CORAL, m.params["alpha"]), a=a)

    def draw(self, f, t):
        live = self.alive(t)
        a, dx, dy = self.appear(t, self.cue.t, 0, self.size, self.w)
        a *= live
        if a <= 0:
            return
        box = self._frame(f, a, dx, dy)
        if self.items:      # texts: 入れ替わる文（見本帳 26: 前の文は .09s で消え、次の文は .09s 後から .21s で出る）
            sw = self.switch
            for i, it in enumerate(self.items):
                t0 = self.cues[i].t if self.cues[i] else self.cue.t
                t1 = self.ends[i]
                if t < t0:
                    continue
                if sw is None or sw.id == "cut":
                    k = 1.0 if t < t1 or t1 >= self.scene_end else 0.0
                else:
                    k_in = 1.0 if i == 0 else mo.Motion("in", "26", "", "switch", sw.params["in_duration"], sw.easing,
                                                        delay=sw.duration).progress(t, t0, speed=self.speed)
                    k_out = sw.progress(t, t1, speed=self.speed) if t1 < self.scene_end else 0.0
                    k = min(k_in, 1.0 - k_out)
                if k > 0:
                    self._text(f, t, it["text"], box, a * k)
        elif self.spec.get("text"):
            self._text(f, t, self.spec["text"], box, a)
        more = self.spec.get("more")
        if more:
            k = self.enter.progress(t, self.more_cue.t, speed=self.speed) if self.enter else 1.0
            x, y, w, h = box
            f.text(more["text"], x + w - 28, y + (h - 26) / 2, size=26, color=TEXT, a=a * k, anchor="r")
        if self.focus_win:
            c, end = self.focus_win
            fm = mo.MOTIONS["roomhighlight"]
            on = min(fm.progress(t, c.t, speed=self.speed), 1 - fm.progress(t, end, speed=self.speed))
            if on > 0:
                x, y, w, h = box
                f.focus(x, y, w, h, r=16 if self.style != "band" else 10, a=on * live)


class Flow(Part):
    TYPE = "flow"
    TITLE = "流れ（札を矢印でつなぐ）"
    DOC = "札（pill）・箱（box）・ただの文字（plain）を横に並べ、矢印でつなぐ。読み上げの順に出し、読んでいる札を示す"
    SCHEMA = {
        "items": {"type": "array", "minItems": 1, "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False, "required": ["text"],
            "properties": dict(ITEM_CUE, text={"type": "string", "minLength": 1},
                               style={"enum": ["pill", "box", "plain"]}, color=COLOR)}},
        "arrows": {"type": "boolean", "description": "札の間に矢印（既定 true）"},
        "size": SIZE,
        "height": {"type": "number", "minimum": 30},
        "gap": {"type": "number", "minimum": 0, "description": "札の間（px、既定 70。矢印が入る）"},
        "align": {"enum": ["left", "center"]},
        "show": SHOW, "dim": DIM, "keep": KEEP,
    }
    REQUIRED = ("items",)
    MOTION_FIELDS = {"motion": ("stagger", "slidein", "fade-in", "cut"), "emphasis": ("roomhighlight", "underline", "none")}
    DEFAULTS = {"motion": "stagger", "emphasis": "roomhighlight"}
    ITEMS = "items"
    HEIGHT = 90

    @classmethod
    def natural_height(cls, spec):
        return spec.get("height", int(spec.get("size", 32) * 2.4))

    def build(self):
        self.size = self.spec.get("size", 32)
        arrows = self.spec.get("arrows", True)
        gap = self.spec.get("gap", 70 if arrows else 30)
        widths = []
        for it in self.items:
            st = it.get("style", "pill")
            weight = "R" if st == "plain" else "B"
            widths.append(int(tw(it["text"], weight, self.size)) + (0 if st == "plain" else 44))
        total = sum(widths) + gap * (len(widths) - 1)
        if total > self.w + 0.5:
            raise LayoutError(f"{self.ctx.where}: 流れが枠に入りません（幅 {total}px ＞ {self.w:.0f}px）")
        x = self.x if self.spec.get("align", "center") == "left" else self.x + (self.w - total) / 2
        self.boxes = []
        for wd in widths:
            self.boxes.append((x, self.y, wd, self.h))
            x += wd + gap
        self.gap = gap

    def draw(self, f, t):
        arrows = self.spec.get("arrows", True)
        for i, (it, box) in enumerate(zip(self.items, self.boxes)):
            a, dx, dy = self.item_alpha(t, i, self.size, box[2])
            if a <= 0:
                continue
            x, y, w, h = box[0] + dx, box[1] + dy, box[2], box[3]
            st = it.get("style", "pill")
            col = color(it.get("color"), TEXT2 if st == "plain" else TEXT)
            if st == "pill":
                f.rr(x, y, w, h, r=12, fill=PANEL2, outline=LINE, ow=2, a=a)
            elif st == "box":
                f.rr(x, y, w, h, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
            f.text(it["text"], x + (0 if st == "plain" else 22), y + (h - self.size) / 2 - 2, size=self.size, color=col,
                   w="R" if st == "plain" else "B", a=a)
            if arrows and i:
                px = self.boxes[i - 1][0] + self.boxes[i - 1][2]
                grow = mo.MOTIONS["underline"].progress(t, self.item_start(i), speed=self.speed)
                f.path([(px + 14, y + h / 2), (x - 14, y + h / 2)], color=TEAL, width=4, head=True, prog=grow, a=a)
            if st != "plain":
                self.emphasize(f, t, i, (x, y, w, h), a, r=12)


PARTS = [Callout, Flow]
