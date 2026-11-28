# -*- coding: utf-8 -*-
"""カード・手順の部品: cards（カードを読み上げ順に点灯）・steps（番号・印つきの並び）。"""
from __future__ import annotations

import math

from .. import motion as mo
from ..engine import (AMBER, LINE, PANEL, PILL_FILL, TAG_STYLE, TEXT, TEXT2, TEXT3, Frame, LayoutError, tag_size,
                      tw, wrap_text)
from .base import COLOR, DIM, ITEM_CUE, KEEP, LINES, SHOW, SIZE, Part, check_icon, color, grid

ENTER = ("stagger", "slidein", "fade-in", "cut", "fade")
EMPHASIS = ("roomhighlight", "fill", "underline", "none")
TAGS = {"type": "array", "items": {"enum": list(TAG_STYLE)}, "description": "区分の札（engine の TAG_STYLE）"}


def _rows(v, weight: str, size: int, maxw: float) -> list[str]:
    if isinstance(v, list):
        return list(v)
    return wrap_text(v, weight, size, maxw)


def _text_rows(f: Frame, rows: list[str], x: float, y: float, maxw: float, size: int, color_: str, weight: str,
               a: float, lh: int) -> float:
    for k, s in enumerate(rows):
        f.text(s, x, y + k * lh, size=size, color=color_, w=weight, a=a, maxw=maxw)
    return y + lh * (len(rows) - 1) + size


class Cards(Part):
    TYPE = "cards"
    TITLE = "カードを読み上げ順に点灯"
    DOC = ("カードを横に（columns: 1 で縦に）並べ、読み上げの順に現す・読んでいるカードを示す。"
           "番号の丸（numbered）、カードの間の矢印（arrows）、下の括弧と札（bracket）、カードの中の確かめの印（checks）")
    SCHEMA = {
        "items": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
            "type": "object", "additionalProperties": False,
            "properties": dict(ITEM_CUE, title=LINES, body=LINES,
                               label={"type": "string", "description": "題の上の小さな文（薄い色）"},
                               note={"anyOf": [LINES, {"type": "object", "additionalProperties": False,
                                                       "required": ["text"], "properties": dict(ITEM_CUE, text=LINES)}],
                                     "description": "強調の文（AMBER・太字）。{text, at, sentence} で自分のきっかけ"},
                               tags=TAGS, badge={"type": "integer", "minimum": 0, "maximum": 99},
                               checks={"type": "array", "items": {
                                   "type": "object", "additionalProperties": False, "required": ["text"],
                                   "properties": dict(ITEM_CUE, text=LINES)}})}},
        "columns": {"type": "integer", "minimum": 1, "maximum": 6, "description": "列の数（既定は項目の数、最大 4）"},
        "gap": {"type": "number", "minimum": 0, "description": "カードの間（px、既定 48）"},
        "row_gap": {"type": "number", "minimum": 0, "description": "行の間（px、既定 gap）"},
        "height": {"type": "number", "minimum": 40, "description": "カードの高さ（px、既定 220）"},
        "numbered": {"type": "boolean", "description": "左上に番号の丸（1 から）"},
        "arrows": {"type": "boolean", "description": "カードの間に矢印（横に並べたとき）"},
        "arrow_color": COLOR,
        "align": {"enum": ["top", "middle"], "description": "文の位置（middle: 番号の丸の下の残りの中央。段階のカード）"},
        "pad": {"type": "number", "minimum": 0, "maximum": 80, "description": "カードの内側の余白（px、既定 24）"},
        "title_size": SIZE, "body_size": SIZE, "body_color": COLOR,
        "bracket": {"type": "object", "additionalProperties": False, "required": ["text"],
                    "properties": dict(ITEM_CUE, text={"type": "string", "minLength": 1},
                                       sub={"type": "string", "description": "札の下の文"}),
                    "description": "カードの列の下の括弧と、まとめの札（AMBER）"},
        "show": SHOW, "dim": DIM, "keep": KEEP,
        "direction": {"enum": ["normal", "reverse"], "description": "slidein の向き（reverse で左から）"},
    }
    REQUIRED = ("items",)
    MOTION_FIELDS = {"motion": ENTER, "emphasis": EMPHASIS}
    DEFAULTS = {"motion": "stagger", "emphasis": "roomhighlight"}
    ITEMS = "items"

    @classmethod
    def natural_height(cls, spec):
        n = len(spec.get("items") or [])
        cols = min(spec.get("columns", min(n, 4)), max(1, n))
        rows = max(1, math.ceil(n / max(1, cols)))
        h = spec.get("height", 220)
        gap = spec.get("row_gap", spec.get("gap", 48))
        total = rows * h + (rows - 1) * gap
        if spec.get("bracket"):
            total += 26 + 34 + (60 if spec["bracket"].get("sub") else 0) + 40
        return total

    def build(self):
        n = len(self.items)
        self.cols = min(self.spec.get("columns", min(n, 4)), n)
        gap = self.spec.get("gap", 48)
        rows = math.ceil(n / self.cols)
        row_gap = self.spec.get("row_gap", gap)
        h = self.spec.get("height")
        if h is None:
            if "box" in self.spec:   # 置き場の高さから（括弧の分を除く）
                b = self.spec.get("bracket")
                bh = (26 + 34 + (60 if b.get("sub") else 0) + 40) if b else 0
                h = (self.h - bh - (rows - 1) * row_gap) / rows
            else:
                h = 220
        self.gap = gap
        self.boxes = grid(n, self.cols, (self.x, self.y, self.w, self.h), gap, row_gap, h)
        self.title_size = self.spec.get("title_size", 36)
        self.body_size = self.spec.get("body_size", 28)
        self.check_cues = []
        self.note_cues = []
        for i, it in enumerate(self.items):
            nt = it.get("note")
            self.note_cues.append(self.ctx.cue(nt, f".items[{i}].note")
                                  if isinstance(nt, dict) and ("at" in nt or "sentence" in nt) else None)
            cs = []
            for k, ck in enumerate(it.get("checks") or []):
                has = "at" in ck or "sentence" in ck
                cs.append(self.ctx.cue(ck, f".items[{i}].checks[{k}]") if has else None)
            self.check_cues.append(cs)
        b = self.spec.get("bracket")
        self.bracket_cue = self.ctx.cue(b, ".bracket") if b else None
        if b:
            self.bracket_line_t = (self.T.S(self.bracket_cue.sentence)
                                   if self.bracket_cue.phrase and self.bracket_cue.sentence else self.bracket_cue.t)

    def cue_points(self):
        pts = super().cue_points()
        for cs in self.check_cues + [[c] for c in self.note_cues]:
            pts += [(c, c.t + self.enter.end_sec(speed=self.speed)) for c in cs if c is not None]
        if self.bracket_cue is not None:
            pts.append((self.bracket_cue, self.bracket_cue.t + self.enter.end_sec(speed=self.speed)))
        return pts

    def _card(self, f: Frame, t: float, i: int, box, a: float) -> None:
        it = self.items[i]
        x, y, w, h = box
        pad = self.spec.get("pad", 24)
        f.rr(x, y, w, h, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
        inner = w - 2 * pad
        top = y + pad
        num = it.get("badge", i + 1 if self.spec.get("numbered") else None)
        if num:
            dia = 52 if self.title_size >= 44 else 48
            f.badge(num, x + 26 + dia / 2, y + 28 + dia / 2, a=a, dia=dia)
            top = y + 28 + dia + 16
        tx = x + pad
        if it.get("tags"):
            tsize = min(30, self.title_size)
            for kind in it["tags"]:
                tx += f.tag(kind, tx + 4, y + pad - 4, size=tsize, a=a) + 14
            tx += 4
            top = y + pad - 2
        blocks = []   # (行, 大きさ, 色, 太さ, 行の高さ, 濃さの掛け, 印)
        if it.get("label"):
            blocks.append(([it["label"]], 22, TEXT3, "R", 30, 1.0, "label"))
            top = y + pad
        ts = self.title_size
        if it.get("title"):
            blocks.append((_rows(it["title"], "B", ts, x + w - pad - tx), ts, TEXT, "B", int(round(ts * 1.26)), 1.0, None))
        bs = self.body_size
        if it.get("body"):
            blocks.append((_rows(it["body"], "R", bs, inner), bs, color(self.spec.get("body_color"), TEXT), "R",
                           int(bs * 1.4), 1.0, None))
        if it.get("note"):
            ns = bs + 2
            nt = it["note"]
            c = self.note_cues[i]
            na = self.enter.progress(t, c.t, speed=self.speed) if (c is not None and self.enter) else 1.0
            blocks.append((_rows(nt["text"] if isinstance(nt, dict) else nt, "B", ns, inner), ns, AMBER, "B",
                           int(ns * 1.4), na, None))
        for k, ck in enumerate(it.get("checks") or []):
            cs = bs - 1
            c = self.check_cues[i][k]
            ca = self.enter.progress(t, c.t, speed=self.speed) if (c is not None and self.enter) else 1.0
            blocks.append((_rows(ck["text"], "R", cs, inner - 46), cs, TEXT, "R", int(round(cs * 1.26)), ca, "check"))
        heights = [lh * (len(r) - 1) + s for r, s, _, _, lh, _, _ in blocks]
        need = sum(heights) + 16 * max(0, len(blocks) - 1)
        if self.spec.get("align") == "middle":
            top = top + max(0, (y + h - 20 - top - need) / 2)
        if top + need > y + h - pad + 6:
            raise LayoutError(f"カード {i + 1} の文字が入りません（文の下端 {top + need - y:.0f}px ＞ 書ける下端 "
                              f"{h - pad + 6:.0f}px、カードの高さ {h:.0f}px）。文を短くするか height を大きくする")
        yy = top
        first = True
        for (rows, size, col, weight, lh, mul, mark), hh in zip(blocks, heights):
            x0 = tx if first and it.get("tags") and mark != "label" else x + pad
            if mark == "check":
                check_icon(f, x0 + 18, yy + size * 0.55, a=a * mul, dia=30)
                _text_rows(f, rows, x0 + 48, yy, x + w - pad - x0 - 48, size, col, weight, a * mul, lh)
            else:
                _text_rows(f, rows, x0, yy, x + w - pad - x0, size, col, weight, a * mul, lh)
            yy += hh + (12 if mark == "label" else int(size * 0.6) if first and it.get("title") else 16)
            first = False

    def draw(self, f, t):
        for i, box in enumerate(self.boxes):
            a, dx, dy = self.item_alpha(t, i, w=box[2])
            if a <= 0:
                continue
            bx = (box[0] + dx, box[1] + dy, box[2], box[3])
            self._card(f, t, i, bx, a)
            self.emphasize(f, t, i, bx, a)
            if self.spec.get("arrows") and i % self.cols:
                m = 8 if self.gap <= 48 else 14
                ya = bx[1] + bx[3] / 2
                grow = mo.MOTIONS["underline"].progress(t, self.item_start(i), speed=self.speed)
                f.path([(bx[0] - self.gap + m, ya), (bx[0] - m - (2 if self.gap > 48 else 0), ya)],
                       color=color(self.spec.get("arrow_color"), TEXT2), width=5 if self.gap > 48 else 4, head=True,
                       prog=grow, a=a)
        if self.bracket_cue is not None:
            self._bracket(f, t)

    def _bracket(self, f: Frame, t: float) -> None:
        b = self.spec["bracket"]
        live = self.alive(t)
        bottom = max(y + h for _, y, _, h in self.boxes)
        x0, x1 = self.boxes[0][0], max(x + w for x, _, w, _ in self.boxes)
        yb = bottom + 26
        a1, _, _ = self.appear(t, self.bracket_line_t)
        f.path([(x0, yb), (x0, yb + 34), (x1, yb + 34), (x1, yb)], color=AMBER, width=3, a=a1 * live)
        a2, _, dy = self.appear(t, self.bracket_cue.t, 0, 40)
        wt = int(tw(b["text"], "B", 40)) + 72
        cx = (x0 + x1) / 2
        f.rr(cx - wt / 2, yb + 2 + dy, wt, 68, r=34, fill=PILL_FILL, outline=AMBER, ow=2, a=a2 * live)
        f.text(b["text"], cx, yb + 14 + dy, size=40, color=AMBER, w="B", a=a2 * live, anchor="c", maxw=x1 - x0)
        if b.get("sub"):
            f.text(b["sub"], cx, yb + 138 + dy, size=36, color=TEXT2, a=a2 * live, anchor="c", maxw=x1 - x0)


class Steps(Part):
    TYPE = "steps"
    TITLE = "手順の番号付きリスト"
    DOC = ("番号・印（check・cross・dot・arrow）の付いた項目を縦に（horizontal で横に）並べ、読み上げの順に出す。"
           "boxed で項目ごとに面を付ける。番号の丸は読み始めた項目だけ明るくする")
    SCHEMA = {
        "items": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
            "type": "object", "additionalProperties": False, "required": ["text"],
            "properties": dict(ITEM_CUE, text=LINES, sub=LINES, tags=TAGS)}},
        "marker": {"enum": ["number", "check", "cross", "dot", "arrow"], "description": "項目の頭の印（既定 number）"},
        "direction": {"enum": ["vertical", "horizontal"]},
        "boxed": {"type": "boolean", "description": "項目ごとに面（カード）を付ける"},
        "size": SIZE, "sub_size": SIZE,
        "row": {"type": "number", "minimum": 30, "description": "1 項目の高さ（px）"},
        "gap": {"type": "number", "minimum": 0},
        "width": {"type": "number", "minimum": 40, "description": "項目の幅（boxed のとき。既定は枠の幅）"},
        "show": SHOW, "dim": DIM, "keep": KEEP,
    }
    REQUIRED = ("items",)
    MOTION_FIELDS = {"motion": ("stagger", "slidein", "fade-in", "cut"), "emphasis": EMPHASIS}
    DEFAULTS = {"motion": "stagger", "emphasis": "roomhighlight"}
    ITEMS = "items"

    @classmethod
    def _row(cls, spec) -> float:
        size = spec.get("size", 34)
        extra = int(spec.get("sub_size", 26) * 1.5) if any(isinstance(i, dict) and i.get("sub") for i in spec.get("items") or []) else 0
        return spec.get("row", int(size * 2.2) + extra)

    @classmethod
    def natural_height(cls, spec):
        n = len(spec.get("items") or [])
        if spec.get("direction") == "horizontal":
            return spec.get("row", 120)
        return n * cls._row(spec) + (n - 1) * spec.get("gap", 18)

    def build(self):
        n = len(self.items)
        self.size = self.spec.get("size", 34)
        self.sub_size = self.spec.get("sub_size", 26)
        gap = self.spec.get("gap", 18)
        if self.spec.get("direction") == "horizontal":
            cw = (self.w - gap * (n - 1)) / n
            self.boxes = [(self.x + i * (cw + gap), self.y, cw, self.h) for i in range(n)]
        else:
            rh = self._row(self.spec)
            ww = self.spec.get("width", self.w)
            self.boxes = [(self.x, self.y + i * (rh + gap), ww, rh) for i in range(n)]

    def draw(self, f, t):
        marker = self.spec.get("marker", "number")
        boxed = self.spec.get("boxed", False)
        horiz = self.spec.get("direction") == "horizontal"
        for i, box in enumerate(self.boxes):
            it = self.items[i]
            a, dx, dy = self.item_alpha(t, i, self.size, box[2])
            if a <= 0:
                continue
            x, y, w, h = box[0] + dx, box[1] + dy, box[2], box[3]
            if boxed:
                f.rr(x, y, w, h, r=14, fill=PANEL, outline=LINE, ow=2, a=a)
            if horiz:
                cx, cy = x + w / 2, y + 30
                if i and marker in ("number", "dot"):
                    px = self.boxes[i - 1][0] + self.boxes[i - 1][2] / 2
                    f.rr(px + 34, cy - 1, cx - px - 68, 3, r=1, fill=LINE, a=a)
                self._marker(f, t, i, marker, cx, cy, a)
                self.lines(f, it["text"], x, y + 72, w, h - 72, size=self.size, color_=TEXT, weight="B", a=a, align="c")
            else:
                mx = x + (46 if boxed else 22)
                tx = x + (92 if boxed else 60)
                if it.get("tags"):
                    for kind in it["tags"]:
                        tx += f.tag(kind, tx, y + (h - tag_size(kind, 26)[1]) / 2 - 2, size=26, a=a) + 14
                rows = _rows(it["text"], "B", self.size, x + w - tx - 20)
                lh = int(self.size * 1.3)
                need = lh * (len(rows) - 1) + self.size
                sub_rows = _rows(it["sub"], "R", self.sub_size, x + w - tx - 20) if it.get("sub") else []
                sub_need = (int(self.sub_size * 1.4) * (len(sub_rows) - 1) + self.sub_size + 10) if sub_rows else 0
                if need + sub_need > h + 0.5:
                    raise LayoutError(f"項目 {i + 1} の文字が入りません（高さ {need + sub_need}px ＞ {h:.0f}px）")
                ty = y + (h - need - sub_need) / 2            # 文の塊を行の高さの中央に。印は 1 行目の高さに
                self._marker(f, t, i, marker, mx, ty + self.size * 0.55, a)
                _text_rows(f, rows, tx, ty, x + w - tx - 20, self.size, TEXT, "B", a, lh)
                if sub_rows:
                    _text_rows(f, sub_rows, tx, ty + need + 10, x + w - tx - 20, self.sub_size, TEXT2, "R", a,
                               int(self.sub_size * 1.4))
            self.emphasize(f, t, i, (x, y, w, h) if boxed else (x - 12, y - 8, w + 24, h + 16), a, r=14)

    def _marker(self, f: Frame, t: float, i: int, marker: str, cx: float, cy: float, a: float) -> None:
        if marker == "number":
            lit = self.read(t, i) >= 0.5 or self.cues[i] is None
            f.badge(i + 1, cx, cy, a=a, dia=44, on=lit)
        else:
            check_icon(f, cx, cy, a=a, dia=34, kind=marker)


PARTS = [Cards, Steps]
