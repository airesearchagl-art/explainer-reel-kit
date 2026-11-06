"""撮影用のページを、この PC だけで配信する（``erkit capture --serve <フォルダ>``）。

台本の ``capture.url`` に ``http://localhost:<番号>/…`` か ``http://127.0.0.1:<番号>/…`` と書いておくと、
``--serve`` のときはその先頭を、ここで立てたサーバー（127.0.0.1、空いている番号）に置き換えて撮る。
"""
from __future__ import annotations

import contextlib
import functools
import http.server
import threading
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def is_local_url(url: str) -> bool:
    """この PC の中だけで開ける URL か（file:// と、localhost・127.0.0.1・::1）。"""
    parts = urlsplit(url)
    if parts.scheme == "file":
        return True
    return parts.scheme in ("http", "https") and (parts.hostname or "") in LOCAL_HOSTS


def rebase_local(url: str, base: str) -> str:
    """ローカルの URL の先頭（scheme と host:port）を base に置き換える。ローカルでなければそのまま。"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or (parts.hostname or "") not in LOCAL_HOSTS:
        return url
    b = urlsplit(base)
    return urlunsplit((b.scheme, b.netloc, parts.path or "/", parts.query, parts.fragment))


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # 撮影の表示を汚さない
        pass


@contextlib.contextmanager
def serve_dir(directory: Path) -> Iterator[str]:
    """フォルダを 127.0.0.1 の空いている番号で配信し、その先頭の URL（末尾 /）を返す。"""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"配信するフォルダがありません: {directory}")
    handler = functools.partial(_QuietHandler, directory=str(directory.resolve()))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()
        srv.server_close()
