# -*- coding: utf-8 -*-
"""描画エンジン（render_mode: interactive）。

各フレームは「表示リスト」（部品のキー・位置・不透明度の並び）として組み立て、部品の画像（スプライト）は
キャッシュして合成する。表示リストが前のフレームと同じなら描画結果を使い回すので、静止している区間は速い。
依存: Pillow だけ。

決まり:
- 書体はこのパッケージの fonts/（Noto Sans JP の OTF、SIL OFL 1.1）から読む（OS の差で絵が変わらない）
- 静止画は ASSET_DIRS（場面コードのフォルダの assets/ など。set_asset_dirs で決める）から探す。絶対パスも可。
  この PC のファイルだけを読む（URL は読まない。ネットワークを使わない）
- 文字のはみ出し: ``Frame.text(..., maxw=)``・``text_box`` は入らなければ LayoutError
- 細線: ``img(..., mode='auto')`` は縮小の割合から太らせ方を選ぶ
"""
from __future__ import annotations

import functools
import math
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
FONT_DIR = Path(__file__).resolve().parent / "fonts"
ASSET_DIRS: list[Path] = []   # 静止画を探すフォルダ（先に書いたものから）。set_asset_dirs で決める
ASSET_ROOTS: list[Path] = []  # 空でなければ、静止画はこの下のファイルだけ（erkit make: 台本のフォルダと出力フォルダ）


class LayoutError(ValueError):
    """文字が枠に入らない・表の見出しが無いなど、画面の組み立ての誤り（描く前に止める）。"""


# ---------------------------------------------------------------- 色
BG_TOP = '#0a1626'
BG_BOT = '#0e2037'
BAND = '#060f1b'      # 字幕帯
PANEL = '#132a44'     # カード面
PANEL2 = '#1a3859'
LINE = '#2c4b6c'
TEXT = '#eef3f8'
TEXT2 = '#a9bccf'
TEXT3 = '#7d93aa'
TEAL = '#62c0d0'      # 主要情報
TEAL_D = '#2f7f92'
AMBER = '#f6b93b'     # 注目箇所（アクセント）
PAPER = '#f4f6f8'     # 図面を載せる明るい面
INK = '#1c2b3a'
BLUE = '#8fb4ff'
GREEN = '#8fd6a5'
CORAL = '#ff8f7d'
VEIL = '#0b1a2c'      # 非注目部分にかける幕
ACCENT = '#d92d20'    # 台本の注釈（赤枠・矢印）。slides（deck/builder.py の ACCENT）と同じ赤
STEP_DONE = '#3f6f8c' # 進行表示の済んだ段（見出し）
CHIP_FILL = '#0b1a2ccc'  # チップ・要点の面
PILL_FILL = '#10233a'    # 札（ピル）の面
# 資料の抜き書き（明るい紙面の表）
DOC_BG = '#ffffff'
DOC_EDGE = '#b9c6d3'
DOC_HEAD = '#16304d'
DOC_SUB = '#51657a'
DOC_LINE = '#c5d0db'
DOC_TINT_HEAD = '#e9eef4'
DOC_TINT_COL = '#f1f4f8'
DOC_TINT_MARK = '#dcf2ea'

SUB_TOP = 940         # 字幕帯の上端（場面はこれより上に描く。検証は字幕帯の明るさで字幕の有無を見る）


def rgba(c):
    if c is None or isinstance(c, tuple):
        return c
    c = c.lstrip('#')
    if len(c) == 6:
        c += 'ff'
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))


def with_alpha(c, a):
    r, g, b, _ = rgba(c)
    return '#%02x%02x%02x%02x' % (r, g, b, int(round(a * 255)))


# ---------------------------------------------------------------- フォント
FONT_FILES = {'R': 'NotoSansJP-Regular.otf', 'B': 'NotoSansJP-Bold.otf'}   # 入手先・版・sha256 は fonts/README.md
_BASIC = getattr(getattr(ImageFont, 'Layout', None), 'BASIC', None)
if _BASIC is None:
    _BASIC = getattr(ImageFont, 'LAYOUT_BASIC', 0)


@functools.lru_cache(None)
def font(weight, size):
    """Noto Sans JP（OTF）。レイアウトは BASIC（raqm の有無で絵が変わらないように）。"""
    return ImageFont.truetype(str(FONT_DIR / FONT_FILES[weight]), size, layout_engine=_BASIC)


@functools.lru_cache(None)
def tw(s, weight='R', size=32):
    """文字列の幅(px)。"""
    return font(weight, size).getlength(s)


TP = 4  # 文字スプライトの左右余白


def _text_dy(weight, size):
    asc, _ = font(weight, size).getmetrics()
    return asc - int(round(size * 0.88))


# ---------------------------------------------------------------- 時間関数
def ramp(t, t0, d=0.35):
    """t0 から d 秒かけて 0→1（減速カーブ）。"""
    if t <= t0:
        return 0.0
    if t >= t0 + d:
        return 1.0
    x = (t - t0) / d
    return 1 - (1 - x) ** 3


def lin(t, t0, d):
    if t <= t0:
        return 0.0
    if t >= t0 + d:
        return 1.0
    return (t - t0) / d


def win(t, t0, t1, din=0.3, dout=0.3):
    """t0 で現れ t1 で消える 0..1。"""
    return min(ramp(t, t0, din), 1 - ramp(t, t1, dout))


# ---------------------------------------------------------------- スプライト生成
SS = 3   # 図形のスーパーサンプリング倍率
M = 8    # 図形スプライトの外周余白


def _mk_text(s, weight, size, color):
    f = font(weight, size)
    asc, desc = f.getmetrics()
    im = Image.new('RGBA', (int(math.ceil(f.getlength(s))) + 2 * TP, asc + desc + 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((TP, 0), s, font=f, fill=rgba(color))
    return im


def _mk_textrot(s, weight, size, color):
    return _mk_text(s, weight, size, color).rotate(90, expand=True)


def _dash_line(d, p0, p1, color, width, dash, gap):
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    if L == 0:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    pos = 0.0
    while pos < L:
        e = min(L, pos + dash)
        d.line((x0 + ux * pos, y0 + uy * pos, x0 + ux * e, y0 + uy * e), fill=color, width=width)
        pos += dash + gap


def _mk_rr(w, h, r, fill, outline, ow, dash):
    S = SS
    im = Image.new('RGBA', ((w + 2 * M) * S, (h + 2 * M) * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = (M * S, M * S, (M + w) * S - 1, (M + h) * S - 1)
    r = min(r, w // 2, h // 2)
    if dash and outline:
        if fill:
            d.rounded_rectangle(box, radius=r * S, fill=rgba(fill))
        x0, y0, x1, y1 = box
        c = rgba(outline)
        dl, gp = dash * S, int(dash * 0.7) * S
        hw = ow * S // 2
        _dash_line(d, (x0, y0 + hw), (x1, y0 + hw), c, ow * S, dl, gp)
        _dash_line(d, (x0, y1 - hw), (x1, y1 - hw), c, ow * S, dl, gp)
        _dash_line(d, (x0 + hw, y0), (x0 + hw, y1), c, ow * S, dl, gp)
        _dash_line(d, (x1 - hw, y0), (x1 - hw, y1), c, ow * S, dl, gp)
    else:
        d.rounded_rectangle(box, radius=r * S, fill=rgba(fill), outline=rgba(outline),
                            width=(ow * S if outline else 0))
    return im.resize((w + 2 * M, h + 2 * M), Image.LANCZOS)


GM = 28  # グローの余白


def _mk_glow(w, h, r, color):
    im = Image.new('RGBA', (w + 2 * GM, h + 2 * GM), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((GM - 2, GM - 2, GM + w + 1, GM + h + 1), radius=r + 2, outline=rgba(color), width=8)
    im = im.filter(ImageFilter.GaussianBlur(9))
    a = im.getchannel('A').point(lambda v: min(255, int(v * 1.1)))
    im.putalpha(a)
    return im


def _mk_circ(dia, fill, outline, ow):
    S = SS
    im = Image.new('RGBA', ((dia + 2 * M) * S, (dia + 2 * M) * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((M * S, M * S, (M + dia) * S - 1, (M + dia) * S - 1), fill=rgba(fill), outline=rgba(outline),
              width=(ow * S if outline else 0))
    return im.resize((dia + 2 * M, dia + 2 * M), Image.LANCZOS)


def _mk_path(pts, color, width, prog_q, head, closed):
    """折れ線。pts はスプライト内座標（余白込み）。prog_q/100 まで描く。"""
    S = SS
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w, h = int(max(xs)) + M + 12, int(max(ys)) + M + 12
    im = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = rgba(color)
    P = list(pts) + ([pts[0]] if closed else [])
    segs = [(P[i], P[i + 1]) for i in range(len(P) - 1)]
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs)
    remain = total * prog_q / 100.0
    last, direction = None, None
    for a, b in segs:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L == 0 or remain <= 0:
            continue
        k = min(1.0, remain / L)
        e = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
        d.line((a[0] * S, a[1] * S, e[0] * S, e[1] * S), fill=c, width=width * S)
        rr = width * S / 2.0
        for q in (a, e):
            d.ellipse((q[0] * S - rr, q[1] * S - rr, q[0] * S + rr, q[1] * S + rr), fill=c)
        last, direction = e, ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        remain -= L
    if head and last and prog_q >= 100:
        ux, uy = direction
        hl, hw = width * 3.2, width * 2.2
        tip = (last[0] + ux * 2, last[1] + uy * 2)
        base = (tip[0] - ux * hl, tip[1] - uy * hl)
        p1 = (base[0] - uy * hw, base[1] + ux * hw)
        p2 = (base[0] + uy * hw, base[1] - ux * hw)
        d.polygon([(tip[0] * S, tip[1] * S), (p1[0] * S, p1[1] * S), (p2[0] * S, p2[1] * S)], fill=c)
    return im.resize((w, h), Image.LANCZOS)


def _mk_hatch(w, h, color, spacing, lw):
    S = 2
    im = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = rgba(color)
    for k in range(-h, w + h, spacing):
        d.line((k * S, h * S, (k + h) * S, 0), fill=c, width=lw * S)
    return im.resize((w, h), Image.LANCZOS)


def set_asset_dirs(dirs) -> None:
    """静止画を探すフォルダを決める（場面コードのフォルダの assets/ など）。キャッシュも捨てる。"""
    ASSET_DIRS[:] = [Path(d) for d in dirs]
    _asset.cache_clear()
    asset_size.cache_clear()
    _cache.clear()


def set_asset_roots(roots) -> None:
    """静止画を読んでよいフォルダを決める（空なら決めない）。キャッシュも捨てる。"""
    ASSET_ROOTS[:] = [Path(d).resolve() for d in roots or []]
    _asset.cache_clear()
    asset_size.cache_clear()
    _cache.clear()


def _inside_roots(p: Path) -> Path:
    if not ASSET_ROOTS:
        return p
    q = p.resolve()
    for r in ASSET_ROOTS:
        try:
            q.relative_to(r)
            return p
        except ValueError:
            continue
    raise LayoutError(f'静止画は台本のフォルダか出力フォルダの中のファイルだけ使えます: {p}'
                      f'（使えるフォルダ: {", ".join(str(r) for r in ASSET_ROOTS)}）')


def asset_path(name) -> Path:
    if '://' in str(name):   # この PC のファイルだけ（ネットワークを使わない）
        raise LayoutError(f'静止画は PC の中のファイルを指定します（URL は使えません）: {name}')
    p = Path(name)
    if p.is_absolute():
        if p.is_file():
            return _inside_roots(p)
        raise LayoutError(f'静止画がありません: {p}')
    for d in ASSET_DIRS:
        q = d / name
        if q.is_file():
            return _inside_roots(q)
    raise LayoutError(f'静止画がありません: {name}（探した場所: {", ".join(str(d) for d in ASSET_DIRS) or "なし"}）')


@functools.lru_cache(None)
def _asset(name):
    with Image.open(asset_path(name)) as im:
        return im.convert('RGB')


@functools.lru_cache(None)
def asset_size(name):
    """静止画の元の大きさ (w, h)。"""
    return _asset(name).size


def thicken_mode(src_w, src_h, w, h):
    """縮小の割合から細線の太らせ方を選ぶ（図面の細線が縮小で消えないように）。

    半分より小さく縮める図は 1 画素（thick2）、少し縮める図は半画素（thick）、縮めない図はそのまま。
    """
    k = min(w / max(1, src_w), h / max(1, src_h))
    if k < 0.5:
        return 'thick2'
    if k < 0.98:
        return 'thick'
    return ''


def _mk_img(name, w, h, crop, mode):
    """静止画。縮小で細線が消えないよう、線を少し太らせてから縮小できる。

    mode: 'thick'=半画素ぶん太らせる（大きく見せる図面用） / 'thick2'=1画素ぶん（小さな縮小図用）
          'auto'=縮小の割合から選ぶ / 'paper'=紙色を乗算 / 'ink'=線を濃くする。
    """
    im = _asset(name)
    if crop:
        im = im.crop(crop)
    if 'auto' in mode:
        mode = mode.replace('auto', thicken_mode(im.width, im.height, w, h))
    if 'thick2' in mode:
        im = im.filter(ImageFilter.MinFilter(3))
        im = im.resize((w, h), Image.LANCZOS)
    elif 'thick' in mode:
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS).filter(ImageFilter.MinFilter(3))
        im = im.resize((w, h), Image.LANCZOS).point(lambda v: int(255 * (v / 255.0) ** 1.5))
    else:
        im = im.resize((w, h), Image.LANCZOS)
    if 'ink' in mode:
        im = im.point(lambda v: int(255 * (v / 255.0) ** 1.6))
    if 'paper' in mode:
        im = ImageChops.multiply(im, Image.new('RGB', im.size, rgba(PAPER)[:3]))
    return im.convert('RGBA')


# 区分タグ: 原 / 標 / 仮 / 写真所見 / 未確認  （色だけでなく枠線の形でも区別する）
TAG_STYLE = {
    '原': dict(fill=TEAL, outline=None, fg='#06202c', dash=0),
    '標': dict(fill='#8fb4ff26', outline=BLUE, fg=BLUE, dash=0),
    '仮': dict(fill='#f6b93b1f', outline=AMBER, fg=AMBER, dash=7),
    '写真所見': dict(fill='#8fd6a51c', outline=GREEN, fg=GREEN, dash=3),
    '未確認': dict(fill='#ff8f7d00', outline=CORAL, fg=CORAL, dash=0, hatch=True),
}


def tag_size(kind, size):
    return int(tw(kind, 'B', size)) + int(size * 0.9), int(size * 1.55)


def _mk_tag(kind, size):
    st = TAG_STYLE[kind]
    w, h = tag_size(kind, size)
    im = Image.new('RGBA', (w + 2 * M, h + 2 * M), (0, 0, 0, 0))
    if st.get('hatch'):
        ht = _mk_hatch(w, h, with_alpha(CORAL, 0.38), 9, 2)
        mask = _mk_rr(w, h, 6, '#ffffff', None, 0, 0).getchannel('A').crop((M, M, M + w, M + h))
        im.paste(ht, (M, M), ImageChops.multiply(ht.getchannel('A'), mask))
    body = _mk_rr(w, h, 6, st['fill'], st['outline'], 2, st['dash'])
    im = Image.alpha_composite(im, body)
    f = font('B', size)
    d = ImageDraw.Draw(im)
    x = M + (w - f.getlength(kind)) / 2
    y = M + (h - size) / 2 - _text_dy('B', size) - size * 0.02
    if st.get('hatch'):
        # 文字の下だけ塗りつぶして読みやすくする
        pad = 4
        d.rounded_rectangle((x - pad, M + 5, x + f.getlength(kind) + pad, M + h - 5), radius=4, fill=rgba('#1a2536'))
    d.text((x, y), kind, font=f, fill=rgba(st['fg']))
    return im


def _mk_arrow(length, height, angle_q, color):
    """ブロック矢印（PowerPoint の右矢印と同じ形: 軸の太さは高さの半分、頭の長さは高さの半分）。

    angle_q は向き（度 × 10 の整数。0 で右向き）。中心まわりに回した画像を返す（中心は画像の中心）。
    """
    S = SS
    L, Hh = length * S, height * S
    hl = Hh * 0.5
    pts = [(0, Hh * 0.25), (L - hl, Hh * 0.25), (L - hl, 0), (L, Hh / 2), (L - hl, Hh), (L - hl, Hh * 0.75),
           (0, Hh * 0.75)]
    pad = int(math.hypot(L, Hh) / 2) + 2 * S
    cx = cy = pad
    im = Image.new('RGBA', (2 * pad, 2 * pad), (0, 0, 0, 0))
    a = math.radians(angle_q / 10.0)
    ca, sa = math.cos(a), math.sin(a)
    poly = []
    for x, y in pts:
        x, y = x - L / 2, y - Hh / 2
        poly.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    ImageDraw.Draw(im).polygon(poly, fill=rgba(color))
    n = 2 * pad // S
    return im.resize((n, n), Image.LANCZOS)


MAKERS = {
    'text': _mk_text, 'textrot': _mk_textrot, 'rr': _mk_rr, 'glow': _mk_glow, 'circ': _mk_circ,
    'path': _mk_path, 'hatch': _mk_hatch, 'img': _mk_img, 'tag': _mk_tag, 'arrow': _mk_arrow,
}
FN = {}  # 場面固有の図（場面コードの側で登録する: FN['名前'] = 関数(*params) → RGBA の画像）


def _mk_fn(name, *params):
    return FN[name](*params)


MAKERS['fn'] = _mk_fn

_cache = OrderedDict()
CACHE_MAX = 900


def sprite(key):
    v = _cache.get(key)
    if v is not None:
        _cache.move_to_end(key)
        return v
    im = MAKERS[key[0]](*key[1:])
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    v = (im.convert('RGB'), im.getchannel('A'))
    _cache[key] = v
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return v


_LUT = [bytes((v * a + 127) // 255 for v in range(256)) for a in range(256)]


# ---------------------------------------------------------------- 文字の折り返し
NO_HEAD = set('、。，．）」』】・ー々ぁぃぅぇぉっゃゅょァィゥェォッャュョ')
NO_TAIL = set('（「『【')


def is_ascii_word(ch):
    """英数字の語の一部（ここでは改行しない）。"""
    return bool(ch) and (ch.isascii() and (ch.isalnum() or ch in ' -.,'))


def wrap_text(text, weight, size, maxw):
    """幅 maxw に収まるよう複数行に分ける（行頭・行末の禁則、英数字の途中では切らない）。"""
    lines, cur = [], ''
    for ch in text:
        if cur and tw(cur + ch, weight, size) > maxw:
            nxt = ch
            k = len(cur)
            while k > 1 and (nxt in NO_HEAD or cur[k - 1] in NO_TAIL
                             or (is_ascii_word(cur[k - 1]) and is_ascii_word(nxt) and cur[k - 1] != ' ')):
                k -= 1
                nxt = cur[k]
            if k <= 1:
                k = len(cur)
            lines.append(cur[:k].rstrip())
            cur = cur[k:].lstrip()
        cur += ch
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- 表示リスト
class Frame:
    """1 フレームの表示リスト。場面コードは f.text / f.rr / f.img … で部品を積む。"""

    def __init__(self):
        self.ops = []

    def add(self, key, x, y, a=1.0):
        ai = int(round(max(0.0, min(1.0, a)) * 255))
        if ai > 0:
            self.ops.append((key, int(round(x)), int(round(y)), ai))

    # 文字。y は文字の上端（漢字の天）付近。anchor: l / c / r。maxw を渡すと、入らなければ LayoutError
    def text(self, s, x, y, size=32, color=TEXT, w='R', a=1.0, anchor='l', maxw=None):
        if not s:
            return
        wd = tw(s, w, size)
        if maxw is not None and wd > maxw + 0.5:
            raise LayoutError(f'文字が枠に入りません（幅 {wd:.0f}px ＞ {maxw:.0f}px）: {s}')
        if anchor != 'l':
            x = x - wd / 2 if anchor == 'c' else x - wd
        self.add(('text', s, w, size, color), x - TP, y - _text_dy(w, size), a)

    def text_box(self, s, x, y, w, h, size=30, color=TEXT, weight='R', a=1.0, lh=None, align='l', valign='t'):
        """枠 (x, y, w, h) の中に折り返して書く。入らなければ LayoutError。戻り値は行の並び。"""
        lines = wrap_text(s, weight, size, w) if isinstance(s, str) else list(s)
        lh = lh or int(size * 1.4)
        need = lh * (len(lines) - 1) + size
        if need > h + 0.5:
            raise LayoutError(f'文字が枠に入りません（{len(lines)} 行・高さ {need}px ＞ {h}px）: {"".join(lines)}')
        for s_ in lines:
            if tw(s_, weight, size) > w + 0.5:
                raise LayoutError(f'文字が枠に入りません（幅 {tw(s_, weight, size):.0f}px ＞ {w}px）: {s_}')
        y0 = y + ((h - need) / 2 if valign == 'c' else (h - need) if valign == 'b' else 0)
        for i, s_ in enumerate(lines):
            if align == 'c':
                self.text(s_, x + w / 2, y0 + i * lh, size=size, color=color, w=weight, a=a, anchor='c')
            elif align == 'r':
                self.text(s_, x + w, y0 + i * lh, size=size, color=color, w=weight, a=a, anchor='r')
            else:
                self.text(s_, x, y0 + i * lh, size=size, color=color, w=weight, a=a)
        return lines

    def rr(self, x, y, w, h, r=14, fill=None, outline=None, ow=2, a=1.0, dash=0):
        self.add(('rr', int(w), int(h), int(r), fill, outline, ow, dash), x - M, y - M, a)

    def veil(self, x, y, w, h, a, r=14):
        self.rr(x, y, w, h, r=r, fill=VEIL, a=a)

    def focus(self, x, y, w, h, r=14, a=1.0, color=AMBER, ow=4):
        """注目枠（にじみ＋枠線）。"""
        self.add(('glow', int(w), int(h), int(r), color), x - GM, y - GM, a * 0.55)
        self.rr(x, y, w, h, r=r, outline=color, ow=ow, a=a)

    def circ(self, cx, cy, dia, fill=None, outline=None, ow=3, a=1.0):
        self.add(('circ', int(dia), fill, outline, ow), cx - dia / 2 - M, cy - dia / 2 - M, a)

    def path(self, pts, color=TEAL, width=4, prog=1.0, head=False, a=1.0, closed=False):
        x0 = min(p[0] for p in pts) - M - 12
        y0 = min(p[1] for p in pts) - M - 12
        rel = tuple((int(round(p[0] - x0)), int(round(p[1] - y0))) for p in pts)
        q = int(round(max(0.0, min(1.0, prog)) * 100))
        if q > 0:
            self.add(('path', rel, color, width, q, head, closed), x0, y0, a)

    def img(self, name, x, y, w, h, crop=None, mode='', a=1.0):
        self.add(('img', str(name), int(w), int(h), crop, mode), x, y, a)

    def tag(self, kind, x, y, size=24, a=1.0):
        self.add(('tag', kind, size), x - M, y - M, a)
        return tag_size(kind, size)[0]

    def arrow(self, tip_x, tip_y, angle, length=130, height=65, color=ACCENT, a=1.0):
        """ブロック矢印。先端が (tip_x, tip_y)、向きは angle（度。0 で右向き、時計回り）。"""
        q = int(round(angle * 10)) % 3600
        rad = math.radians(q / 10.0)
        cx, cy = tip_x - math.cos(rad) * length / 2, tip_y - math.sin(rad) * length / 2
        n = 2 * (int(math.hypot(length * SS, height * SS) / 2) + 2 * SS) // SS
        self.add(('arrow', int(length), int(height), q, color), cx - n / 2, cy - n / 2, a)

    def fn(self, name, x, y, *params, a=1.0):
        self.add(('fn', name) + params, x, y, a)

    def badge(self, n, cx, cy, a=1.0, dia=40, on=True):
        self.circ(cx, cy, dia, fill=(AMBER if on else PANEL2), outline=(None if on else LINE), ow=2, a=a)
        self.text(str(n), cx, cy - dia * 0.29, size=int(dia * 0.58), color=('#1a1300' if on else TEXT2), w='B', a=a,
                  anchor='c')


def texts_of(ops):
    """表示リストの中の文字（text・textrot・tag）を並びの順に返す。画面の文字の検査に使う。"""
    return [k[1] for k, *_ in ops if k[0] in ('text', 'textrot', 'tag')]


@functools.lru_cache(None)
def background():
    im = Image.new('RGB', (W, H))
    top, bot = rgba(BG_TOP), rgba(BG_BOT)
    d = ImageDraw.Draw(im)
    for y in range(H):
        k = y / (H - 1)
        d.line((0, y, W, y), fill=tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))
    # ごく薄い方眼（製図用紙の気配）
    grid = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for x in range(0, W, 48):
        g.line((x, 0, x, H), fill=(255, 255, 255, 5 if x % 240 else 9))
    for y in range(0, H, 48):
        g.line((0, y, W, y), fill=(255, 255, 255, 5 if y % 240 else 9))
    im.paste(grid, (0, 0), grid)
    d = ImageDraw.Draw(im)
    d.rectangle((0, SUB_TOP, W, H), fill=rgba(BAND)[:3])
    d.line((0, SUB_TOP, W, SUB_TOP), fill=rgba('#16283d')[:3])
    return im


def raster(ops):
    im = background().copy()
    for key, x, y, a in ops:
        rgb, al = sprite(key)
        if a < 255:
            al = al.point(_LUT[a])
        im.paste(rgb, (x, y), al)
    return im

# __all__ は置かない: 場面コードの `from explainer_reel_kit.interactive.engine import *` で
# 公開の名前（色・部品・時間関数・Image など）がすべて使えるようにする。
