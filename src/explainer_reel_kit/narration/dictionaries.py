"""読み辞書を名前かパスで選ぶ。

- パス（/ か \\ を含む、または .yaml / .yml で終わる）: そのファイル
- 名前: 今のフォルダの dictionaries/<名前>.yaml ＞ キットのフォルダの dictionaries/<名前>.yaml
- 既定では辞書を使わない（台本の分野に合う辞書を config/kit.yaml の voice.dictionaries か --dictionary で選ぶ）
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..config import KIT_ROOT
from .errors import InputError
from .textproc import PronunciationDictionary

DICT_DIR = "dictionaries"


def resolve_dictionary(spec: str, cwd: Path | None = None) -> Path:
    s = spec.strip()
    if "/" in s or "\\" in s or s.lower().endswith((".yaml", ".yml")):
        p = Path(s)
        if not p.is_file():
            raise InputError(f"読み辞書が見つかりません: {p}")
        return p
    for base in (cwd or Path.cwd(), KIT_ROOT):
        p = base / DICT_DIR / f"{s}.yaml"
        if p.is_file():
            return p
    raise InputError(f"読み辞書 '{s}' が見つかりません（dictionaries/{s}.yaml を置くか、ファイルのパスを指定してください）。"
                     f" 使えるもの: {', '.join(available_dictionaries(cwd)) or 'なし'}")


def available_dictionaries(cwd: Path | None = None) -> list[str]:
    names: set[str] = set()
    for base in (cwd or Path.cwd(), KIT_ROOT):
        d = base / DICT_DIR
        if d.is_dir():
            names.update(p.stem for p in d.glob("*.yaml"))
    return sorted(names)


def load_dictionaries(specs: Sequence[str], cwd: Path | None = None) -> tuple[PronunciationDictionary, list[Path]]:
    paths = [resolve_dictionary(s, cwd) for s in specs]
    return PronunciationDictionary.merge([PronunciationDictionary.load(p) for p in paths]), paths
