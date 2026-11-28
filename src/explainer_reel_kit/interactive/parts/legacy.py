# -*- coding: utf-8 -*-
"""場面コードの部品（表の行番号の取り違え・文字のはみ出しを仕組みで防ぐもの。Python の場面コードから使う）。

- ``Table``: 表のセルの位置だけを持つ。行・列は**見出しの文字で指定**する（番号で指定して 1 行ずれるのを防ぐ。4 章の 4）
- ``card_text``: カードの中に文字を書く。入らなければ LayoutError（4 章の 5）
"""
from __future__ import annotations

from ..engine import LINE, PANEL, TEXT, Frame, LayoutError, tw


class Table:
    """セルの位置だけを持つ表。描画・強調は場面の側で、このセル位置を使って行う。

    ``Table(x, y, colw=[…], rowh=[…], cols=['ガラス', '室内側の表面', …], rows=['見出し', '1 枚のガラス', …])``
    ``tb.cell('1 枚のガラス', '室内側の表面')`` / ``tb.col('室内側の表面')`` / ``tb.row('1 枚のガラス')`` は (x, y, w, h)。
    番号は受け付けない（例は examples/scenes/window-condensation/s03.py）。
    """

    def __init__(self, x: float, y: float, colw: list[float], rowh: list[float], *, cols: list[str], rows: list[str]):
        if len(cols) != len(colw):
            raise LayoutError(f'列の見出しの数（{len(cols)}）と列の幅の数（{len(colw)}）が違います')
        if len(rows) != len(rowh):
            raise LayoutError(f'行の見出しの数（{len(rows)}）と行の高さの数（{len(rowh)}）が違います')
        for kind, names in (('列', cols), ('行', rows)):
            dup = sorted({n for n in names if names.count(n) > 1})
            if dup:
                raise LayoutError(f'{kind}の見出しが重複しています: {dup}（見出しの文字で指定するため、重ならない名前にする）')
        self.cols, self.rows = list(cols), list(rows)
        self.colw, self.rowh = list(colw), list(rowh)
        self.xs = [x]
        for w_ in colw:
            self.xs.append(self.xs[-1] + w_)
        self.ys = [y]
        for h_ in rowh:
            self.ys.append(self.ys[-1] + h_)

    def _ci(self, col: str) -> int:
        if not isinstance(col, str):
            raise LayoutError(f'列は見出しの文字で指定してください（番号 {col!r} は使えません）')
        try:
            return self.cols.index(col)
        except ValueError:
            raise LayoutError(f'列「{col}」はありません（列: {self.cols}）') from None

    def _ri(self, row: str) -> int:
        if not isinstance(row, str):
            raise LayoutError(f'行は見出しの文字で指定してください（番号 {row!r} は使えません）')
        try:
            return self.rows.index(row)
        except ValueError:
            raise LayoutError(f'行「{row}」はありません（行: {self.rows}）') from None

    def cell(self, row: str, col: str):
        r, c = self._ri(row), self._ci(col)
        return self.xs[c], self.ys[r], self.colw[c], self.rowh[r]

    def col(self, col: str, from_row: str | None = None):
        c = self._ci(col)
        r0 = self._ri(from_row) if from_row is not None else 0
        return self.xs[c], self.ys[r0], self.colw[c], self.ys[-1] - self.ys[r0]

    def row(self, row: str, from_col: str | None = None):
        r = self._ri(row)
        c0 = self._ci(from_col) if from_col is not None else 0
        return self.xs[c0], self.ys[r], self.xs[-1] - self.xs[c0], self.rowh[r]

    def box(self):
        return self.xs[0], self.ys[0], self.xs[-1] - self.xs[0], self.ys[-1] - self.ys[0]

    def draw_cell(self, f: Frame, row: str, col: str, text, a: float = 1.0, size: int = 28, w: str = 'R',
                  color: str = TEXT, fill: str | None = PANEL, align: str = 'c', lh: int | None = None, pad: int = 22):
        """セルに文字を書く（text は文字列か行の並び）。セルに入らなければ LayoutError。"""
        x, y, cw, ch = self.cell(row, col)
        if fill:
            f.rr(x + 2, y + 2, cw - 4, ch - 4, r=6, fill=fill, a=a)
        rows = [text] if isinstance(text, str) else list(text)
        lh = lh or int(size * 1.32)
        need = lh * (len(rows) - 1) + size
        if need > ch - 4:
            raise LayoutError(f'表のセル（{row} × {col}）に {len(rows)} 行が入りません（高さ {need}px ＞ {ch - 4}px）')
        y0 = y + (ch - lh * len(rows)) / 2 + (lh - size) / 2
        for i, s in enumerate(rows):
            if align == 'c':
                f.text(s, x + cw / 2, y0 + i * lh, size=size, w=w, color=color, a=a, anchor='c', maxw=cw - 2 * pad)
            else:
                f.text(s, x + pad, y0 + i * lh, size=size, w=w, color=color, a=a, maxw=cw - 2 * pad)

    def veil_cells(self, f: Frame, lit, amount: float = 0.6, from_row: str | None = None):
        """lit(行の見出し, 列の見出し) → 0..1（1 で明るいまま）。それ以外のセルを沈める。"""
        r0 = self._ri(from_row) if from_row is not None else 0
        for r in range(r0, len(self.rowh)):
            for c in range(len(self.colw)):
                v = (1 - lit(self.rows[r], self.cols[c])) * amount
                if v > 0.004:
                    x, y, cw, ch = self.xs[c], self.ys[r], self.colw[c], self.rowh[r]
                    f.veil(x + 1, y + 1, cw - 2, ch - 2, v, r=6)


def card_text(f: Frame, x: float, y: float, w: float, h: float, title: str | None = None, body: str | None = None,
              a: float = 1.0, title_size: int = 34, body_size: int = 28, pad: int = 24, fill: str = PANEL):
    """カード（角丸の面）に見出しと本文を書く。見出しが 1 行に入らない・本文が枠に入らなければ LayoutError。"""
    f.rr(x, y, w, h, r=16, fill=fill, outline=LINE, ow=2, a=a)
    inner = w - 2 * pad
    yy = y + pad
    if title:
        if tw(title, 'B', title_size) > inner:
            raise LayoutError(f'カードの見出しが 1 行に入りません: {title}')
        f.text(title, x + pad, yy, size=title_size, w='B', a=a, maxw=inner)
        yy += int(title_size * 1.6)
    if body:
        f.text_box(body, x + pad, yy, inner, y + h - pad - yy, size=body_size, a=a)
