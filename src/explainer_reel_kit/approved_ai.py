"""社内で認められた AI の許可リスト（``config/approved_ai.yaml``）の読み込みと検証。

区分の 3 つ目の段: 台本が ``confidential`` でも、所属先が社外秘の扱いを認めた AI（このリストに載った AI）なら、
台本・説明図づくりに使ってよい。詳しくは docs/guide/confidentiality.md。

- **書くのは人だけ**。エージェントはこのファイルを書き換えない。リストに無い AI は認められていない
- ファイルが無い・``approved`` が空のときは、今までと同じ決まり（クラウドで動くエージェントは confidential で止まる）
- 1 項目: ``id``・``name``・``kind``（``chat``／``agent``）・``approved_on``（YYYY-MM-DD）・``basis``（規程や申請の名前）・
  ``allows``（扱ってよい区分。``[confidential]``）・``notes``（任意）
- キットがこのリストで変えるのは ``erkit doctor`` の表示だけ。撮影・説明図・ナレーション・通し生成の区分の確かめ
  （この PC の中だけ）は、リストに何が載っていても変わらない
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from .config import KIT_ROOT

CONFIG_RELPATH = Path("config") / "approved_ai.yaml"
KINDS = ("chat", "agent")
ALLOWS = ("confidential",)
FIELDS = ("id", "name", "kind", "approved_on", "basis", "allows", "notes")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ApprovedAIError(ValueError):
    """許可リストが読めない・形が違う。"""

    def __init__(self, path: Path | None, problems: list[str]):
        self.path = path
        self.problems = problems
        super().__init__(f"{path or 'approved_ai.yaml'}: " + " / ".join(problems))


@dataclass(frozen=True)
class ApprovedAI:
    id: str
    name: str
    kind: str
    approved_on: str
    basis: str
    allows: tuple[str, ...]
    notes: str = ""

    def allows_confidential(self) -> bool:
        return "confidential" in self.allows


@dataclass
class ApprovedList:
    entries: dict[str, ApprovedAI] = field(default_factory=dict)
    path: Path | None = None
    exists: bool = False

    def get(self, ai_id: str | None) -> ApprovedAI | None:
        return self.entries.get(ai_id) if ai_id else None

    def ids(self) -> list[str]:
        return list(self.entries)

    def agent_allowed(self, ai_id: str) -> bool:
        """``ai_id`` のエージェントが confidential の台本・資料を扱ってよいか（kind agent で allows に confidential）。"""
        entry = self.get(ai_id)
        return bool(entry and entry.kind == "agent" and entry.allows_confidential())


def _date_text(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value  # YAML の日付は date で読まれる


def validate(data: Any) -> list[str]:
    """許可リストの形の検査。戻り値は誤りの一覧（空なら合格）。空のファイル（None）は合格。"""
    if data is None:
        return []
    if not isinstance(data, dict):
        return ["最上位は version と approved のオブジェクトにしてください"]
    errs: list[str] = []
    unknown_top = sorted(set(data) - {"version", "approved"})
    if unknown_top:
        errs.append(f"知らない項目 {', '.join(map(str, unknown_top))}")
    if data.get("version") != 1:
        errs.append("version は 1 です")
    items = data.get("approved")
    if items is None:
        return errs
    if not isinstance(items, list):
        return errs + ["approved は項目のリストにしてください（無ければ approved: []）"]
    seen: set[str] = set()
    for i, item in enumerate(items):
        where = f"approved[{i}]"
        if not isinstance(item, dict):
            errs.append(f"{where}: 項目はオブジェクトにしてください")
            continue
        unknown = sorted(set(map(str, item)) - set(FIELDS))
        if unknown:
            errs.append(f"{where}: 知らない項目 {', '.join(unknown)}")
        ai_id = item.get("id")
        if not isinstance(ai_id, str) or not ID_PATTERN.match(ai_id) or len(ai_id) > 64:
            errs.append(f"{where}: id は英小文字・数字・- です（例 github-copilot）")
        else:
            where = f"approved[{i}]（{ai_id}）"
            if ai_id in seen:
                errs.append(f"{where}: id が重複しています")
            seen.add(ai_id)
        for key in ("name", "basis"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errs.append(f"{where}: {key} を書いてください")
        if item.get("kind") not in KINDS:
            errs.append(f"{where}: kind は {' / '.join(KINDS)} のどちらかです（{item.get('kind')!r}）")
        on = _date_text(item.get("approved_on"))
        if not isinstance(on, str) or not DATE_PATTERN.match(on):
            errs.append(f"{where}: approved_on は YYYY-MM-DD です（{item.get('approved_on')!r}）")
        else:
            try:
                date.fromisoformat(on)
            except ValueError:
                errs.append(f"{where}: approved_on が日付になっていません（{on}）")
        allows = item.get("allows")
        if not isinstance(allows, list) or not allows or any(a not in ALLOWS for a in allows):
            errs.append(f"{where}: allows は {list(ALLOWS)} です（扱ってよい区分）")
        if item.get("notes") is not None and not isinstance(item.get("notes"), str):
            errs.append(f"{where}: notes は文字列です")
    return errs


def parse(data: Any, path: Path | None = None) -> ApprovedList:
    errs = validate(data)
    if errs:
        raise ApprovedAIError(path, errs)
    out = ApprovedList(path=path, exists=path is not None)
    for item in (data or {}).get("approved") or []:
        out.entries[item["id"]] = ApprovedAI(
            id=item["id"], name=item["name"].strip(), kind=item["kind"], approved_on=_date_text(item["approved_on"]),
            basis=item["basis"].strip(), allows=tuple(item["allows"]), notes=(item.get("notes") or "").strip())
    return out


def find_config(explicit: str | Path | None = None, env: Mapping[str, str] | None = None,
                cwd: Path | None = None) -> Path:
    """探す順: 引数 ＞ 環境変数 ERKIT_APPROVED_AI ＞ 今のフォルダの config/approved_ai.yaml ＞ キットのフォルダの同じ所。

    どれも無ければキットのフォルダのパス（無いファイル）を返す。"""
    import os

    if explicit is not None:
        return Path(explicit)
    env = os.environ if env is None else env
    if env.get("ERKIT_APPROVED_AI"):
        return Path(env["ERKIT_APPROVED_AI"])
    here = (cwd or Path.cwd()) / CONFIG_RELPATH
    return here if here.is_file() else KIT_ROOT / CONFIG_RELPATH


def load(path: str | Path | None = None, *, env: Mapping[str, str] | None = None,
         cwd: Path | None = None) -> ApprovedList:
    """許可リストを読む。ファイルが無ければ空（認められた AI は無い）。形が違えば ApprovedAIError。"""
    p = find_config(path, env, cwd)
    if not p.is_file():
        return ApprovedList(path=p, exists=False)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ApprovedAIError(p, [f"読めません（{_first_line(str(e))}）"]) from e
    return parse(data, p)


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def describe(approved: ApprovedList) -> str:
    """doctor の表示: 載っている AI の名前。"""
    if not approved.entries:
        where = "ファイル無し" if not approved.exists else "載っている AI なし"
        return f"{where}（社外秘の台本は、この PC の中で動く AI だけ）"
    names = "、".join(f"{e.name}（{e.id}、{e.kind}）" for e in approved.entries.values())
    return f"{len(approved.entries)} 件: {names}"
