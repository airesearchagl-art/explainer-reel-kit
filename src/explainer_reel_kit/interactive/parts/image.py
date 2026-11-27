# -*- coding: utf-8 -*-
"""画像の部品: image（画像を並べる・重ねて切り替える・注釈）と compare（比較の左右）。

画像の座標（注釈の位置）は、元の画像の画素で書く（切り抜き crop を書いたときも元の画像の画素）。
"""
from __future__ import annotations

from .. import motion as mo
from ..engine import (AMBER, LINE, PANEL, PAPER, TEXT, TEXT2, Frame, LayoutError, asset_size, tw, with_alpha)
from .base import COLOR, DIM, ITEM_CUE, KEEP, LINES, SHOW, Part, check_icon, color

IMG_PROPS = {
    "src": {"type": "string", "minLength": 1, "description": "静止画（scenes\\assets\\ などから探す）"},
    "crop": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 4, "maxItems": 4,
             "description": "切り抜き [左, 上, 右, 下]（元の画像の画素）"},
    "mode": {"enum": ["auto", "thick", "thick2", "paper", "ink", "thick paper", "thick2 paper", ""],
             "description": "細線の太らせ方（engine.img の mode。既定 auto）"},
    "paper": {"type": "boolean", "description": "明るい紙の面に載せる（図面）"},
    "caption": {"type": "string"},
}
ANNOT = {
    "type": "object", "additionalProperties": False, "required": ["shape"],
    "properties": dict(ITEM_CUE, shape={"enum": ["box", "circle", "point", "label"]},
                       rect={"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
                             "description": "box: [x, y, 幅, 高さ]（元の画像の画素）"},
                       xy={"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                           "description": "circle・point・label の中心（元の画像の画素）"},
                       size={"type": "number", "minimum": 4, "description": "circle の直径（画面の px）"},
                       text={"type": "string"}, image={"type": "integer", "minimum": 1,
                                                        "description": "何枚目の画像か（既定 1）"},
                       dx={"type": "number"}, dy={"type": "number"}),
    "description": "注釈: box（枠）・circle（丸）・point（注目点の脈動 28 hotspot）・label（引き出し線の注記 T10 callout）",
}


def fit(src_w: float, src_h: float, box) -> tuple[float, float, float, float]:
    x, y, w, h = box
    k = min(w / src_w, h / src_h)
    ww, hh = src_w * k, src_h * k
    return x + (w - ww) / 2, y + (h - hh) / 2, ww, hh


class Image_(Part):
    TYPE = "image"
    TITLE = "画像と注釈"
    DOC = ("画像を横に並べる（stack: true で同じ場所に重ね、きっかけで切り替える。見本帳 V02 fade）。"
           "注釈（annotations）は元の画像の画素で位置を書き、読み上げに合わせて出す")
    SCHEMA = {
        "images": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["src"],
            "properties": dict(ITEM_CUE, **IMG_PROPS)}},
        "stack": {"type": "boolean", "description": "同じ場所に重ねて、きっかけで切り替える"},
        "gap": {"type": "number", "minimum": 0},
        "annotations": {"type": "array", "items": ANNOT},
        "height": {"type": "number", "minimum": 40},
        "show": SHOW, "dim": DIM, "keep": KEEP,
    }
    REQUIRED = ("images",)
    MOTION_FIELDS = {"motion": ("clipreveal", "wipe", "fade", "stagger", "cut"),
                     "emphasis": ("roomhighlight", "none")}
    DEFAULTS = {"motion": "clipreveal", "emphasis": "roomhighlight"}
    ITEMS = "images"
    HEIGHT = 600

    def build(self):
        n = len(self.items)
        gap = self.spec.get("gap", 24)
        stack = self.spec.get("stack", False)
        cap = 50 if any(it.get("caption") for it in self.items) else 0
        if stack:
            cells = [(self.x, self.y, self.w, self.h - cap)] * n
        else:
            cw = (self.w - gap * (n - 1)) / n
            cells = [(self.x + i * (cw + gap), self.y, cw, self.h - cap) for i in range(n)]
        self.cells = cells
        self.places = []
        for it, cell in zip(self.items, cells):
            sw, sh = asset_size(it["src"])
            crop = it.get("crop")
            if crop:
                l, tp, r, b = crop
                if not (0 <= l < r <= sw and 0 <= tp < b <= sh):
                    raise LayoutError(f"{self.ctx.where}: 切り抜き {crop} が画像 {it['src']}（{sw}×{sh}）の外です")
                sw, sh = r - l, b - tp
            pad = 3 if it.get("paper") else 0
            x, y, w, h = fit(sw, sh, (cell[0] + pad, cell[1] + pad, cell[2] - 2 * pad, cell[3] - 2 * pad))
            self.places.append((x, y, w, h, (crop[0], crop[1]) if crop else (0, 0), w / sw))
        self.notes = []
        for k, an in enumerate(self.spec.get("annotations") or []):
            idx = an.get("image", 1) - 1
            if idx >= n:
                raise LayoutError(f"{self.ctx.where}.annotations[{k}]: {idx + 1} 枚目の画像はありません")
            if an["shape"] == "box" and "rect" not in an:
                raise LayoutError(f"{self.ctx.where}.annotations[{k}]: box は rect を書きます")
            if an["shape"] != "box" and "xy" not in an:
                raise LayoutError(f"{self.ctx.where}.annotations[{k}]: {an['shape']} は xy を書きます")
            c = self.ctx.cue(an, f".annotations[{k}]") if ("at" in an or "sentence" in an) else self.cue
            end = self.ctx.cue(an["until"], f".annotations[{k}].until").t if "until" in an else None
            self.notes.append((an, c, end))

    def to_screen(self, idx: int, px: float, py: float) -> tuple[float, float]:
        x, y, w, h, (ox, oy), k = self.places[idx]
        return x + (px - ox) * k, y + (py - oy) * k

    def cue_points(self):
        pts = super().cue_points()
        pts += [(c, c.t + 1.0) for _, c, _ in self.notes if c is not self.cue]
        return pts

    def _img(self, f: Frame, t: float, i: int, a: float) -> None:
        it = self.items[i]
        x, y, w, h, _, _ = self.places[i]
        cell = self.cells[i]
        m = self.enter
        crop = it.get("crop")
        mode = it.get("mode", "auto")
        if it.get("paper"):
            f.rr(cell[0], cell[1], cell[2], cell[3], r=8, fill=PAPER, a=a)
        if m is not None and m.id in ("clipreveal", "wipe") and not self.spec.get("stack"):
            p = m.progress(t, self.item_start(i), speed=self.speed)
            if p < 1:   # 左から見せる（切り抜きを広げる）。clipreveal は少し引きながら（1.15 → 1、1.4s）
                sw, sh = asset_size(it["src"])
                l, tp, r, b = crop or (0, 0, sw, sh)
                rr = l + max(1, int((r - l) * p))
                ww = max(1, int(w * (rr - l) / (r - l)))
                if ww >= 2:
                    f.img(it["src"], x, y, ww, int(h), crop=(l, tp, rr, b), mode=mode, a=a)
                return
        f.img(it["src"], x, y, int(w), int(h), crop=tuple(crop) if crop else None, mode=mode, a=a)

    def draw(self, f, t):
        stack = self.spec.get("stack", False)
        live = self.alive(t)
        for i, it in enumerate(self.items):
            if stack:
                t0 = self.item_start(i)
                if t < t0:
                    continue
                k = mo.MOTIONS["fade"].progress(t, t0, speed=self.speed) if i else self.appear(t, t0)[0]
                nxt = [self.item_start(j) for j in range(i + 1, len(self.items))]
                if nxt and t >= nxt[0] + mo.MOTIONS["fade"].duration / self.speed:
                    continue
                a = k * live
            else:
                a, _, _ = self.item_alpha(t, i)
            if a <= 0:
                continue
            self._img(f, t, i, a)
            cell = self.cells[i]
            if it.get("caption"):
                f.text(it["caption"], cell[0], cell[1] + cell[3] + 12, size=26, color=TEXT2, a=a, maxw=cell[2])
            if not stack:
                self.emphasize(f, t, i, cell, a, r=8)
        for an, c, end in self.notes:
            self._note(f, t, an, c, end, live)

    def _note(self, f, t, an, c, end, live):
        idx = an.get("image", 1) - 1
        if t < c.t:
            return
        fade = 1.0 if end is None else 1 - mo.MOTIONS["roomhighlight"].progress(t, end, speed=self.speed)
        if fade <= 0:
            return
        shape = an["shape"]
        if shape == "box":
            px, py, pw, ph = an["rect"]
            x0, y0 = self.to_screen(idx, px, py)
            x1, y1 = self.to_screen(idx, px + pw, py + ph)
            a = mo.MOTIONS["roomhighlight"].progress(t, c.t, speed=self.speed) * fade * live
            f.rr(x0, y0, x1 - x0, y1 - y0, r=6, fill=with_alpha(AMBER, 0.22), outline=AMBER, ow=3, a=a)
            if an.get("text"):
                f.text(an["text"], x0, y1 + 8, size=26, color=AMBER, w="B", a=a)
        elif shape == "circle":
            cx, cy = self.to_screen(idx, *an["xy"])
            a = mo.MOTIONS["roomhighlight"].progress(t, c.t, speed=self.speed) * fade * live
            f.circ(cx, cy, int(an.get("size", 120)), outline=AMBER, ow=5, a=a)
        elif shape == "point":
            cx, cy = self.to_screen(idx, *an["xy"])
            self.pulse(f, t, cx, cy, an.get("size", 28), c.t, fade * live)
        else:   # label: 見本帳 T10 引き出し線の注記（点 .3s → 線 .5s → 注記 .4s）
            m = mo.MOTIONS["callout"]
            cx, cy = self.to_screen(idx, *an["xy"])
            dx, dy = an.get("dx", 120), an.get("dy", -60)
            p_dot = m.progress(t, c.t, speed=self.speed)
            p_line = mo.sub_progress(m, "leader", t, c.t, self.speed)
            p_lab = mo.sub_progress(m, "label", t, c.t, self.speed)
            a = fade * live
            f.circ(cx, cy, 14, fill=AMBER, a=a * p_dot)
            ex, ey = cx + dx * p_line, cy + dy * p_line
            if p_line > 0:
                f.path([(cx, cy), (ex, ey)], color=AMBER, width=3, a=a)
            if p_lab > 0 and an.get("text"):
                s = an["text"]
                wd = tw(s, "B", 28) + 32
                lx = cx + dx + (8 if dx >= 0 else -wd - 8) + m.params["parts"]["label"]["dx"] * (1 - p_lab)
                f.rr(lx, cy + dy - 24, wd, 48, r=10, fill="#ffffffe0", outline=AMBER, ow=2, a=a * p_lab)
                f.text(s, lx + 16, cy + dy - 14, size=28, color="#1c2b3a", w="B", a=a * p_lab)


class Compare(Part):
    TYPE = "compare"
    TITLE = "比較の左右"
    DOC = ("左右 2 つの面に、題・本文・要点・結論（verdict）・画像を並べて比べる。既定は左右から滑り込む（見本帳 21 slidein）。"
           "両方に画像があれば、見本帳 11 beforeafter（つまみが動いて 2 枚を見比べる）も使える")
    SIDE = {"type": "object", "additionalProperties": False,
            "properties": dict(ITEM_CUE, title={"type": "string"}, body=LINES,
                               points={"type": "array", "items": {"type": "string"}},
                               marker={"enum": ["check", "cross", "dot", "arrow"]},
                               verdict={"type": "string"}, verdict_color=COLOR,
                               image={"type": "object", "additionalProperties": False, "required": ["src"],
                                      "properties": {k: v for k, v in IMG_PROPS.items() if k != "caption"}})}
    SCHEMA = {"left": SIDE, "right": SIDE,
              "gap": {"type": "number", "minimum": 0}, "height": {"type": "number", "minimum": 60},
              "show": SHOW, "dim": DIM, "keep": KEEP, "title_size": {"type": "integer", "minimum": 16, "maximum": 80}}
    REQUIRED = ("left", "right")
    MOTION_FIELDS = {"motion": ("slidein", "stagger", "fade-in", "cut", "beforeafter"),
                     "emphasis": ("roomhighlight", "underline", "none")}
    DEFAULTS = {"motion": "slidein", "emphasis": "roomhighlight"}
    HEIGHT = 420

    def build(self):
        sp = self.spec
        self._items([sp["left"], sp["right"]], ["left", "right"])
        gap = sp.get("gap", 48)
        cw = (self.w - gap) / 2
        self.boxes = [(self.x, self.y, cw, self.h), (self.x + cw + gap, self.y, cw, self.h)]
        if self.enter is not None and self.enter.id == "beforeafter":
            if not (sp["left"].get("image") and sp["right"].get("image")):
                raise LayoutError(f"{self.ctx.where}: beforeafter は左右の両方に image を書きます")
        self.tsize = sp.get("title_size", 40)

    def _side(self, f, t, i, side, box, a):
        x, y, w, h = box
        f.rr(x, y, w, h, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
        yy = y + 28
        if side.get("title"):
            f.text(side["title"], x + 32, yy, size=self.tsize, w="B", a=a, maxw=w - 64)
            yy += int(self.tsize * 1.6)
        img = side.get("image")
        if img:
            sw, sh = asset_size(img["src"])
            crop = img.get("crop")
            if crop:
                sw, sh = crop[2] - crop[0], crop[3] - crop[1]
            ih = min(h * 0.55, y + h - yy - 24)
            ix, iy, iw, ihh = fit(sw, sh, (x + 32, yy, w - 64, ih))
            if img.get("paper"):
                f.rr(x + 32, yy, w - 64, ih, r=8, fill=PAPER, a=a)
            f.img(img["src"], ix, iy, int(iw), int(ihh), crop=tuple(crop) if crop else None, mode=img.get("mode", "auto"), a=a)
            yy += ih + 20
        if side.get("body"):
            rows = self.lines(f, side["body"], x + 32, yy, w - 64, max(30, y + h - yy - 24), size=30, color_=TEXT2,
                              a=a)
            yy += int(30 * 1.4) * len(rows) + 10
        for k, ptxt in enumerate(side.get("points") or []):
            check_icon(f, x + 50, yy + 18, a=a, dia=30, kind=side.get("marker", "dot"))
            f.text(ptxt, x + 80, yy, size=30, a=a, maxw=w - 112)
            yy += 50
        if side.get("verdict"):
            col = color(side.get("verdict_color"), AMBER)
            f.text(side["verdict"], x + 32, y + h - 64, size=34, w="B", color=col, a=a, maxw=w - 64)
        if yy > y + h - (70 if side.get("verdict") else 10):
            raise LayoutError(f"{self.ctx.where}: {'左右'[i]}の面に入りません（文を減らすか height を大きくする）")

    def draw(self, f, t):
        sp = self.spec
        if self.enter is not None and self.enter.id == "beforeafter":
            self._beforeafter(f, t)
            return
        for i, (side, box) in enumerate(zip((sp["left"], sp["right"]), self.boxes)):
            a, dx, dy = self.item_alpha(t, i, 32, box[2] * 0.3)
            if self.enter is not None and self.enter.id == "slidein" and i == 0:
                dx = -dx   # 左の面は左から
            if a <= 0:
                continue
            bx = (box[0] + dx, box[1] + dy, box[2], box[3])
            self._side(f, t, i, side, bx, a)
            self.emphasize(f, t, i, bx, a)

    def _beforeafter(self, f, t):
        """見本帳 11: 境界のつまみが 50% → 85% → 15% → 50% と動き、左に左の画像・右に右の画像（2.2s ease-in-out）。"""
        m = self.enter
        sp = self.spec
        x, y, w, h = self.x, self.y, self.w, self.h
        a = min(1.0, max(0.0, (t - self.cue.t) / 0.3)) * self.alive(t)
        if a <= 0:
            return
        f.rr(x, y, w, h, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
        p = m.progress(t, self.cue.t, speed=self.speed)
        pos = mo.keyframes(m.params["keys"], p)
        for side, key in ((sp["left"], "l"), (sp["right"], "r")):
            img = side["image"]
            sw, sh = asset_size(img["src"])
            crop = list(img.get("crop") or (0, 0, sw, sh))
            cw_, ch_ = crop[2] - crop[0], crop[3] - crop[1]
            ix, iy, iw, ih = fit(cw_, ch_, (x + 16, y + 16, w - 32, h - 32))
            split = ix + iw * pos
            if key == "l":
                frac = (split - ix) / iw
                c2 = (crop[0], crop[1], crop[0] + max(1, int(cw_ * frac)), crop[3])
                if c2[2] - c2[0] >= 2:
                    f.img(img["src"], ix, iy, max(1, int(split - ix)), int(ih), crop=c2, mode=img.get("mode", "auto"), a=a)
            else:
                frac = (split - ix) / iw
                c2 = (crop[0] + int(cw_ * frac), crop[1], crop[2], crop[3])
                if c2[2] - c2[0] >= 2:
                    f.img(img["src"], split, iy, max(1, int(ix + iw - split)), int(ih), crop=c2, mode=img.get("mode", "auto"), a=a)
        f.rr(split - 2, iy, 4, ih, r=2, fill="#ffffff", a=a)
        f.circ(split, iy + ih / 2, 44, fill="#ffffff", outline=LINE, ow=2, a=a)
        for side, ax in ((sp["left"], ix + 24), (sp["right"], ix + iw - 24)):
            if side.get("title"):
                f.text(side["title"], ax, iy + 20, size=30, w="B", color=TEXT, a=a, anchor="l" if ax < split else "r")


PARTS = [Image_, Compare]
