# -*- coding: utf-8 -*-
"""部品の動き。名前と使いどころはモーション見本帳にそろえる。

- 名前（scenes.yaml の ``motion`` / ``emphasis`` の値）は、モーション見本帳（動きの見本集）の見本の id。見本帳で 2 つの見本が同じ id を持つもの（stagger は
  UI 22 と文字 T03）は、番号を付けて ``stagger-T03`` と書く（番号の無い ``stagger`` は UI 22）
- 長さ・イージング・始めと終わりの値は、見本帳の CSS の例（数値が無いものは見本のプレビュー）から数値だけを取った。
  見本帳のコードは移していない
- 長さの既定は説明動画向け: 登場 0.4 秒・強調 0.3 秒・数値 0.8 秒（VIDEO_DEFAULTS）。
  見本帳の CSS の値は Web の画面向けなので ``Motion.book`` に分けて残し、どちらを使ったかを ``Motion.basis``
  （video / book）に書く。イージングは見本帳のまま。くり返しの周期・往復の見せ方など、長さを縮めないものは
  見本帳のまま（理由は ``Motion.why``）
- 見本帳の「速度」（×0.5・×1・×1.5）にならい、scenes.yaml の ``speed`` で長さを割る

描けない性質（ぼかし blur・3D・拡大縮小の一部）は落とし、残した性質を ``notes`` に書く。
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field, replace

SOURCE = "モーション見本帳の CSS の例（数値だけ）"


# ---------------------------------------------------------------- イージング（CSS と同じ定義）

@functools.lru_cache(None)
def cubic_bezier(x1: float, y1: float, x2: float, y2: float):
    """CSS の cubic-bezier(x1, y1, x2, y2)。戻り値は 0..1 → 0..1 の関数。"""

    def sample(a1, a2, s):
        return ((1 - 3 * a2 + 3 * a1) * s + (3 * a2 - 6 * a1)) * s * s + 3 * a1 * s

    def slope(a1, a2, s):
        return 3 * (1 - 3 * a2 + 3 * a1) * s * s + 2 * (3 * a2 - 6 * a1) * s + 3 * a1

    def f(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        s = x
        for _ in range(8):   # ニュートン法
            d = slope(x1, x2, s)
            if abs(d) < 1e-6:
                break
            s2 = s - (sample(x1, x2, s) - x) / d
            if not 0 <= s2 <= 1:
                break
            s = s2
        if abs(sample(x1, x2, s) - x) > 1e-5:   # 収まらなければ二分法
            lo, hi = 0.0, 1.0
            s = x
            for _ in range(40):
                v = sample(x1, x2, s)
                if abs(v - x) < 1e-7:
                    break
                lo, hi = (s, hi) if v < x else (lo, s)
                s = (lo + hi) / 2
        return sample(y1, y2, s)

    return f


EASINGS = {   # CSS のキーワード
    "linear": None,
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
}


def ease_fn(easing):
    """'ease' などのキーワード・(x1, y1, x2, y2)・'ease-out-cubic' → 関数。"""
    if easing == "ease-out-cubic":   # 見本帳 T08 の JS: 1 - (1 - p)^3
        return lambda p: 1 - (1 - max(0.0, min(1.0, p))) ** 3
    if isinstance(easing, str):
        easing = EASINGS[easing]
    if easing is None:
        return lambda p: max(0.0, min(1.0, p))
    return cubic_bezier(*easing)


# ---------------------------------------------------------------- 見本

ROLES = {
    "enter": "現れ方",
    "emphasis": "読んでいる箇所の示し方",
    "value": "数値の出し方",
    "compare": "比べ方",
    "switch": "入れ替え方・消え方",
}

# 説明動画の既定の長さ。見本帳の CSS の値は Web の画面向けで、
# 説明動画には遅い。役割ごとにこの長さを既定にし、加減速の形（イージング）は見本帳のまま。
# 見本帳の値は Motion.book に残す（どちらを使ったかは Motion.basis）
VIDEO_DEFAULTS = {"enter": 0.4, "emphasis": 0.3, "value": 0.8}

BASES = {
    "video": "説明動画の既定",
    "book": "見本帳のまま",
}


@dataclass(frozen=True)
class Motion:
    id: str                 # scenes.yaml に書く名前（見本帳の id）
    number: str             # 見本帳の番号
    name: str               # 見本帳の名前
    role: str               # ROLES のどれか
    duration: float         # 使う長さ（秒、speed 1 のとき）。basis が video なら説明動画の既定
    easing: object = "ease"
    delay: float = 0.0      # きっかけからの遅れ（秒）
    step: float = 0.0       # 同じきっかけで並ぶ要素の間の遅れ（見本帳の --i × 秒。見本帳のまま）
    params: dict = field(default_factory=dict)   # 始めと終わりの値（見本帳の CSS の数値）。parts は使う長さ
    css: str = ""           # 数値を取った CSS（短く）
    notes: str = ""         # 描けない性質など
    book: dict = field(default_factory=dict)     # 見本帳の値: duration（None は書かれていない）・delay・parts
    basis: str = "video"    # duration・delay の出どころ（BASES）
    why: str = ""           # 見本帳のままにした理由・長さの決め方

    def progress(self, t: float, t0: float, *, i: int = 0, speed: float = 1.0, duration: float | None = None,
                 delay: float | None = None) -> float:
        """きっかけ t0 から、この動きが進んだ割合 0..1（イージングの後）。"""
        d = (self.duration if duration is None else duration) / speed
        start = t0 + ((self.delay if delay is None else delay) + self.step * i) / speed
        if t < start:
            return 0.0
        if d <= 0:
            return 1.0
        return ease_fn(self.easing)(min(1.0, (t - start) / d))

    def end_sec(self, *, items: int = 1, speed: float = 1.0) -> float:
        """きっかけから動きが終わるまでの秒（items 個が step ずつずれて並ぶとき）。"""
        sub = [p for p in self.params.get("parts", {}).values()]
        tail = max([self.duration] + [q["delay"] + q["duration"] - self.delay for q in sub])
        return (self.delay + self.step * max(0, items - 1) + tail) / speed

    def book_motion(self) -> "Motion":
        """見本帳の値（CSS の例の長さ・遅れ）で動く同じ見本。比べるため・記録のため（既定では使わない）。"""
        params = dict(self.params)
        if "parts" in self.book:
            params["parts"] = self.book["parts"]
        dur = self.book.get("duration")
        return replace(self, duration=self.duration if dur is None else dur, delay=self.book.get("delay", 0.0),
                       params=params, basis="book")


def _m(id_: str, number: str, name: str, role: str, book: float | None, easing: object = "ease", *,
       video: float | None = None, delay: float = 0.0, book_delay: float | None = None, parts: dict | None = None,
       book_parts: dict | None = None, keep: str = "", why: str = "", **kw) -> Motion:
    """book: 見本帳の CSS の長さ（秒。None は書かれていない）。video: 説明動画の長さ（None なら役割の既定）。
    keep: 見本帳のままにする理由（書いたら book の長さを使う）。"""
    bk = {"duration": book, "delay": delay if book_delay is None else book_delay}
    params = dict(kw.pop("params", {}))
    if book_parts is not None:
        bk["parts"] = book_parts
        params["parts"] = parts if parts is not None else book_parts
    if keep:
        return Motion(id_, number, name, role, book, easing, delay=bk["delay"], params=params, book=bk,
                      basis="book", why=keep, **kw)
    dur = VIDEO_DEFAULTS[role] if video is None else video
    return Motion(id_, number, name, role, dur, easing, delay=delay, params=params, book=bk, basis="video",
                  why=why, **kw)


MOTIONS: dict[str, Motion] = {m.id: m for m in [
    # ---- 現れ方（説明動画の既定 0.4 秒）
    _m("cut", "V01", "カット", "enter", 0.0, "linear", video=0.0, css="opacity 0→1（0s）",
       notes="間を作らずに出す", why="長さ 0（見本帳と同じ）"),
    _m("fade", "V02", "フェード", "enter", 1.5, "ease", css="opacity 0→1 1.5s",
       notes="2 つの画を溶かしてつなぐ（画像の切り替え）"),
    _m("fade-in", "T01", "フェードイン", "enter", 1.7, "ease", params={"dy_em": 0.25},
       css="from opacity 0, translateY(.25em), blur(6px)；1.7s ease", notes="ぼかし（blur）は描かない"),
    _m("stagger", "22", "順に現れる", "enter", 0.5, (0.2, 0.8, 0.2, 1.0), step=0.08, params={"dy": 18},
       css="from opacity 0, translateY(18px) scale(.96)；.5s cubic-bezier(.2,.8,.2,1)、--i × .08s",
       notes="scale(.96) は描かない（位置と濃さだけ）。要素の間の遅れ .08s は見本帳のまま"),
    _m("stagger-T03", "T03", "文字送り", "enter", 0.55, (0.2, 0.8, 0.2, 1.0), step=0.1, params={"dy_em": 0.9},
       css="from opacity 0, translateY(.9em)；.55s cubic-bezier(.2,.8,.2,1)、--i × .1s（1 文字ずつ）",
       notes="見出しの文字を 1 文字ずつ。文字の間の遅れ .1s は見本帳のまま"),
    _m("slidein", "21", "スライドイン", "enter", 0.6, (0.2, 0.8, 0.2, 1.0), params={"dx_ratio": 1.2},
       css="from translateX(120%) opacity 0；.6s cubic-bezier(.2,.8,.2,1)", notes="direction: reverse で左から"),
    _m("clipreveal", "12", "画像のクリップ表示", "enter", 1.0, (0.7, 0.0, 0.2, 1.0),
       params={"scale_from": 1.15, "scale_duration": 1.4, "scale_easing": "ease"},
       css="clip-path inset(0 100% 0 0)→inset(0) 1s cubic-bezier(.7,0,.2,1)、scale 1.15→1 1.4s",
       notes="画像だけ。左から切り抜きを広げる（scale 1.15→1 は描かない）"),
    _m("wipe", "V03", "ワイプ", "enter", 1.2, (0.65, 0.0, 0.35, 1.0),
       css="clip-path inset(0 100% 0 0)→inset(0)；1.2s cubic-bezier(.65,0,.35,1)", notes="画像・面を左から"),
    _m("typewriter", "T02", "タイプ表示", "enter", 0.01, "linear", step=0.18,
       css="1 文字ずつ opacity 0→1、--i × .18s", notes="短い文だけ（長い文は避ける、と見本帳）",
       keep="1 文字ずつの遅れ（.18s）で長さが決まり、1 文字の長さは 0 に近いので、見本帳のまま"),
    # ---- 読んでいる箇所の示し方（説明動画の既定 0.3 秒）
    _m("roomhighlight", "30", "平面図の部屋を強調", "emphasis", None, "ease", params={"others_opacity": 0.45},
       css="ほかの部屋 opacity .45、指した部屋に色と名前（長さは書かれていない）",
       notes="読んでいる要素に注目枠、ほかを薄くする", why="見本帳に長さが無い。説明動画の既定 0.3 秒"),
    _m("fill", "08", "背景色が広がる", "emphasis", 0.4, "ease",
       css="background-size 0 100%→100% 100%（左から）；.4s", notes="読んでいる行・項目の面が左から満ちる"),
    _m("underline", "07", "下線が伸びる", "emphasis", 0.35, "ease", params={"height": 3},
       css="::after height 3px、scaleX(0)→scaleX(1)（origin left）；.35s",
       notes="読んでいる項目の下に線。矢印の伸び方もこの長さ"),
    _m("marker", "T13", "マーカーが引かれる", "emphasis", 1.0, (0.6, 0.0, 0.3, 1.0),
       params={"band": (0.58, 0.92), "alpha": 0.42},
       css="帯 58%〜92% の高さ、rgb(234 107 77 / .42)、background-size 0%→100%；1s cubic-bezier(.6,0,.3,1)",
       notes="色は engine の CORAL（見本帳の rgb(234 107 77) に近い色。濃さ .42 は見本帳のまま）。文字の下に引く"),
    _m("hotspot", "28", "注目点の脈動", "emphasis", 1.1, "ease-out",
       params={"scale_to": 3.6, "opacity_from": 0.9, "second": 0.45, "border": 2},
       css="輪 opacity .9→0、scale(1)→scale(3.6)；1.1s ease-out infinite、2 つ目の輪は .45s 後",
       notes="読んでいる間だけ繰り返す",
       keep="読んでいる間くり返す輪の周期（現れる長さではない）。0.3 秒の周期は速すぎるので、見本帳のまま"),
    _m("callout", "T10", "引き出し線の注記", "emphasis", 0.3, "ease", video=0.15,
       book_parts={"leader": {"delay": 0.3, "duration": 0.5, "easing": "ease"},
                   "label": {"delay": 0.7, "duration": 0.4, "easing": "ease", "dx": -6}},
       parts={"leader": {"delay": 0.15, "duration": 0.25, "easing": "ease"},
              "label": {"delay": 0.35, "duration": 0.2, "easing": "ease", "dx": -6}},
       css="点 .3s → 引き出し線 scaleX(0)→1 .5s（.3s 後）→ 注記 from opacity 0, translateX(-6px) .4s（.7s 後）",
       why="点・線・注記の 3 段なので、見本帳の順と比を保って半分（全体 1.1 秒 → 0.55 秒）"),
    # ---- 数値（説明動画の既定 0.8 秒）
    _m("counter", "T08", "数字のカウントアップ", "value", 1.6, "ease-out-cubic", book_delay=0.2,
       css="to × (1 - (1 - p)^3)；見本のプレビューは 0.2s 後から 1.6s（main.ts の runCounters）",
       why="きっかけ（読む文）から数え始める（見本のプレビューの 0.2s の遅れは使わない）"),
    # ---- 入れ替え方・消え方
    _m("fadethrough", "26", "タブの切り替え（フェードスルー）", "switch", 0.09, "ease",
       params={"in_duration": 0.21, "scale": 0.94},
       css="out .09s → opacity 0, scale(.94)；in .21s（.09s 後）from opacity 0, scale(.94)",
       notes="同じ場所の中身を入れ替える・場面の中で部品を消す（until）。scale(.94) は描かない",
       keep="出 .09s ＋ 入 .21s で 0.3 秒。すでに説明動画の長さ"),
    # ---- 比べ方
    _m("beforeafter", "11", "前後比較スライダー", "compare", 2.2, "ease-in-out",
       params={"keys": [(0.0, 0.5), (0.08, 0.5), (0.35, 0.85), (0.70, 0.15), (0.92, 0.5), (1.0, 0.5)]},
       css="clip-path inset(0 0 0 var(--pos,50%))、プレビュー 2.2s ease-in-out で 50%→85%→15%→50%（style.css の ba-clip）",
       keep="前と後を往復して見せる動き（現れ方ではない）。左右を見比べる間が要るので、見本帳のまま"),
]}


def timing_rows() -> list[dict]:
    """動きの長さの表（docs と確かめ用）: id・役割・使う長さ・見本帳の値・出どころ。"""
    rows = []
    for m in MOTIONS.values():
        rows.append({"id": m.id, "number": m.number, "role": m.role, "duration": m.duration, "delay": m.delay,
                     "end": round(m.end_sec(), 3), "book_duration": m.book.get("duration"),
                     "book_delay": m.book.get("delay", 0.0), "book_end": round(m.book_motion().end_sec(), 3),
                     "basis": m.basis, "why": m.why})
    return rows


STAGGER_ALIASES = {"stagger-22": "stagger", "22": "stagger", "T03": "stagger-T03"}


def get(name: str) -> Motion:
    name = STAGGER_ALIASES.get(name, name)
    try:
        return MOTIONS[name]
    except KeyError:
        raise KeyError(name) from None


def names(role: str | None = None) -> list[str]:
    return [k for k, m in MOTIONS.items() if role is None or m.role == role]


def keyframes(keys, p: float) -> float:
    """[(時刻の割合, 値)] を線形に補う（イージングは区間ごとに掛けない。CSS の keyframes の既定と同じく全体に掛ける側で）。"""
    for (a, va), (b, vb) in zip(keys, keys[1:]):
        if p <= b:
            return va if b == a else va + (vb - va) * (p - a) / (b - a)
    return keys[-1][1]


def sub_progress(m: Motion, part: str, t: float, t0: float, speed: float = 1.0) -> float:
    """lowerthird・callout の中の要素（title・leader・label など）の進み 0..1。"""
    q = m.params["parts"][part]
    return Motion(m.id, m.number, m.name, m.role, q["duration"], q.get("easing", "ease"), delay=q["delay"]).progress(
        t, t0, speed=speed)


def ease_value(easing, p: float) -> float:
    return ease_fn(easing)(p)


__all__ = ["BASES", "MOTIONS", "Motion", "ROLES", "SOURCE", "VIDEO_DEFAULTS", "cubic_bezier", "ease_fn", "ease_value",
           "get", "keyframes", "names", "sub_progress", "timing_rows"]
