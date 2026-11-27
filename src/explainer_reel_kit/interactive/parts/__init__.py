# -*- coding: utf-8 -*-
"""場面の部品（scenes.yaml の型）。

- 場面コード（Python）から使う道具: ``Table``（行・列は見出しの文字で指定）・``card_text``（段階 1、legacy.py）
- scenes.yaml の型（PART_TYPES）: 型の名前 → 部品のクラス。動きの名前はモーション見本帳の見本の id（motion.py）

型の一覧と見本帳との対応は interactive/README.md の「部品の一覧」。
"""
from __future__ import annotations

from .legacy import Table, card_text  # noqa: F401  （段階 1 からの場面コードの import をそのまま）

from . import callout, cards, header, image, number, table  # noqa: E402

PART_TYPES = {cls.TYPE: cls for mod in (header, cards, table, number, image, callout)
              for cls in mod.PARTS}

__all__ = ["PART_TYPES", "Table", "card_text"]
