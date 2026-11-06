"""「この PC の外へ出ないか」の確かめ（手元の LLM の段で使う）。

- LLM の ``base_url`` がこの PC（127.0.0.0/8・::1・localhost）か。LAN でも外とみなす
- 台本の ``capture.url`` がこの PC か

設定を読むだけで、何も実行しない。``erkit make`` の確かめ（docs/design/make.md）とは別に、
``erkit draft --offline`` が使う。
"""

from __future__ import annotations

import urllib.parse
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .config import host_kind
from .errors import LLMToolError


class OfflineError(LLMToolError):
    """--offline: a setting would use the network. Nothing was run."""

    exit_code = 1


@dataclass(frozen=True)
class OfflineCheck:
    item: str
    value: str
    ok: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_loopback_url(url: str | None) -> bool:
    if not url:
        return False
    host = urllib.parse.urlsplit(url).hostname
    return bool(host) and host_kind(host) == "loopback"


def url_check(item: str, url: str | None) -> OfflineCheck:
    if is_loopback_url(url):
        return OfflineCheck(item, str(url), True)
    return OfflineCheck(item, str(url), False, "この PC（127.0.0.1 / ::1 / localhost）以外を指しています。ネットワークが要ります")


def storyboard_url_checks(doc: dict[str, Any]) -> list[OfflineCheck]:
    out = []
    for scene in doc.get("scenes") or []:
        capture = scene.get("capture") if isinstance(scene, dict) else None
        if isinstance(capture, dict) and "url" in capture:
            out.append(url_check(f"{scene.get('id')}.capture.url", capture.get("url")))
    return out




def fixed_check(item: str, value: str) -> OfflineCheck:
    return OfflineCheck(item, value, True)


def require(checks: Iterable[OfflineCheck]) -> list[dict[str, Any]]:
    """The checks as records; OfflineError listing every failed one (nothing has been run)."""
    checks = list(checks)
    failed = [c for c in checks if not c.ok]
    if failed:
        lines = [f"{c.item} = {c.value}: {c.reason}" for c in failed]
        raise OfflineError("--offline: ネットワークを使う設定があるため、何もせずに止めました:\n  - " + "\n  - ".join(lines))
    return [c.as_dict() for c in checks]
