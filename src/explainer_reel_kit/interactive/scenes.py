# -*- coding: utf-8 -*-
"""場面コードの読み込みと、既定の場面。

場面コードは台本ごとに手で書き、台本のフォルダの ``scenes/`` に置く（台本と同じく reels/ の下。.gitignore で外してある）。
ツールは**自分の台本のフォルダのコードだけ**を読み込んで実行する（人から受け取ったコードを読み込む用途は想定しない。
:func:`find_scenes_dir` は台本のフォルダの下だけを探す）。

置き方（どちらでも、混ぜてもよい）:

- ``scenes/<場面 id>.py`` に ``def scene(f, t, T)``（f: 表示リスト Frame、t: 秒、T: 問い合わせ口 Timeline）
- ``scenes/index.py`` に ``SCENES = {'<場面 id>': 関数, …}``（いくつかの場面を 1 つのファイルにまとめるとき）。
  任意で ``subtitle(f, frame, T)``（字幕の描き方を変える）、``AT_WEIGHTS``（T.at の推定の重みを変える）
- ``scenes/scenes.yaml``: Python を書かずに、場面ごとに「型・中身・動くきっかけ」を書く（spec.py）。
  優先順位は Python の場面コード ＞ scenes.yaml ＞ 既定の場面

場面コードの無い場面は、既定の場面で描く: 台本のシーンは slides と同じ配置で、見出し・画像（説明図の PNG・撮影画像）・
画面テキスト・来歴ラベル（実キャプチャ／説明用再構成図。撮影前は 撮影前（仮））・注釈（赤枠・矢印。slides と同じ段落）。
画像の無い場面（intro・outro など）は見出しと文のカード。
静止画は ``scenes/assets/`` と ``<scenes の親>/assets/`` から探す（engine.set_asset_dirs）。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import engine
from . import spec as specmod
from .engine import (ACCENT, LINE, PANEL, PANEL2, TEAL, TEXT, TEXT2, TEXT3, W, Frame, LayoutError, asset_size, ramp,
                     wrap_text)

SceneFn = Callable[[Frame, float, object], None]
INDEX_NAME = "index.py"


class SceneError(RuntimeError):
    """場面コードを読み込めない・知らない場面 id など。"""


@dataclass
class SceneSet:
    dir: Path | None = None
    funcs: dict[str, SceneFn] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)   # 場面 id → どこから（index.py / <id>.py / scenes.yaml / default）
    subtitle: Callable | None = None
    at_weights: dict | None = None
    files: list[Path] = field(default_factory=list)          # 読み込んだ .py・scenes.yaml（ハッシュの対象）
    spec_file: Path | None = None                            # scenes.yaml
    specs: dict[str, dict] = field(default_factory=dict)     # scenes.yaml で描く場面 id → 指定
    shadowed: list[str] = field(default_factory=list)        # scenes.yaml にあるが Python の場面コードが先の場面
    compiled: dict = field(default_factory=dict)             # 場面 id → spec.CompiledScene（compile の後）

    def compile(self, T) -> None:
        """scenes.yaml の場面を部品に組み立て、きっかけと文字のはみ出しを確かめる（描く前に止める）。"""
        for sid, sp in self.specs.items():
            cs = specmod.compile_scene(T, sid, sp)
            specmod.dry_run(T, cs)
            self.compiled[sid] = cs
            self.funcs[sid] = cs.draw

    def record(self) -> dict:
        return {"dir": str(self.dir) if self.dir else None, "sources": dict(self.sources),
                "subtitle": "scenes" if self.subtitle else "default", "files": [str(p) for p in self.files],
                "spec": str(self.spec_file) if self.spec_file else None, "spec_shadowed_by_python": list(self.shadowed)}


def _import_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SceneError(f"場面コードを読み込めません: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # 場面コードの誤りは、どのファイルかを添えて止める
        sys.modules.pop(name, None)
        raise SceneError(f"場面コードの読み込みで失敗しました（{path.name}）: {type(e).__name__}: {e}") from e
    return mod


_LOADED_DIR: Path | None = None   # いま sys.path に入れている場面コードのフォルダ


def _forget_scenes_dir(d: Path) -> None:
    """前に読んだ場面コードのフォルダのモジュールを捨て、sys.path から外す（別の台本の scenes_a.py などと取り違えない）。"""
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f:
            try:
                if Path(f).resolve().parent == d:
                    del sys.modules[name]
            except OSError:
                pass
    while str(d) in sys.path:
        sys.path.remove(str(d))


def asset_dirs_for(scenes_dir: Path | None, extra: list[Path] | None = None) -> list[Path]:
    dirs: list[Path] = []
    if scenes_dir is not None:
        dirs += [scenes_dir / "assets", scenes_dir.parent / "assets"]
    return dirs + list(extra or [])


def load_scenes(scenes_dir: Path | None, scene_ids: list[str], *, extra_asset_dirs: list[Path] | None = None) -> SceneSet:
    """scenes_dir の場面コードを読み込む。無いフォルダ・None なら、すべて既定の場面。"""
    global _LOADED_DIR
    engine.set_asset_dirs(asset_dirs_for(scenes_dir, extra_asset_dirs))
    out = SceneSet(dir=scenes_dir)
    new_dir = Path(scenes_dir).resolve() if scenes_dir is not None and Path(scenes_dir).is_dir() else None
    if _LOADED_DIR is not None and _LOADED_DIR != new_dir:
        _forget_scenes_dir(_LOADED_DIR)
        _LOADED_DIR = None
    if new_dir is None:
        out.sources = {sid: "default" for sid in scene_ids}
        return out
    scenes_dir = new_dir
    out.dir = scenes_dir
    _LOADED_DIR = scenes_dir
    if str(scenes_dir) not in sys.path:
        sys.path.insert(0, str(scenes_dir))   # 場面コードどうしの import（from scenes_a import …）のため
    index = scenes_dir / INDEX_NAME
    if index.is_file():
        mod = _import_file(index, "er_scenes_index")
        out.files.append(index)
        table = getattr(mod, "SCENES", None)
        if not isinstance(table, dict):
            raise SceneError(f"{index} に SCENES = {{'<場面 id>': 関数}} がありません")
        unknown = [k for k in table if k not in scene_ids]
        if unknown:
            raise SceneError(f"{index} の SCENES に中間データに無い場面 id があります: {unknown}（場面: {scene_ids}）")
        for k, fn in table.items():
            if not callable(fn):
                raise SceneError(f"{index} の SCENES['{k}'] が関数ではありません")
            out.funcs[k] = fn
            out.sources[k] = INDEX_NAME
        out.subtitle = getattr(mod, "subtitle", None)
        out.at_weights = getattr(mod, "AT_WEIGHTS", None)
    for sid in scene_ids:
        if sid in out.funcs:
            continue
        p = scenes_dir / f"{sid}.py"
        if p.is_file():
            mod = _import_file(p, f"er_scene_{sid.replace('-', '_').replace('.', '_')}")
            out.files.append(p)
            fn = getattr(mod, "scene", None)
            if not callable(fn):
                raise SceneError(f"{p} に def scene(f, t, T) がありません")
            out.funcs[sid] = fn
            out.sources[sid] = p.name
        else:
            out.sources[sid] = "default"
    # 読み込まれた補助のモジュール（scenes_a.py など）もハッシュの対象にする
    for p in sorted(scenes_dir.glob("*.py")):
        if p not in out.files:
            out.files.append(p)
    spec_path = scenes_dir / specmod.SPEC_NAME
    if spec_path.is_file():
        doc = specmod.load_spec(spec_path)
        unknown = [k for k in doc["scenes"] if k not in scene_ids]
        if unknown:
            raise specmod.SpecError(f"{spec_path.name} に中間データに無い場面 id があります: {unknown}（場面: {scene_ids}）")
        out.spec_file = spec_path
        out.files.append(spec_path)
        for sid, sp in doc["scenes"].items():
            if sid in out.funcs:          # Python の場面コードが先
                out.shadowed.append(sid)
                continue
            out.specs[sid] = sp
            out.sources[sid] = specmod.SPEC_NAME
    return out


# ---------------------------------------------------------------- 既定の場面
#
# 台本のシーン（中間データの場面に heading がある）は slides（deck/builder.py の _scene_slide）と同じ配置で描く。
# slides の 13.333×7.5 インチを 1920×1080 に当てる（1 インチ ＝ 144 px）。本家の interactive と同じ値:
#   見出し（上）→ 画像（その下）→ 来歴ラベル（画像の右下の外）。字幕帯（y 940 から）と重ねない。
#   画面テキスト（on_screen_text）は interactive では出さない（slides の位置だと字幕の帯と重なるため）。
#   出る時刻は slides のアニメーションのまま計算する（画面テキストの段も時刻の計算には数える）。

HEAD_X, HEAD_CENTER_Y = 72, 104          # 見出し: x 72、縦の中心 104（slides の HEAD_BOX）
HEAD_BOX = (HEAD_X, HEAD_CENTER_Y - 44, 1776, 88)
IMAGE_BOX = (72, 180, 1776, 724)         # 画像: 縦横比を保って収める（slides の IMAGE_BOX。区分の表示の行を残す）
LABEL_RIGHT, LABEL_TOP = 1848, 912       # 区分の表示: 右端 1848・上端 912、右寄せ（slides の LABEL_BOX）
LABEL_SIZE = 20
HEAD_SIZES = (56, 52, 48, 44, 40, 36)    # 56px・太字。入らなければ 36px まで縮める
BOX_LINE = 9                             # 赤枠の線（slides の 4.5pt ＝ 9px。線は縁の中心）
ARROW_LEN, ARROW_H = 130, 65             # 矢印（slides の 0.9 × 0.45 インチ）
FADE = 0.4
HEAD_FADE, IMAGE_FADE = 0.5, 0.7   # slides の deck.recipes の FADE・IMAGE_FADE と同じ
BOX_FADE, BOX_EXIT, BLINK, ARROW_FADE = 0.4, 0.3, 0.6, 0.3
DEFAULT_LABEL = "説明用再構成図"           # 来歴の分からない画像（annotate.DEFAULT_LABEL と同じ）


def fit_box(src_w: int, src_h: int, box=IMAGE_BOX) -> tuple[int, int, int, int]:
    """縦横比を保って box に収める (x, y, w, h)。"""
    bx, by, bw, bh = box
    k = min(bw / src_w, bh / src_h)
    w, h = int(round(src_w * k)), int(round(src_h * k))
    return bx + (bw - w) // 2, by + (bh - h) // 2, w, h


def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _fit_size(text: str, weight: str, sizes, maxw: float) -> int | None:
    for size in sizes:
        if engine.tw(text, weight, size) <= maxw:
            return size
    return None


def _heading(f: Frame, text: str, a: float, box=HEAD_BOX) -> None:
    """見出し（太字・左寄せ・枠の上下の中央）。1 行に入らなければ小さくし、それでも入らなければ 2 行。"""
    if not text:
        return
    x, y, w, h = box
    size = _fit_size(text, "B", HEAD_SIZES, w)
    if size is not None:
        f.text(text, x, y + (h - size) / 2, size=size, w="B", a=a, maxw=w)
        return
    # 36px でも 1 行に入らなければ 2 行（縦の中心は同じ。画像の枠 y 180 より上に収める）
    f.text_box(text, x, y - 12, w, h + 24, size=HEAD_SIZES[-1], weight="B", a=a, valign="c")


def draw_label(f: Frame, label: str, right: float = LABEL_RIGHT, top: float = LABEL_TOP) -> None:
    """区分の表示（slides の Provenance Label: 20px、控えめな色、右寄せ）。消す設定は無い。"""
    f.text(label, right, top, size=LABEL_SIZE, color=TEXT3, anchor="r")


def _view_at(t: float, sc: dict) -> dict | None:
    """いまの表示範囲（元の画像に対する 0〜1）。zoom: per_mark は枠の範囲へ段落の始まりから移る。"""
    views = [a for a in sc.get("annotations") or [] if a.get("view")]
    if not views:
        return sc.get("view")
    cur = views[0]["view"]
    for a in views[1:]:
        m0 = a.get("morph_sec", a["at_sec"])
        if t < m0:
            break
        k = _ease((t - m0) / max(1e-6, a.get("morph_dur_sec", 0.0)))
        cur = {key: cur[key] + (a["view"][key] - cur[key]) * k for key in ("x", "y", "w", "h")}
    return cur


def _placed(image: str, view: dict | None, box) -> tuple[tuple[int, int, int, int], tuple | None, dict]:
    """画像（と拡大の範囲）を box に置いた矩形・切り抜き・範囲。"""
    sw, sh = asset_size(image)
    v = view or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    if view is None:
        return fit_box(sw, sh, box), None, v
    l, tp = int(round(v["x"] * sw)), int(round(v["y"] * sh))
    r, b = max(l + 1, int(round((v["x"] + v["w"]) * sw))), max(tp + 1, int(round((v["y"] + v["h"]) * sh)))
    r, b = min(r, sw), min(b, sh)
    v = {"x": l / sw, "y": tp / sh, "w": (r - l) / sw, "h": (b - tp) / sh}
    return fit_box(r - l, b - tp, box), (l, tp, r, b), v


def _to_screen(rect, v: dict, p: dict) -> tuple[float, float]:
    x, y, w, h = rect
    return x + (p["x"] - v["x"]) / v["w"] * w, y + (p["y"] - v["y"]) / v["h"] * h


def _box_screen(rect, v, b) -> tuple[float, float, float, float]:
    x0, y0 = _to_screen(rect, v, {"x": b["x"], "y": b["y"]})
    x1, y1 = _to_screen(rect, v, {"x": b["x"] + b["w"], "y": b["y"] + b["h"]})
    return x0, y0, x1 - x0, y1 - y0


def _blink(t: float, t0: float) -> float:
    """slides の点滅（1 回、0.6 秒）: 前半は隠れ、後半に戻る。"""
    if t0 <= t < t0 + BLINK / 2:
        return 0.0
    return 1.0


def _annotations(f: Frame, t: float, sc: dict, rect, v: dict, image: str | None, box) -> None:
    """台本の注釈（赤枠・矢印）を、記録の時刻（slides と同じ段落）に描く。"""
    anns = sc.get("annotations") or []
    for k, a in enumerate(anns):
        if t < a.get("morph_sec", a["at_sec"]):
            continue
        if a["kind"] == "box":
            if "morph_sec" in a and t < a["at_sec"]:   # per_mark: 前の枠の位置から、この枠の位置へ動く
                prev = anns[k - 1]
                pr, _, pv = _placed(image, prev["view"], box)
                nr, _, nv = _placed(image, a["view"], box)
                p0, p1 = _box_screen(pr, pv, prev["box"]), _box_screen(nr, nv, a["box"])
                e = _ease((t - a["morph_sec"]) / max(1e-6, a.get("morph_dur_sec", 0.0)))
                x0, y0, w, h = (p0[i] + (p1[i] - p0[i]) * e for i in range(4))
                f.rr(x0, y0, w, h, r=0, outline=ACCENT, ow=BOX_LINE)
                continue
            if a.get("until_sec") is not None and t >= a["until_sec"]:
                nxt = anns[k + 1] if k + 1 < len(anns) else None
                if nxt is not None and "morph_sec" in nxt:   # per_mark: 次の枠へ動いて替わる
                    continue
                alpha = 1.0 - ramp(t, a["until_sec"], BOX_EXIT)
            else:
                alpha = 1.0 if "morph_sec" in a else ramp(t, a["at_sec"], BOX_FADE)
            alpha *= _blink(t, a["at_sec"] + (0.0 if "morph_sec" in a else BOX_FADE))
            if alpha <= 0:
                continue
            x0, y0, w, h = _box_screen(rect, v, a["box"])
            f.rr(x0, y0, w, h, r=0, outline=ACCENT, ow=BOX_LINE, a=alpha)
        else:
            sx, sy = _to_screen(rect, v, a["start"])
            ex, ey = _to_screen(rect, v, a["end"])
            p = _ease((t - a.get("move_sec", a["at_sec"])) / max(1e-6, a.get("move_dur_sec", 0.0)))
            ang = math.degrees(math.atan2(ey - sy, ex - sx)) if (ex, ey) != (sx, sy) else 0.0
            f.arrow(sx + (ex - sx) * p, sy + (ey - sy) * p, ang, ARROW_LEN, ARROW_H, a=ramp(t, a["at_sec"], ARROW_FADE))


def _card(f: Frame, card: dict, box, a: float) -> None:
    """文字だけのカード（slides の Text Card: 表示名・説明・プラットフォーム）。来歴ラベルは出さない。"""
    x, y, w, h = box
    f.rr(x, y, w, h, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
    inner = w - 2 * 115
    paras = [(card["title"], 88, "B", TEXT)] + ([(card["text"], 52, "R", TEXT)] if card.get("text") else []) + \
            ([(card["meta"], 40, "R", TEXT2)] if card.get("meta") else [])
    for k in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
        rows = [(wrap_text(s, wt, int(sz * k), inner), int(sz * k), wt, c) for s, sz, wt, c in paras]
        need = sum(int(sz * 1.3) * len(r) for r, sz, _, _ in rows) + 28 * (len(rows) - 1)
        if need <= h - 60:
            break
    else:
        raise LayoutError(f"文字だけのカードが枠に入りません: {card['title']}")
    yy = y + (h - need) / 2
    for r, sz, wt, c in rows:
        for line in r:
            f.text(line, x + 115, yy, size=sz, w=wt, color=c, a=a, maxw=inner)
            yy += int(sz * 1.3)
        yy += 28


def _placeholder(f: Frame, ph: dict, box, a: float) -> tuple[int, int, int, int]:
    """撮影前の仮の枠（slides の Image Placeholder: 16:9 の枠に「撮影予定: <画像>」）。"""
    x, y, w, h = fit_box(16, 9, box)
    f.rr(x, y, w, h, r=0, fill=PANEL2, outline=TEXT3, ow=3, dash=14, a=a)
    msg = f"{ph.get('reason') or '撮影予定'}: {ph.get('ref') or ''}"
    size = _fit_size(msg, "R", (32, 28, 24, 20), w - 48) or 20
    lines = wrap_text(msg, "R", size, w - 48)
    f.text_box(lines, x + 24, y, w - 48, h, size=size, color=TEXT2, a=a, align="c", valign="c")
    return x, y, w, h


def _slide_scene(f: Frame, t: float, sc: dict) -> None:
    """台本のシーン（slides と同じ配置・同じ順）: 見出し → 画像 → 画面テキスト、来歴ラベル、注釈。"""
    start = sc["start"]
    ap = sc.get("appear") or {}
    _heading(f, sc.get("heading") or sc.get("title") or "", ramp(t, ap.get("heading", start), HEAD_FADE))
    box = IMAGE_BOX   # 画面テキストは出さない（字幕の帯と重なるため）。画像の枠はいつも同じ
    ai = ramp(t, ap.get("image", start), IMAGE_FADE)
    card, image, ph = sc.get("card"), sc.get("image"), sc.get("placeholder")
    if card:
        _card(f, card, box, ai)
    elif image:
        view = _view_at(t, sc)
        rect, crop, v = _placed(image, view, box)
        f.img(image, rect[0], rect[1], rect[2], rect[3], crop=crop, mode="auto", a=ai)
        _annotations(f, t, sc, rect, v, image, box)
    elif ph is not None:
        rect = _placeholder(f, ph, box, ai)
        _annotations(f, t, sc, rect, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, None, box)
    if not card and (image or ph is not None):
        draw_label(f, sc.get("label") or DEFAULT_LABEL)


def _body_rows(body: list[str], maxw: float, maxh: float, sizes=(40, 32)):
    for k in (1.0, 0.9, 0.8, 0.7, 0.6):
        rows = []
        for i, para in enumerate(body):
            size, color = (int(sizes[0] * k), TEXT) if i == 0 else (int(sizes[1] * k), TEXT2)
            rows += [(line, size, color, i) for line in wrap_text(para, "R", size, maxw)]
        height = sum(int(s * 1.5) for _, s, _, _ in rows) + 18 * (len(body) - 1)
        if height <= maxh:
            return rows, height
    return None, None


def _summary_with_image(f: Frame, t: float, sc: dict) -> None:
    """outro に画像があるとき（slides の outro: 左に見出しと文、右に画像）。画像には来歴ラベルを添える。"""
    a = ramp(t, sc["start"], FADE)
    _heading(f, sc.get("title") or "", a, box=(HEAD_X, HEAD_CENTER_Y - 44, 820, 88))
    rows, _ = _body_rows(sc.get("body") or [], 820, IMAGE_BOX[3])
    if rows is None:
        raise LayoutError(f"{sc['id']}: 既定の場面の文が左の欄に入りません（文を短くするか、場面コードを書く）")
    y, prev = IMAGE_BOX[1], 0
    for line, size, color, i in rows:
        if i != prev:
            y += 18
            prev = i
        f.text(line, 72, y, size=size, color=color, a=a * ramp(t, sc["start"] + 0.2 * i, FADE), maxw=820)
        y += int(size * 1.5)
    box = (936, IMAGE_BOX[1], 912, IMAGE_BOX[3])
    if sc.get("image"):
        rect, crop, _ = _placed(sc["image"], None, box)
        f.img(sc["image"], rect[0], rect[1], rect[2], rect[3], mode="auto", a=ramp(t, sc["start"] + 0.3, IMAGE_FADE))
    else:
        _placeholder(f, sc["placeholder"], box, a)
    draw_label(f, sc.get("label") or DEFAULT_LABEL)


def default_scene(f: Frame, t: float, T, sc: dict) -> None:
    """既定の場面。

    - 台本のシーン（heading がある）・画像だけの場面: slides と同じ配置（見出し・画像・画面テキスト・来歴ラベル・注釈）
    - 画像と文がある場面（outro）: 左に見出しと文、右に画像と来歴ラベル
    - 画像の無い場面（intro・outro）: 見出しと文のカード
    画像には来歴ラベルを必ず出す（記録が無ければ 説明用再構成図。撮影前は 撮影前（仮）。文字だけのカードは出さない）。
    """
    has_visual = bool(sc.get("image") or sc.get("placeholder") is not None)
    if "heading" in sc or sc.get("card") or (has_visual and not sc.get("body")):
        _slide_scene(f, t, sc)
        return
    if has_visual:
        _summary_with_image(f, t, sc)
        return
    a = ramp(t, sc["start"], FADE)
    title = sc.get("title") or ""
    f.rr(96, 60, 8, 62, r=4, fill=TEAL, a=a)
    if title:
        f.text(title, 126, 67, size=48, w="B", a=a, maxw=W - 126 - 96)
    f.rr(96, 142, 1728, 2, r=0, fill=LINE, a=a)
    body = sc.get("body") or []
    if not body:
        return
    x0, maxw = 136, W - 272
    rows = []   # (行, 大きさ, 色, 段落の番号)
    for i, para in enumerate(body):
        size, color = (40, TEXT) if i == 0 else (32, TEXT2)
        rows += [(line, size, color, i) for line in wrap_text(para, "R", size, maxw)]
    height = sum(int(s * 1.5) for _, s, _, _ in rows) + 18 * (len(body) - 1) + 2 * 36
    if 196 + height > 860:
        raise LayoutError(f"{sc['id']}: 既定の場面の文がカードに入りません（文を短くするか、場面コードを書く）")
    f.rr(96, 196, W - 192, height, r=16, fill=PANEL, outline=LINE, ow=2, a=a)
    y, prev = 196 + 36, 0
    for line, size, color, i in rows:
        if i != prev:
            y += 18
            prev = i
        f.text(line, x0, y, size=size, color=color, a=a * ramp(t, sc["start"] + 0.2 * i, FADE), maxw=maxw)
        y += int(size * 1.5)


def draw_credit(f: Frame, T) -> None:
    """ナレーション音声のクレジット。最後の場面の左下に常に出す。"""
    credit = (T.meta or {}).get("credit")
    if credit:
        f.text(f"ナレーション音声: {credit}", 96, 896, size=24, color=TEXT3, maxw=W - 192)
