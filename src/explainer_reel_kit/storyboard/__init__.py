"""台本（storyboard）の読み込み・Markdown → JSON の変換・検証・区分。

- スキーマ: パッケージのデータ ``data/schema/storyboard.schema.json``（kit-1.2.0）
- 読める版: 1.0.0 / 1.1.0 / kit-1.0.0 / kit-1.1.0 / kit-1.2.0（1.0.0 / 1.1.0 は web / manual / generated の画像だけを使う台本。
  ``kind: explainer`` は kit-1.1.0 から。``reel.render_mode``・字幕の別表記 ``subtitles``・固定尺の枠 ``slot_sec`` は kit-1.2.0 から）
- 社外秘の区分を読むのは :func:`confidentiality` だけ。ほかのモジュールはここで区分を読む
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterator

import yaml
from jsonschema import Draft202012Validator

SCHEMA_VERSION = "kit-1.2.0"  # 新しく書く台本の版
SCHEMA_VERSIONS = ("1.0.0", "1.1.0", "kit-1.0.0", "kit-1.1.0", "kit-1.2.0")  # 読める版
KINDS = ("tool_intro", "work_manual", "explainer")  # 台本の種別（reel.kind）
#: 版ごとに足した種別（それより前の版の台本では使えない）
KIND_SINCE = {"explainer": "kit-1.1.0"}
#: 版ごとに足した項目（それより前の版の台本では使えない）。(項目名, 表示名) → 版
FIELD_SINCE = {
    ("render_mode", "映像の作り方（reel.render_mode）"): "kit-1.2.0",
    ("subtitles", "字幕の別表記（subtitles）"): "kit-1.2.0",
    ("slot_sec", "固定尺の枠（slot_sec）"): "kit-1.2.0",
}
#: 映像の作り方（reel.render_mode）。省略は slides
RENDER_MODES = ("slides", "interactive")
DEFAULT_RENDER_MODE = "slides"

# 社外秘の区分（reel.confidentiality）
CONFIDENTIAL = "confidential"
GENERAL = "general"
CONFIDENTIALITY_VALUES = (CONFIDENTIAL, GENERAL)

RESERVED_SECTIONS = ("intro", "outro")
RECOMMENDED_SCENES = (5, 8)
EXPLAINER_SCENES = (5, 7)  # kind: explainer の推奨
#: 種別の短い説明（erkit check の表示）
KIND_LABELS = {"tool_intro": "ツールの紹介", "work_manual": "作業の手順", "explainer": "一般の解説"}

# キットでは使えない値（本体の元になった仕組みにだけあるもの）
UNSUPPORTED_SOURCES = {"sketchup": "SketchUp の撮影はキットに含まれません"}
UNSUPPORTED_KINDS = {"catalog": "カタログ動画はキットに含まれません"}

_FRONT_MATTER = re.compile(r"\A(?:﻿)?---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
_SECTION = re.compile(r"^##\s+([A-Za-z0-9_-]+)\s*(?:[:：]\s*(.*?))?\s*$")
_YAML_FENCE = re.compile(r"^```ya?ml\s*$")
_FENCE_END = re.compile(r"^```\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# 字幕の別表記（kit-1.2.0）: 段落の直後の <!-- subtitle: … -->（複数行でもよい）
_SUBTITLE = re.compile(r"<!--\s*subtitle\s*[:：](.*?)-->", re.S)
# 日本語の行動見出しは動詞（終止形）で終わる: 〜する / 〜る / 〜く / 〜す …
_VERB_ENDING = re.compile(r"[うくぐすつぬぶむる]$")


class ConversionError(ValueError):
    """Markdown 台本を JSON へ変換できない（書式の誤り）。"""


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------- schema

@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    text = resources.files("explainer_reel_kit").joinpath("data/schema/storyboard.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def recipe_names() -> list[str]:
    return list(load_schema()["$defs"]["recipe"]["enum"])


# ---------------------------------------------------------------- Markdown → JSON

def markdown_to_storyboard(text: str) -> dict[str, Any]:
    """Markdown 台本（テンプレート ``data/templates/storyboard.md`` の書式）を台本 dict に変換する。"""
    m = _FRONT_MATTER.match(text)
    if not m:
        raise ConversionError("先頭に YAML front matter（--- で囲む reel 情報）がありません")
    reel = _load_yaml(m.group(1), "front matter")
    if not isinstance(reel, dict):
        raise ConversionError("front matter は key: value の形式で書いてください")
    if isinstance(reel.get("aspect"), int):
        raise ConversionError('aspect は引用符で囲んでください（例: aspect: "16:9"）')
    if "schema_version" in reel:
        reel["schema_version"] = str(reel["schema_version"])

    body_start_line = text[: m.end()].count("\n") + 1
    sections = _split_sections(text[m.end():], body_start_line)

    doc: dict[str, Any] = {"reel": reel}
    scenes: list[dict[str, Any]] = []
    for sec in sections:
        meta, narration, subtitles = _parse_section_body(sec)
        if subtitles:
            if "subtitles" in meta:
                raise ConversionError(f"{sec['line']} 行目: ## {sec['key']} の字幕の別表記が yaml ブロックと"
                                      " <!-- subtitle: --> の両方にあります（どちらか一方に）")
            meta = {**meta, "subtitles": subtitles}
        if sec["key"] in RESERVED_SECTIONS:
            if sec["key"] in doc:
                raise ConversionError(f"{sec['line']} 行目: ## {sec['key']} が重複しています")
            item = dict(meta)
            if narration:
                item["narration"] = narration
            doc[sec["key"]] = item
        else:
            if not sec["heading"]:
                raise ConversionError(f"{sec['line']} 行目: シーン見出しは『## <id>: <行動の見出し>』で書いてください")
            item = {"id": sec["key"], "heading": sec["heading"], **meta}
            if narration:
                item["narration"] = narration
            scenes.append(item)

    ordered: dict[str, Any] = {"reel": doc["reel"]}  # 出力順を固定（reel → intro → scenes → outro）
    if "intro" in doc:
        ordered["intro"] = doc["intro"]
    ordered["scenes"] = scenes
    if "outro" in doc:
        ordered["outro"] = doc["outro"]
    return ordered


def _load_yaml(src: str, where: str) -> Any:
    try:
        return yaml.safe_load(src) or {}
    except yaml.YAMLError as e:
        raise ConversionError(f"{where} の YAML を読めません: {e}") from e


def _split_sections(body: str, first_line: int) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_fence = False
    for offset, line in enumerate(body.splitlines()):
        lineno = first_line + offset
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        hm = None if in_fence else _SECTION.match(line)
        if hm:
            current = {"key": hm.group(1), "heading": (hm.group(2) or "").strip(), "line": lineno, "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append((lineno, line))
        # ## より前の本文（# タイトルや説明）は読み飛ばす
    return sections


def _parse_section_body(sec: dict[str, Any]) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    lines = sec["lines"]
    meta: dict[str, Any] = {}
    rest: list[str] = []
    i = 0
    found_yaml = False
    while i < len(lines):
        lineno, line = lines[i]
        if not found_yaml and _YAML_FENCE.match(line.strip()):
            j = i + 1
            while j < len(lines) and not _FENCE_END.match(lines[j][1].strip()):
                j += 1
            if j >= len(lines):
                raise ConversionError(f"{lineno} 行目: ```yaml ブロックが閉じていません")
            loaded = _load_yaml("\n".join(l for _, l in lines[i + 1 : j]), f"{lineno} 行目のブロック")
            if not isinstance(loaded, dict):
                raise ConversionError(f"{lineno} 行目: yaml ブロックは key: value で書いてください")
            meta = loaded
            found_yaml = True
            i = j + 1
            continue
        rest.append(line)
        i += 1
    if not found_yaml:
        raise ConversionError(f"{sec['line']} 行目: ## {sec['key']} に ```yaml ブロックがありません")
    narration, subtitles = _narration_and_subtitles(rest, sec)
    return meta, narration, subtitles


def _narration_from_lines(lines: list[str]) -> str:
    """段落内の改行は詰め、空行区切りの段落は改行 1 つで区切る。HTML コメントは除く。"""
    text = _COMMENT.sub("", "\n".join(lines))
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        parts = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if parts:
            paragraphs.append(_join_lines(parts))
    return "\n".join(paragraphs)


def _narration_and_subtitles(lines: list[str], sec: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """ナレーション（:func:`_narration_from_lines` と同じ）と、字幕の別表記 ``[{paragraph, text}]``（kit-1.2.0）。

    ``<!-- subtitle: … -->`` は、その前にある一番近い段落の字幕になる（空行を挟んでもよい）。前に段落が無い・
    同じ段落に 2 つある・中身が空のときは ConversionError。ほかの HTML コメントは今までどおり捨てる。
    """
    text = "\n".join(lines)
    subtitles: list[dict[str, Any]] = []
    for m in _SUBTITLE.finditer(text):
        before = _narration_from_lines(text[: m.start()].split("\n"))
        count = len([p for p in before.split("\n") if p]) if before else 0
        body_lines = [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]
        body = _join_lines(body_lines) if body_lines else ""
        if count == 0:
            raise ConversionError(f"{sec['line']} 行目の ## {sec['key']}: <!-- subtitle: --> の前に段落がありません"
                                  "（字幕の別表記は、直す段落のすぐ後に書く）")
        if not body:
            raise ConversionError(f"{sec['line']} 行目の ## {sec['key']}: <!-- subtitle: --> の中身が空です")
        if subtitles and subtitles[-1]["paragraph"] == count:
            raise ConversionError(f"{sec['line']} 行目の ## {sec['key']}: 段落 {count} に <!-- subtitle: --> が"
                                  " 2 つあります")
        subtitles.append({"paragraph": count, "text": body})
    return _narration_from_lines(lines), subtitles


def _join_lines(parts: list[str]) -> str:
    out = parts[0]
    for p in parts[1:]:
        # 英数字同士がつながる場合だけ空白を入れる（日本語は詰める）
        sep = " " if out[-1].isascii() and out[-1].isalnum() and p[0].isascii() and p[0].isalnum() else ""
        out += sep + p
    return out


# ---------------------------------------------------------------- load

def load_storyboard(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return markdown_to_storyboard(text)


def dump_json(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- 区分

def confidentiality(doc: Any) -> str:
    """台本の区分（confidential / general）。ほかのモジュールはこの関数だけで区分を読む。

    書いていない・1.0.0 の台本・読めない値（``General`` などの書き間違いも）は confidential（安全側）。
    """
    reel = doc.get("reel") if isinstance(doc, dict) else None
    value = reel.get("confidentiality") if isinstance(reel, dict) else None
    return value if value in CONFIDENTIALITY_VALUES else CONFIDENTIAL


def render_mode(doc: Any, override: str | None = None) -> str:
    """映像の作り方（slides / interactive）。コマンドの指定（override）が台本の ``reel.render_mode`` より優先。

    どちらも無い・読めない値は slides（今までの経路）。override に知らない値を渡すと ValueError。
    """
    if override is not None:
        if override not in RENDER_MODES:
            raise ValueError(f"render_mode は {' / '.join(RENDER_MODES)} のどれかです: {override!r}")
        return override
    reel = doc.get("reel") if isinstance(doc, dict) else None
    value = reel.get("render_mode") if isinstance(reel, dict) else None
    return value if value in RENDER_MODES else DEFAULT_RENDER_MODE


# ---------------------------------------------------------------- validation

def _fmt_path(path) -> str:
    return "/".join(str(p) for p in path) or "(root)"


def _iter_scenes(doc: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any]]]:
    scenes = doc.get("scenes")
    if isinstance(scenes, list):
        for idx, sc in enumerate(scenes):
            if isinstance(sc, dict):
                yield idx, sc


def _iter_images(doc: dict[str, Any]):
    for idx, sc in _iter_scenes(doc):
        if isinstance(sc.get("image"), dict):
            yield f"scenes/{idx} ({sc.get('id')})", sc["image"]
    outro = doc.get("outro")
    if isinstance(outro, dict) and isinstance(outro.get("image"), dict):
        yield "outro", outro["image"]


def _narration_nodes(doc: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """(場所, intro / シーン / outro の dict)。ナレーションを持つところ。"""
    if isinstance(doc.get("intro"), dict):
        yield "intro", doc["intro"]
    for idx, sc in _iter_scenes(doc):
        yield f"scenes/{idx} ({sc.get('id')})", sc
    if isinstance(doc.get("outro"), dict):
        yield "outro", doc["outro"]


def _version_before(version: Any, since: str) -> bool:
    """version（読める版）が since より前か。読めない版は False（スキーマのエラーに任せる）。"""
    return version in SCHEMA_VERSIONS and SCHEMA_VERSIONS.index(version) < SCHEMA_VERSIONS.index(since)


def _kit_only_features(doc: dict[str, Any]) -> list[str]:
    """kit-1.0.0 で足した項目のうち、台本が使っているもの。"""
    found = []
    for idx, sc in _iter_scenes(doc):
        cap = sc.get("capture")
        img = sc.get("image")
        if isinstance(img, dict) and img.get("source") == "generated" and isinstance(cap, dict):
            if "src" in cap:
                found.append(f"scenes/{idx} ({sc.get('id')}): capture.src")
            if cap.get("tool") == "html":
                found.append(f"scenes/{idx} ({sc.get('id')}): capture.tool = html")
    return found


def validate_storyboard(doc: Any, base_dir: Path | None = None) -> Report:
    """台本 dict を検証する。errors が 1 件でもあれば不合格。

    base_dir は manual 画像の相対パスを解決する基準（台本ファイルのあるフォルダ）。
    """
    rep = Report()
    if not isinstance(doc, dict):
        rep.errors.append("[schema] 台本の最上位はオブジェクトである必要があります")
        return rep

    scenes = doc.get("scenes")
    recipes = recipe_names()
    reel = doc.get("reel") if isinstance(doc.get("reel"), dict) else {}
    version = reel.get("schema_version")

    # --- キットで使えないもの（分かりやすい理由で報告し、同じ箇所のスキーマのエラーは出さない）
    skip: set[tuple] = set()
    kind = reel.get("kind")
    if kind in UNSUPPORTED_KINDS:
        rep.errors.append(f"[kit] reel.kind '{kind}': {UNSUPPORTED_KINDS[kind]}")
        skip.add(("reel", "kind"))

    if not isinstance(scenes, list) or len(scenes) == 0:
        rep.errors.append("[scenes] シーンが 0 件です（本編シーンを 1 つ以上書いてください）")

    seen: set[str] = set()
    for idx, sc in _iter_scenes(doc):
        sid = sc.get("id", f"#{idx}")
        recipe = sc.get("recipe")
        if recipe is not None and recipe not in recipes:
            rep.errors.append(f"[recipe] scenes/{idx} ({sid}): 存在しないレシピ名 '{recipe}'（使えるもの: {', '.join(recipes)}）")
        if isinstance(sid, str):
            if sid in RESERVED_SECTIONS:
                rep.errors.append(f"[id] scenes/{idx}: '{sid}' は予約名のためシーン ID に使えません")
            elif sid in seen:
                rep.errors.append(f"[id] scenes/{idx}: シーン ID '{sid}' が重複しています")
            seen.add(sid)
        heading = sc.get("heading")
        if isinstance(heading, str) and heading and not _VERB_ENDING.search(heading):
            rep.warnings.append(f"[heading] scenes/{idx} ({sid}): 見出しは行動（動詞）で終える形を推奨: '{heading}'")
        img = sc.get("image")
        source = img.get("source") if isinstance(img, dict) else None
        if source in UNSUPPORTED_SOURCES:
            rep.errors.append(f"[kit] scenes/{idx} ({sid}): image.source '{source}': {UNSUPPORTED_SOURCES[source]}")
            skip.update({("scenes", idx, "image", "source"), ("scenes", idx, "capture")})
        elif source == "web" and "capture" not in sc:
            rep.warnings.append(f"[capture] scenes/{idx} ({sid}): web 画像の撮影指示（capture）がありません")

    if version in ("1.0.0", "1.1.0"):
        for where in _kit_only_features(doc):
            rep.errors.append(f"[version] {where} は kit-1.0.0 の項目です。schema_version を kit-1.0.0 にしてください")

    since = KIND_SINCE.get(kind) if isinstance(kind, str) else None
    if since and version in SCHEMA_VERSIONS and SCHEMA_VERSIONS.index(version) < SCHEMA_VERSIONS.index(since):
        rep.errors.append(f"[version] reel.kind '{kind}' は {since} の種別です。schema_version を {since} にしてください")

    # --- 版ごとに足した項目（render_mode・subtitles・slot_sec）。スキーマはシーンから版を見られないため、ここで確かめる
    skip_render_mode_version = False
    for (key, label), field_since in FIELD_SINCE.items():
        if not _version_before(version, field_since):
            continue
        places = [("reel", reel)] if key == "render_mode" else list(_narration_nodes(doc))
        for where, node in places:
            if key in node:
                rep.errors.append(f"[version] {where}: {label}は {field_since} 以降の台本だけで使えます。"
                                  f"schema_version を {field_since} にしてください")
                skip_render_mode_version = skip_render_mode_version or key == "render_mode"

    # --- 字幕の別表記の段落の番号
    for where, node in _narration_nodes(doc):
        subs = node.get("subtitles")
        narration = node.get("narration")
        if not (isinstance(subs, list) and isinstance(narration, str)):
            continue
        count = len([ln for ln in narration.splitlines() if ln.strip()])
        seen_p: set[int] = set()
        for s_item in subs:
            n = s_item.get("paragraph") if isinstance(s_item, dict) else None
            if isinstance(n, int) and not isinstance(n, bool):
                if n > count:
                    rep.errors.append(f"[subtitles] {where}: 段落 {n} がありません（ナレーションの段落は {count}）")
                elif n in seen_p:
                    rep.errors.append(f"[subtitles] {where}: 段落 {n} の字幕の別表記が 2 つあります")
                seen_p.add(n)

    if version in ("1.1.0", "kit-1.0.0", "kit-1.1.0", "kit-1.2.0") and "confidentiality" not in reel:
        rep.warnings.append("[confidentiality] reel.confidentiality が未記入です。未記入は confidential として扱います"
                            "（公開済みの情報・一般的な知識だけなら general と書く）")

    lo, hi = RECOMMENDED_SCENES
    if kind == "explainer":  # 解説の構成の決まり: 5〜7 シーン（docs/design/storyboard.md）
        lo, hi = EXPLAINER_SCENES
    if isinstance(scenes, list) and scenes and not (lo <= len(scenes) <= hi):
        rep.warnings.append(f"[scenes] シーン数 {len(scenes)}（推奨 {lo}〜{hi}）")

    # --- スキーマ検証（独自チェックと重複する分は除く）
    validator = Draft202012Validator(load_schema())
    for err in sorted(validator.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path]):
        path = tuple(err.absolute_path)
        if path == ("scenes",) and err.validator == "minItems":
            continue
        if len(path) == 3 and path[0] == "scenes" and path[2] == "recipe" and err.validator == "enum":
            continue
        if any(path[: len(s)] == s for s in skip):
            continue
        if skip_render_mode_version and path == ("reel", "schema_version") and err.validator == "const":
            continue  # render_mode の版は上の [version] で報告済み
        rep.errors.append(f"[schema] {_fmt_path(path)}: {err.message}")

    # --- manual 画像の参照切れ
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    for where, img in _iter_images(doc):
        if img.get("source") != "manual" or not isinstance(img.get("ref"), str):
            continue
        if not (base / img["ref"]).resolve().is_file():
            rep.errors.append(f"[image] {where}: manual 画像が見つかりません: {img['ref']}")

    return rep


def validate_file(path: Path | str) -> Report:
    path = Path(path)
    try:
        doc = load_storyboard(path)
    except ConversionError as e:
        return Report(errors=[f"[markdown] {e}"])
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return Report(errors=[f"[json] 読み込めません: {e}"])
    return validate_storyboard(doc, base_dir=path.parent)
