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

場面コードの無い場面は、既定の場面で描く: シーンの画像（説明図の PNG・撮影画像）を字幕帯の上にいっぱいに出す。
画像の無い場面（intro・outro など）は見出しと文のカード。
静止画は ``scenes/assets/`` と ``<scenes の親>/assets/`` から探す（engine.set_asset_dirs）。
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import engine
from . import spec as specmod
from .engine import (LINE, PANEL, SUB_TOP, TEAL, TEXT, TEXT2, TEXT3, W, Frame, LayoutError, asset_size, ramp,
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

IMAGE_BOX = (0, 0, W, SUB_TOP)   # 画像を置く範囲（字幕帯の上）
FADE = 0.4


def fit_box(src_w: int, src_h: int, box=IMAGE_BOX) -> tuple[int, int, int, int]:
    """縦横比を保って box に収める (x, y, w, h)。"""
    bx, by, bw, bh = box
    k = min(bw / src_w, bh / src_h)
    w, h = int(round(src_w * k)), int(round(src_h * k))
    return bx + (bw - w) // 2, by + (bh - h) // 2, w, h


def default_scene(f: Frame, t: float, T, sc: dict) -> None:
    """既定の場面。画像があれば字幕帯の上にいっぱいに（細線は縮小の割合で太らせる）、無ければ見出しと文のカード。"""
    a = ramp(t, sc["start"], FADE)
    if sc.get("image"):
        sw, sh = asset_size(sc["image"])
        x, y, w, h = fit_box(sw, sh)
        f.img(sc["image"], x, y, w, h, mode="auto", a=a)
        return
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
