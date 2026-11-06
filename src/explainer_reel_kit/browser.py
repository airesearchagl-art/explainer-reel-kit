"""Playwright のブラウザを起動する（撮影と説明図の段が共通で使う）。

使う順: ``--executable``（実行ファイル）＞ ``--channel``（msedge / chrome、インストール済みのもの）＞
Playwright の Chromium（``python -m playwright install chromium`` で入れたもの）。
"""
from __future__ import annotations

from typing import Any

INSTALL_HINT = ("Playwright のブラウザを起動できません。`python -m playwright install chromium` で入れるか、"
                "`--channel msedge`（Windows 標準の Edge）を付けてください")


class BrowserError(RuntimeError):
    """ブラウザを起動できない。"""


def launch(pw, channel: str | None = None, executable: str | None = None, headed: bool = False):
    kw: dict[str, Any] = {"headless": not headed}
    if executable:
        kw["executable_path"] = executable
    elif channel:
        kw["channel"] = channel
    try:
        return pw.chromium.launch(**kw)
    except Exception as e:  # 入っていない・起動できない
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise BrowserError(f"{INSTALL_HINT}（{first}）") from e


def sync_playwright():
    """playwright を import する（無ければ分かる言葉で止める）。"""
    try:
        from playwright.sync_api import sync_playwright as sp
    except ImportError as e:  # pragma: no cover - 依存に入っているので通常は起きない
        raise BrowserError("Playwright が入っていません。`pip install -e .` をやり直してください") from e
    return sp()
