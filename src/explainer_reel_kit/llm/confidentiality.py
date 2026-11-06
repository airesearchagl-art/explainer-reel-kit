"""社外秘の区分と、AI に送るときの関所。

- 区分は台本の ``reel.confidentiality``（``confidential`` / ``general``）。読むのは
  :func:`explainer_reel_kit.storyboard.confidentiality` だけ（未記入・1.0.0・読めない値は confidential）
- **confidential → この PC だけ**: 接続先が ``127.0.0.0/8``・``::1``・``localhost`` でなければ送らない（LAN でも送らない）。
  確かめるのは ``LLMClient`` そのもので、**作るときと、毎回送る直前**。設定・引数・環境変数で外す方法は無い。
  ちょうど ``general`` でない値（区分を言わずに作ったクライアントも）は、すべて confidential として扱う
- general → ``route: local``（この PC と LAN）。キットにクラウドの AI の接続（``route: cloud``）と API キーは無い
"""

from __future__ import annotations

from typing import Any

CONFIDENTIAL = "confidential"
GENERAL = "general"
VALUES = (CONFIDENTIAL, GENERAL)


def normalize(value: Any) -> str:
    """ちょうど general のときだけ general。ほか（None・書き間違い・知らない値）はすべて confidential。"""
    return GENERAL if value == GENERAL else CONFIDENTIAL


def of_storyboard(doc: Any) -> str:
    """台本の区分（読むのは storyboard.confidentiality だけ）。"""
    from .. import storyboard as sb

    return normalize(sb.confidentiality(doc))
