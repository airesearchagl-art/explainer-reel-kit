"""画像の場所を決め、この実行で使うものを ``work/assets/`` にまとめる。

探す順（見つかった最初のもの）:

| image.source | 探す場所 |
|---|---|
| web | ``--assets-root`` ＞ 撮影素材のフォルダ（``<撮影素材のルート>/web/<reel id>``） |
| generated | ``--assets-root`` ＞ この実行の説明図（``work/diagram``） ＞ 台本のフォルダ |
| manual | ``--assets-root`` ＞ 台本のフォルダ ＞ 撮影素材のフォルダ |

- 見つからない web / generated の画像は「プレースホルダー」（スライドでは灰色の枠）。manual が無いのはエラー
- 文字だけのカード（``recipe_params.card``）のシーンは画像を探さない
- 使う画像と隣の ``<画像名>.marks.json`` を ``work/assets/<image.ref>`` に複製し、スライドにはそのフォルダを渡す
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AssetsError(Exception):
    """素材のフォルダの指定ミスなど、始めるべきでない状態。"""


@dataclass
class ImageEntry:
    id: str  # シーン id（outro の画像は "outro"）
    source: str
    ref: str
    path: Path | None = None
    status: str = "missing"  # found / placeholder / missing / text_card
    searched: list[str] = field(default_factory=list)

    def record(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "ref": self.ref, "status": self.status,
                "path": str(self.path) if self.path else None, "searched": self.searched}


@dataclass
class AssetPlan:
    images: list[ImageEntry]
    roots: dict[str, list[str]]

    @property
    def placeholders(self) -> list[ImageEntry]:
        return [i for i in self.images if i.status == "placeholder"]

    @property
    def missing_manual(self) -> list[ImageEntry]:
        return [i for i in self.images if i.status == "missing"]

    @property
    def found(self) -> list[ImageEntry]:
        return [i for i in self.images if i.status == "found"]

    def placeholder_text(self) -> str:
        return ", ".join(f"{i.id}（{i.source}: {i.ref}）" for i in self.placeholders)

    def record(self) -> dict[str, Any]:
        return {"roots": self.roots, "found": len(self.found), "placeholders": [i.id for i in self.placeholders],
                "images": [i.record() for i in self.images]}


def is_text_card(scene: dict[str, Any]) -> bool:
    card = (scene.get("recipe_params") or {}).get("card")
    return isinstance(card, dict) and isinstance(card.get("title"), str) and bool(card["title"].strip())


def _images(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any], bool]]:
    out = [(s["id"], s["image"], is_text_card(s)) for s in doc["scenes"]]
    if isinstance((doc.get("outro") or {}).get("image"), dict):
        out.append(("outro", doc["outro"]["image"], False))
    return out


def resolve_assets(doc: dict[str, Any], storyboard_dir: Path, *, captures_dir: Path | None,
                   diagram_dir: Path | None = None, assets_root: Path | None = None) -> AssetPlan:
    storyboard_dir = Path(storyboard_dir)
    if assets_root is not None:
        if not Path(assets_root).is_dir():
            raise AssetsError(f"--assets-root のフォルダがありません: {assets_root}（入力の誤りがないか確かめてください）")
        cands = {k: [Path(assets_root)] for k in ("web", "generated", "manual")}
    else:
        cap = [Path(captures_dir)] if captures_dir is not None else []
        dia = [Path(diagram_dir)] if diagram_dir is not None else []
        cands = {"web": cap, "generated": [*dia, storyboard_dir], "manual": [storyboard_dir, *cap]}
    entries = []
    for sid, img, card in _images(doc):
        e = ImageEntry(sid, img["source"], img["ref"])
        if card:
            e.status = "text_card"
            entries.append(e)
            continue
        for base in cands.get(e.source, []):
            p = base / e.ref
            e.searched.append(str(p))
            if p.is_file():
                e.path, e.status = p, "found"
                break
        if e.status != "found":
            e.status = "missing" if e.source == "manual" else "placeholder"
        entries.append(e)
    return AssetPlan(entries, {k: [str(p) for p in v] for k, v in cands.items()})


def stage_assets(plan: AssetPlan, dest: Path) -> Path:
    """使う画像（と注釈位置の記録）を dest/<image.ref> に複製する。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for e in plan.images:
        if e.path is None:
            continue
        target = dest / e.ref
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(e.path).resolve() != target.resolve():
            shutil.copy2(e.path, target)
        marks = Path(e.path).with_name(Path(e.path).stem + ".marks.json")
        tmarks = target.with_name(target.stem + ".marks.json")
        if marks.is_file() and marks.resolve() != tmarks.resolve():
            shutil.copy2(marks, tmarks)
    return dest
