"""台本の下書きへ、mark の名前を入れる（LLM は使わない）。

``erkit draft <台本の id> --update-marks``

赤枠・矢印は座標を書かず、mark の名前で指す（docs/design/storyboard.md「レシピ」）。名前は次から取る。

- Web の撮影のシーン（``image.source: web``）: 操作定義（``<reel id>.actions.yaml``、
  ``explainer-reel/web-actions@1``）の ``scenes.<シーン id>.marks`` の名前
- 説明図のシーン（``image.source: generated`` で ``capture.tool: html``）: ``capture.src`` の HTML の
  ``data-mark="名前"``

触るのはシーンの YAML ブロックだけで、行を**足す**だけ（``recipe_params:`` と ``mark: …``）。
ナレーション・確認・人が直した所は 1 字も変えない。次のシーンはそのままにする:
mark（か box）が既にある、recipe が ``highlight_box`` / ``arrow_move`` でない、名前が見つからない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

from .. import storyboard as sb
from .errors import ConfigError, OutputError

ACTIONS_SCHEMA = "explainer-reel/web-actions@1"
ACTIONS_SUFFIX = ".actions.yaml"
MARK_RECIPES = ("highlight_box", "arrow_move")
_MARK_NAME = re.compile(r"^[a-z0-9_]+$")
_SECTION = re.compile(r"^##\s+([A-Za-z0-9_-]+)\s*(?:[:：].*)?$")
_KEY = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")


@dataclass
class MarksUpdate:
    path: Path
    updated: dict[str, list[str]] = field(default_factory=dict)  # シーン id → 入れた mark
    skipped: dict[str, str] = field(default_factory=dict)  # シーン id → そのままにした理由
    record: Path | None = None
    warnings: list[str] = field(default_factory=list)


# -- 名前を集める ------------------------------------------------------------------------------

def action_marks(path: str | Path) -> dict[str, list[str]]:
    """操作定義の ``scenes.<id>.marks`` の名前（書いた順）。"""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as cause:
        raise ConfigError(f"操作定義がありません: {path}") from cause
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as cause:
        raise ConfigError(f"操作定義を読めません: {path}: {cause}") from cause
    if not isinstance(data, dict) or data.get("schema") != ACTIONS_SCHEMA:
        raise ConfigError(f"操作定義の schema が {ACTIONS_SCHEMA} ではありません: {path}")
    out: dict[str, list[str]] = {}
    for sid, scene in (data.get("scenes") or {}).items():
        marks = scene.get("marks") if isinstance(scene, dict) else None
        if isinstance(marks, dict):
            out[str(sid)] = [str(n) for n in marks if _MARK_NAME.match(str(n))]
    return out


class _DataMarks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key == "data-mark" and value and _MARK_NAME.match(value) and value not in self.names:
                self.names.append(value)


def html_marks(path: str | Path) -> list[str]:
    """説明図の HTML の ``data-mark`` の名前（出てくる順、重複なし）。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as cause:
        raise ConfigError(f"説明図の HTML を読めません: {path}: {cause}") from cause
    parser = _DataMarks()
    parser.feed(text)
    return parser.names


def _has_mark(value: Any) -> bool:
    if isinstance(value, dict):
        return any(k in ("mark", "box") or _has_mark(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_mark(v) for v in value)
    return False


def names_for(scene: dict[str, Any], base_dir: Path, actions: dict[str, list[str]] | None) -> tuple[list[str], str]:
    """(mark の名前, 見つからないときの理由)。"""
    image = scene.get("image") or {}
    capture = scene.get("capture") or {}
    source = image.get("source")
    if source == "web":
        if actions is None:
            return [], "操作定義がない"
        names = actions.get(scene.get("id"), [])
        return names, "" if names else "操作定義にこのシーンの marks がない"
    if source == "generated":
        if capture.get("tool") != "html" or not isinstance(capture.get("src"), str):
            return [], "説明図の HTML がまだない（capture に tool: html と src を書く）"
        html = base_dir / capture["src"]
        if not html.is_file():
            return [], f"説明図の HTML がない: {capture['src']}"
        names = html_marks(html)
        return names, "" if names else "説明図の HTML に data-mark がない"
    return [], f"image.source が {source}（mark を測るのは web と説明図だけ）"


# -- 書き込み -------------------------------------------------------------------------------------

def _scalar(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][\w-]*", name) else json.dumps(name, ensure_ascii=False)


def _insert(block: list[str], names: list[str]) -> list[str]:
    """``block``: 1 シーンの YAML の行（囲みの ``` は除く）。mark の行を足して返す。"""
    mark_text = _scalar(names[0]) if len(names) == 1 else "[" + ", ".join(_scalar(m) for m in names) + "]"
    keys = {m.group(1): i for i, m in ((i, _KEY.match(line)) for i, line in enumerate(block)) if m}
    if "recipe_params" in keys:
        start = keys["recipe_params"]
        children = []
        for line in block[start + 1:]:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            children.append(line)
        indent = next((len(c) - len(c.lstrip()) for c in children if c.strip()), 2)
        return block[:start + 1] + [f"{' ' * indent}mark: {mark_text}"] + block[start + 1:]
    at = keys["recipe"] + 1
    while at < len(block) and block[at].startswith((" ", "\t")):
        at += 1
    return block[:at] + ["recipe_params:", f"  mark: {mark_text}"] + block[at:]


def update_marks(path: str | Path, actions_path: str | Path | None = None) -> MarksUpdate:
    """``path`` の台本に mark の名前を入れる。``actions_path`` が無ければ台本の隣の ``<id>.actions.yaml``（あれば）。"""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"台本がありません: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        doc = sb.markdown_to_storyboard(text)
    except sb.ConversionError as error:
        raise ConfigError(f"台本を読めません: {path}: {error}") from error
    reel_id = (doc.get("reel") or {}).get("id") or path.name.split(".")[0]
    if actions_path is None:
        guess = path.parent / f"{reel_id}{ACTIONS_SUFFIX}"
        actions_path = guess if guess.is_file() else None
    actions = action_marks(actions_path) if actions_path is not None else None

    result = MarksUpdate(path)
    lines = text.split("\n")
    out: list[str] = []
    scenes = {s["id"]: s for s in doc.get("scenes") or [] if isinstance(s, dict) and "id" in s}
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = _SECTION.match(line)
        i += 1
        if not m or m.group(1) not in scenes:
            continue
        sid = m.group(1)
        while i < len(lines) and not re.match(r"^```ya?ml\s*$", lines[i]):
            if _SECTION.match(lines[i]):
                break
            out.append(lines[i])
            i += 1
        if i >= len(lines) or _SECTION.match(lines[i]):
            continue
        out.append(lines[i])
        i += 1
        block: list[str] = []
        while i < len(lines) and lines[i].strip() != "```":
            block.append(lines[i])
            i += 1
        scene = scenes[sid]
        names, why = names_for(scene, path.parent, actions)
        reason = None
        if _has_mark(scene.get("recipe_params")):
            reason = "mark（または box）が既にある"
        elif "recipe" not in scene:
            reason = "recipe がない"
        elif scene["recipe"] not in MARK_RECIPES:
            reason = f"recipe が {scene['recipe']}（{' / '.join(MARK_RECIPES)} 以外は人が書く）"
        elif not names:
            reason = why
        if reason is None:
            block = _insert(block, names)
            result.updated[sid] = names
        else:
            result.skipped[sid] = reason
        out.extend(block)
    if not result.updated:
        return result
    new_text = "\n".join(out)
    try:
        new_doc = sb.markdown_to_storyboard(new_text)
    except sb.ConversionError as error:  # pragma: no cover - 足すのはふつうの YAML の行だけ
        raise OutputError(f"mark を入れた台本を読み直せません（書き込んでいません）: {error}") from error
    # 変わってよいのは、入れたシーンの recipe_params.mark だけ
    before = json.loads(json.dumps(doc))
    after = json.loads(json.dumps(new_doc))
    for scene in after.get("scenes") or []:
        if scene.get("id") in result.updated:
            params = dict(scene.get("recipe_params") or {})
            params.pop("mark", None)
            if params:
                scene["recipe_params"] = params
            else:
                scene.pop("recipe_params", None)
    if before != after:  # pragma: no cover - 念のための確かめ
        raise OutputError("mark 以外の部分が変わってしまうため、書き込みませんでした")
    report = sb.validate_storyboard(new_doc, base_dir=path.parent)
    errors = [e for e in report.errors if not e.startswith("[image]")]
    if errors:
        raise OutputError("mark を入れた台本が検証に通らないため、書き込みませんでした:\n  - " + "\n  - ".join(errors))
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    record = path.parent / "draft.json"
    if record.is_file():
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
            data.setdefault("marks_updates", []).append({
                "at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "storyboard": str(path), "actions": str(actions_path) if actions_path else None,
                "updated": result.updated, "skipped": result.skipped})
            record.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result.record = record
        except (OSError, ValueError) as error:
            result.warnings.append(f"draft.json に記録できませんでした: {error}")
    return result
