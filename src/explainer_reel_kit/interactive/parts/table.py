# -*- coding: utf-8 -*-
"""表の部品: table（行・列は見出しの文字で指定する。読み上げに合わせて行・セルを出し、行・列を示す）。

theme: paper で、明るい紙面の表（資料の抜き書き。上に題の帯、下に注記）。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from ..engine import (DOC_BG, DOC_EDGE, DOC_HEAD, DOC_LINE, DOC_SUB, DOC_TINT_COL, DOC_TINT_HEAD, DOC_TINT_MARK, FN,
                      INK, PANEL, PANEL2, TEXT, TEXT2, LayoutError, rgba)
from .base import COLOR, DIM, ITEM_CUE, KEEP, SHOW, SIZE, UNTIL, Part, color
from .legacy import Table as Cells


def _mk_grid(colw, rowh, head_rows, tint_col):
    """明るい面の表の罫線と塗り（1 枚の部品）。"""
    w, h = int(sum(colw)), int(sum(rowh))
    im = Image.new("RGBA", (w + 2, h + 2), rgba(DOC_BG))
    d = ImageDraw.Draw(im)
    hh = int(sum(rowh[:head_rows]))
    if head_rows:
        d.rectangle((0, 0, w, hh), fill=rgba(DOC_TINT_HEAD))
    d.rectangle((0, hh, int(colw[0]), h), fill=rgba(DOC_TINT_COL))
    if tint_col is not None:
        x = int(sum(colw[:tint_col]))
        d.rectangle((x, hh, x + int(colw[tint_col]), h), fill=rgba(DOC_TINT_MARK))
    x = 0.0
    for cw in list(colw) + [0]:
        d.line((int(x), 0, int(x), h), fill=rgba(DOC_LINE), width=1)
        x += cw
    y = 0.0
    for rh in list(rowh) + [0]:
        d.line((0, int(y), w, int(y)), fill=rgba(DOC_LINE), width=1)
        y += rh
    return im


FN["er_table_grid"] = _mk_grid

CELL = {"anyOf": [{"type": "string"},
                  {"type": "object", "additionalProperties": False, "required": ["text"],
                   "properties": dict(ITEM_CUE, text={"anyOf": [{"type": "string"},
                                                                 {"type": "array", "items": {"type": "string"}}]},
                                      color=COLOR, size=SIZE, bold={"type": "boolean"})}]}
ROW = {"anyOf": [
    {"type": "object", "additionalProperties": False, "required": ["name"],
     "properties": dict(ITEM_CUE, name={"type": "string", "minLength": 1},
                        cells={"type": "object", "additionalProperties": CELL,
                               "description": "列の見出し → セルの文字（または {text, at, sentence, color, size}）"})},
    {"type": "array", "items": {"type": "string"}, "minItems": 1,
     "description": "[行の見出し, 2 列目, 3 列目, …]（きっかけの要らない行）"}]}


class TablePart(Part):
    TYPE = "table"
    TITLE = "表の行・列の強調"
    DOC = ("表。列は columns の見出しの文字、行は rows の name（1 列目の文字）で指定する（番号では指定しない）。"
           "行は自分のきっかけで現れ、セルは自分のきっかけで書き足す。読んでいる行を示し、highlights で列・セルも示せる")
    SCHEMA = {
        "columns": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
                    "description": "列の見出し（左から）。1 列目は行の見出しの列"},
        "widths": {"type": "array", "items": {"type": "number", "exclusiveMinimum": 0},
                   "description": "列の幅（px、columns と同じ数）。無ければ等分"},
        "rows": {"type": "array", "minItems": 1, "items": ROW},
        "header": {"type": "boolean", "description": "見出しの行を描く（既定 true）"},
        "header_height": {"type": "number", "minimum": 16},
        "row_height": {"type": "number", "minimum": 16, "description": "行の高さ（px、既定 150。paper は 34）"},
        "size": dict(SIZE, description="セルの文字の大きさ（既定 32。paper は 21）"),
        "name_size": dict(SIZE, description="行の見出しの文字の大きさ（既定 34）"),
        "header_size": SIZE,
        "theme": {"enum": ["dark", "paper"], "description": "paper: 明るい紙面（資料の抜き書き）"},
        "title": {"type": "string", "description": "paper の上の題の帯"},
        "note": {"type": "string", "description": "paper の下の注記"},
        "tint_column": {"type": "string", "description": "paper で色を付ける列（列の見出し）"},
        "highlights": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": dict(ITEM_CUE, row={"type": "string"}, col={"type": "string"})},
            "description": "列・セル・行を示す時間（row・col は見出しの文字）"},
        "show": SHOW, "dim": DIM, "keep": KEEP,
    }
    REQUIRED = ("columns", "rows")
    MOTION_FIELDS = {"motion": ("stagger", "fade-in", "cut", "fade"), "emphasis": ("roomhighlight", "fill", "underline", "none")}
    DEFAULTS = {"motion": "stagger", "emphasis": "roomhighlight"}
    ITEMS = "rows"

    @classmethod
    def natural_height(cls, spec):
        if "height" in spec:
            return spec["height"]
        paper = spec.get("theme") == "paper"
        rh = spec.get("row_height", 34 if paper else 150)
        hh = spec.get("header_height", rh if paper else 80) if spec.get("header", True) else 0
        body = hh + rh * len(spec.get("rows") or [])
        return body + (56 + 40 if paper else 0) + (30 if paper and spec.get("note") else 0)

    def _items(self, raw):
        cols = self.spec["columns"]
        norm = []
        for i, r in enumerate(raw):
            if isinstance(r, list):
                if len(r) > len(cols):
                    raise LayoutError(f"{self.ctx.where}.rows[{i}]: 列が {len(cols)} なのに {len(r)} 個あります")
                norm.append({"name": r[0], "cells": dict(zip(cols[1:], r[1:]))})
            else:
                norm.append(r)
        super()._items(norm)

    def build(self):
        sp = self.spec
        cols = sp["columns"]
        self.paper = sp.get("theme") == "paper"
        widths = sp.get("widths")
        inner_x, inner_y, inner_w = self.x, self.y, self.w
        if self.paper:
            inner_x, inner_y, inner_w = self.x + 16, self.y + 56, self.w - 32
        if widths is None:
            widths = [inner_w / len(cols)] * len(cols)
        if len(widths) != len(cols):
            raise LayoutError(f"{self.ctx.where}: 列の見出しの数（{len(cols)}）と列の幅の数（{len(widths)}）が違います")
        rh = sp.get("row_height", 34 if self.paper else 150)
        self.has_header = sp.get("header", True)
        hh = sp.get("header_height", rh if self.paper else 80)
        names = [r["name"] for r in self.items]
        rows = (["見出し"] if self.has_header else []) + names
        if self.has_header and "見出し" in names:
            rows[0] = "\0見出し"
        heights = ([hh] if self.has_header else []) + [rh] * len(names)
        self.tb = Cells(inner_x, inner_y, widths, heights, cols=list(cols), rows=rows)
        self.head = rows[0] if self.has_header else None
        self.size = sp.get("size", 21 if self.paper else 32)
        self.name_size = sp.get("name_size", self.size if self.paper else 34)
        self.header_size = sp.get("header_size", self.size if self.paper else 30)
        for i, r in enumerate(self.items):       # 列の見出しの確かめ（知らない列は描く前に止める）
            for c in (r.get("cells") or {}):
                if c not in cols:
                    raise LayoutError(f"{self.ctx.where}.rows[{i}]: 列「{c}」はありません（列: {list(cols)}）")
        self.cell_cues = {}
        for i, r in enumerate(self.items):
            for c, v in (r.get("cells") or {}).items():
                if isinstance(v, dict) and ("at" in v or "sentence" in v):
                    self.cell_cues[(i, c)] = self.ctx.cue(v, f".rows[{i}].cells.{c}")
        self.hl = []
        for k, h in enumerate(sp.get("highlights") or []):
            for key in ("row", "col"):
                if key in h:
                    (self.tb._ri if key == "row" else self.tb._ci)(h[key])
            c = self.ctx.cue(h, f".highlights[{k}]")
            end = self.ctx.cue(h["until"], f".highlights[{k}].until").t if "until" in h else None
            self.hl.append((h, c, end))
        for k, (h, c, end) in enumerate(self.hl):
            if end is None:
                later = [c2.t for _, c2, _ in self.hl[k + 1:] if c2.t > c.t]
                self.hl[k] = (h, c, later[0] if later else (self.until.t if self.until else self.scene_end))
        if self.paper:
            from ..engine import tw
            if sp.get("title") and tw(sp["title"], "B", 26) > self.w - 36:
                raise LayoutError(f"{self.ctx.where}: 表の題が入りません: {sp['title']}")
        self.tint = cols.index(sp["tint_column"]) if sp.get("tint_column") in cols else None

    def cue_points(self):
        pts = super().cue_points()
        pts += [(c, c.t + self.enter.end_sec(speed=self.speed)) for c in self.cell_cues.values()]
        pts += [(c, c.t + 0.3) for _, c, _ in self.hl]
        return pts

    def _cell(self, f, row: str, col: str, v, a: float, *, size: int, weight: str, color_: str, fill, align: str):
        if self.paper:
            x, y, cw, ch = self.tb.cell(row, col)
            rows = [v] if isinstance(v, str) else list(v)
            for k, s in enumerate(rows):
                ty = y + (ch - size * len(rows) - 4 * (len(rows) - 1)) / 2 - 1 + k * (size + 4)
                if align == "l":
                    f.text(s, x + 10, ty, size=size, color=INK, w=weight, a=a, maxw=cw - 14)
                else:
                    f.text(s, x + cw / 2, ty, size=size, color=INK, w=weight, a=a, anchor="c", maxw=cw - 8)
            return
        self.tb.draw_cell(f, row, col, v, a=a, size=size, w=weight, color=color_, fill=fill, align=align)

    def draw(self, f, t):
        sp = self.spec
        cols = sp["columns"]
        live = self.alive(t)
        a0, _, _ = self.appear(t, self.cue.t)
        a0 *= live
        if a0 <= 0 and not any(c is not None for c in self.cues):
            return
        if self.paper:
            x, y, w, h = self.x, self.y, self.w, self.h
            f.rr(x, y, w, h, r=8, fill=DOC_BG, outline=DOC_EDGE, ow=2, a=a0)
            f.rr(x, y, w, 46, r=8, fill=DOC_HEAD, a=a0)
            f.rr(x, y + 30, w, 16, r=0, fill=DOC_HEAD, a=a0)
            if sp.get("title"):
                f.text(sp["title"], x + 18, y + 10, size=26, color="#ffffff", w="B", a=a0)
            gx, gy, _, _ = self.tb.box()
            f.fn("er_table_grid", gx, gy, tuple(self.tb.colw), tuple(self.tb.rowh), 1 if self.has_header else 0,
                 self.tint, a=a0)
            if sp.get("note"):
                f.text(sp["note"], gx, gy + sum(self.tb.rowh) + 12, size=18, color=DOC_SUB, a=a0, maxw=w - 32)
        if self.has_header:
            for c in cols:
                self._cell(f, self.head, c, c, a0, size=self.header_size, weight="B", color_=TEXT2, fill=PANEL2,
                           align="c" if (c != cols[0] or not self.paper) else "c")
        for i, r in enumerate(self.items):
            a, _, _ = self.item_alpha(t, i, self.size)
            if a <= 0:
                continue
            name = r["name"]
            self._cell(f, name, cols[0], name, a, size=self.name_size, weight="B", color_=TEXT, fill=PANEL,
                       align="l" if self.paper else "c")
            for c, v in (r.get("cells") or {}).items():
                spec = v if isinstance(v, dict) else {"text": v}
                cue = self.cell_cues.get((i, c))
                k = a * (self.enter.progress(t, cue.t, speed=self.speed) if (cue is not None and self.enter) else 1.0)
                if k <= 0:
                    continue
                self._cell(f, name, c, spec["text"], k, size=spec.get("size", self.size),
                           weight="B" if spec.get("bold", not self.paper) else "R",
                           color_=color(spec.get("color"), TEXT), fill=PANEL, align="c")
            self.emphasize(f, t, i, self.tb.row(name), a, r=8)
        for h, c, end in self.hl:
            from .. import motion as mo
            m = self.emph or mo.MOTIONS["roomhighlight"]
            on = min(m.progress(t, c.t, speed=self.speed), 1 - m.progress(t, end, speed=self.speed)) * live
            if on <= 0:
                continue
            if "row" in h and "col" in h:
                box = self.tb.cell(h["row"], h["col"])
            elif "col" in h:
                box = self.tb.col(h["col"], self.tb.rows[1] if self.has_header and len(self.tb.rows) > 1 else None)
            else:
                box = self.tb.row(h["row"])
            f.focus(*box, r=8, a=on)


PARTS = [TablePart]
