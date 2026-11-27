# -*- coding: utf-8 -*-
"""場面の指定（scenes.yaml）: Python を書かずに、場面を「型・中身・動くきっかけ」で書く。

置き場は場面コードと同じフォルダ（台本のフォルダの ``scenes/<reel id>/scenes.yaml`` か ``scenes/scenes.yaml``）。
形の正本はこのモジュールの ``json_schema()``。パッケージのデータ ``data/schema/scenes.schema.json`` はそこから作る
（``python -m explainer_reel_kit.interactive schema`` で書き出し、``schema --check`` で同じか確かめる）。

優先順位: その場面の Python の場面コード（``<場面 id>.py``・``index.py``）＞ scenes.yaml の指定 ＞ 既定の場面。

きっかけ（部品・項目の ``at`` / ``sentence``）:

- ``at: "露点は"``: その場面のナレーションの中で、この語句が読まれ始める秒（``T.at``）。語句が場面の 2 つ以上の文に
  あるときは ``sentence`` で文を決める
- ``sentence: 3``: その場面の 3 番目の文（``<場面 id>-3``）の始まり（``T.S``）。``at`` と一緒なら、その文の中の語句
- どちらも無ければ場面の始まり

読み込みの検証（知らない型・項目・動き、語句がナレーションに無い、文が無い、文字が枠に入らない）は描く前に止める
（``SpecError``。interactive のコマンドは終了コード 2）。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import motion as mo
from .engine import Frame, LayoutError

SPEC_NAME = "scenes.yaml"
SPEC_VERSION = 1
#: 書き出したスキーマ（パッケージのデータ。台本のスキーマと同じ置き場）
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "data" / "schema" / "scenes.schema.json"


class SpecError(LayoutError):
    """scenes.yaml の誤り（描く前に止める）。"""


# ---------------------------------------------------------------- 形（JSON スキーマ）

CUE_PROPS = {
    "at": {"type": "string", "minLength": 1, "description": "ナレーションの語句。この語句が読まれ始める秒がきっかけ（T.at）"},
    "sentence": {"type": "integer", "minimum": 1, "description": "その場面の何番目の文か（1 から）。at と一緒なら、その文の中の語句"},
    "delay": {"type": "number", "minimum": -5, "maximum": 30, "description": "きっかけから何秒ずらすか（既定 0）"},
}
COMMON_PROPS = {
    "type": {"type": "string"},
    **CUE_PROPS,
    "speed": {"type": "number", "exclusiveMinimum": 0, "maximum": 4,
              "description": "動きの速さ（見本帳の「速度」と同じく、長さをこの数で割る。既定 1）"},
    "until": {"type": "object", "additionalProperties": False, "properties": copy.deepcopy(CUE_PROPS),
              "description": "この時刻で部品を消す（見本帳 26 fadethrough の out .09s）。同じ場所の中身を入れ替えるとき"},
    "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
            "description": "置く範囲 [x, y, 幅, 高さ]（px、1920×1080 の画面。字幕帯 y 940 より上）。無ければ上から順に積む"},
}


def _registry():
    from .parts import PART_TYPES

    return PART_TYPES


def json_schema() -> dict:
    """scenes.yaml の JSON スキーマ（data/schema/scenes.schema.json の正本）。"""
    types = _registry()
    defs: dict[str, Any] = {"cue": {"type": "object", "properties": copy.deepcopy(CUE_PROPS)}}
    branches = []
    for name, cls in types.items():
        props = copy.deepcopy(COMMON_PROPS)
        props["type"] = {"const": name, "description": cls.TITLE}
        for key, allowed in cls.MOTION_FIELDS.items():
            props[key] = {"enum": list(allowed), "description": f"見本帳の見本の id（既定 {cls.DEFAULTS.get(key)}）"}
        props.update(copy.deepcopy(cls.SCHEMA))
        defs[name] = {"type": "object", "description": cls.DOC, "properties": props,
                      "required": ["type", *cls.REQUIRED], "additionalProperties": False}
        branches.append({"if": {"properties": {"type": {"const": name}}, "required": ["type"]},
                         "then": {"$ref": f"#/$defs/{name}"}})
    part = {"type": "object", "required": ["type"],
            "properties": {"type": {"enum": list(types), "description": "部品の型"}}, "allOf": branches}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/airesearchagl-art/explainer-reel-kit/schema/scenes.schema.json",
        "title": "explainer-reel-kit 場面の指定（scenes.yaml）",
        "description": "Python を書かずに場面を「型・中身・動くきっかけ」で書く（render_mode: interactive）。"
                       "動きの名前はモーション見本帳の見本の id。src/explainer_reel_kit/interactive/spec.py の json_schema() から作る",
        "type": "object",
        "required": ["version", "scenes"],
        "additionalProperties": False,
        "properties": {
            "version": {"const": SPEC_VERSION},
            "scenes": {"type": "object", "minProperties": 1,
                       "additionalProperties": {"$ref": "#/$defs/scene"},
                       "description": "場面 id → その場面の指定"},
        },
        "$defs": {
            "scene": {"type": "object", "required": ["parts"], "additionalProperties": False,
                      "properties": {"parts": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/part"}},
                                     "gap": {"type": "number", "minimum": 0,
                                             "description": "上から積むときの部品の間（px、既定 40）"}}},
            "part": part,
            **defs,
        },
    }


# ---------------------------------------------------------------- 読み込みと形の検証

def _where(path) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(全体)"


def _message(e) -> str:
    """jsonschema の誤りを日本語に。"""
    where = _where(list(e.absolute_path))
    v = e.validator
    if v == "additionalProperties":
        extra = sorted(set(e.instance) - set(e.schema.get("properties", {})))
        known = ", ".join(sorted(e.schema.get("properties", {})))
        return f"{where}: 知らない項目 {', '.join(extra)}（使える項目: {known}）"
    if v == "required":
        return f"{where}: 項目 {e.message.split(' ')[0]} が要ります"
    if v == "enum":
        return f"{where}: {e.instance!r} は使えません（使えるもの: {', '.join(map(str, e.validator_value))}）"
    if v == "const":
        return f"{where}: {e.validator_value!r} と書きます（{e.instance!r}）"
    if v == "type":
        kinds = {"string": "文字", "integer": "整数", "number": "数", "array": "並び（[...]）", "object": "項目の組",
                 "boolean": "true / false"}
        want = e.validator_value if isinstance(e.validator_value, list) else [e.validator_value]
        return f"{where}: {' か '.join(kinds.get(k, k) for k in want)}で書きます（{e.instance!r}）"
    if v in ("minItems", "maxItems", "minLength", "minimum", "maximum", "exclusiveMinimum", "minProperties"):
        return f"{where}: {e.message}"
    return f"{where}: {e.message}"


def validate_doc(doc: Any) -> list[str]:
    """形の検証（スキーマ）。戻り値は誤りの並び（空なら合格）。知らない型は型の名前の一覧を添える。"""
    from jsonschema import Draft202012Validator

    if not isinstance(doc, dict):
        return ["(全体): version と scenes を書きます"]
    types = _registry()
    errors: list[str] = []
    for sid, sc in (doc.get("scenes") or {}).items() if isinstance(doc.get("scenes"), dict) else []:
        for i, p in enumerate((sc or {}).get("parts") or [] if isinstance(sc, dict) else []):
            if isinstance(p, dict) and "type" in p and p["type"] not in types:
                errors.append(f"scenes.{sid}.parts[{i}]: 知らない型 {p['type']!r}（使える型: {', '.join(types)}）")
    if errors:
        return errors
    val = Draft202012Validator(json_schema())
    seen = set()
    for e in sorted(val.iter_errors(doc), key=lambda e: (list(map(str, e.absolute_path)), e.validator)):
        best = e
        if e.validator in ("allOf", "if", "then"):   # 枝の中の誤りを出す
            subs = list(e.context or [])
            best = subs[0] if subs else e
        msg = _message(best)
        if msg not in seen:
            seen.add(msg)
            errors.append(msg)
    return errors


def load_spec(path: Path) -> dict:
    """scenes.yaml を読み、形を確かめる。誤りは SpecError（どの場面のどの部品か）。"""
    import yaml

    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as e:
        raise SpecError(f"{path.name} を読めません: {e}") from e
    errors = validate_doc(doc)
    if errors:
        raise SpecError(f"{Path(path).name} の誤り:\n  " + "\n  ".join(errors[:30]))
    return doc


# ---------------------------------------------------------------- きっかけ

@dataclass
class Cue:
    """部品・項目のきっかけ。t は秒。label は確かめの一覧に出す名前。"""

    t: float
    label: str
    sentence: str | None = None
    phrase: str | None = None


def scene_sentences(T, sid: str) -> list[tuple[int, str, str]]:
    """場面 sid の文 [(番号, 文の id, 原稿)]。番号はその場面の中の順（時刻の順に 1 から）。

    台本から作った中間データでは文の id が <場面 id>-<番号> なので番号と同じ。通し番号の id の中間データでも、
    その場面の 2 番目の文が sentence: 2。
    """
    rows = sorted((v["start"], k, v["text"]) for k, v in T.sent.items() if v["scene"] == sid)
    return [(n, k, text) for n, (_, k, text) in enumerate(rows, 1)]


def resolve_cue(T, sid: str, item: dict, where: str, default: float | None = None) -> Cue:
    """item の at / sentence（と delay）→ きっかけの秒。語句・文が無ければ SpecError。"""
    c = _resolve_cue(T, sid, item, where, default)
    d = float(item.get("delay", 0) or 0)
    if d:
        c.t = round(c.t + d, 3)
        c.label += f" {d:+.2f}s"
    return c


def _resolve_cue(T, sid: str, item: dict, where: str, default: float | None = None) -> Cue:
    from .timeline import TimelineError

    at, num = item.get("at"), item.get("sentence")
    sc = T.by_id[sid]
    if at is None and num is None:
        t = sc["start"] if default is None else default
        return Cue(t, "場面の始まり" if default is None else "前と同じ")
    sents = scene_sentences(T, sid)
    if num is not None:
        hit = [s for s in sents if s[0] == num]
        if not hit:
            nums = [s[0] for s in sents]
            raise SpecError(f"{where}: 場面 {sid} に文 {num} はありません"
                            f"（文は {nums[0]}〜{nums[-1]}）" if nums else f"{where}: 場面 {sid} に文がありません")
        _, sent_id, text = hit[0]
        if at is None:
            return Cue(T.S(sent_id), f"文 {num}" + (f"（id {sent_id}）" if sent_id != f"{sid}-{num}" else ""),
                       sentence=sent_id)
        if at not in text:
            raise SpecError(f"{where}: 語句「{at}」は場面 {sid} の文 {num} にありません: {text}")
        try:
            return Cue(T.at(sent_id, at), f"文 {num}「{at}」", sentence=sent_id, phrase=at)
        except TimelineError as e:
            raise SpecError(f"{where}: {e}") from e
    hits = [s for s in sents if at in s[2]]
    if not hits:
        raise SpecError(f"{where}: 語句「{at}」が場面 {sid} のナレーションにありません")
    if len(hits) > 1:
        raise SpecError(f"{where}: 語句「{at}」は場面 {sid} の文 {'・'.join(str(s[0]) for s in hits)} にあります"
                        "（sentence: で文を決める）")
    n, sent_id, _ = hits[0]
    return Cue(T.at(sent_id, at), f"文 {n}「{at}」", sentence=sent_id, phrase=at)


# ---------------------------------------------------------------- 場面を組み立てる

CONTENT_TOP = 196      # 見出しの下（既定の場面と同じ）
CONTENT_BOTTOM = 900   # 字幕帯（940）の少し上
CONTENT_X, CONTENT_W = 96, 1728
GAP = 40


@dataclass
class Ctx:
    """部品の組み立てに渡すもの。"""

    T: Any
    sid: str
    where: str
    box: tuple[float, float, float, float]

    @property
    def scene(self) -> dict:
        return self.T.by_id[self.sid]

    def cue(self, item: dict, where: str, default: float | None = None) -> Cue:
        return resolve_cue(self.T, self.sid, item, f"{self.where}{where}", default)


@dataclass
class CompiledScene:
    """scenes.yaml の 1 場面。draw が場面コードの scene(f, t, T) の代わり。"""

    sid: str
    parts: list = field(default_factory=list)

    def draw(self, f: Frame, t: float, T=None) -> None:
        for p in self.parts:
            p.draw(f, t)

    def cues(self) -> list[tuple[str, Cue, float]]:
        """確かめ用: [(部品の名前, きっかけ, 動きが終わる秒)]（時刻の順）。"""
        out = []
        for p in self.parts:
            for c, end in p.cue_points():
                out.append((p.label, c, end))
        return sorted(out, key=lambda x: (x[1].t, x[0]))


def compile_scene(T, sid: str, spec: dict, file_name: str = SPEC_NAME) -> CompiledScene:
    """1 場面の指定を部品にする。きっかけの語句・文はここで確かめる（描く前）。"""
    types = _registry()
    if sid not in T.by_id:
        raise SpecError(f"{file_name}: 場面 {sid} は中間データにありません（場面: {list(T.by_id)}）")
    out = CompiledScene(sid)
    gap = spec.get("gap", GAP)
    y = CONTENT_TOP
    for i, ps in enumerate(spec["parts"]):
        cls = types[ps["type"]]
        where = f"{file_name} scenes.{sid}.parts[{i}]（{ps['type']}）"
        if "box" in ps:
            box = tuple(ps["box"])
        elif cls.FIXED_BOX is not None:
            box = cls.FIXED_BOX
        else:
            h = cls.natural_height(ps)
            box = (CONTENT_X, y, CONTENT_W, h)
            y += h + gap
        bx, by, bw, bh = box
        if by + bh > 940 + 0.5:
            raise SpecError(f"{where}: 字幕帯（y 940 より下）にかかります（下端 {by + bh:.0f}px）。"
                            "部品を減らすか box で置き場を決める")
        out.parts.append(cls(ps, Ctx(T, sid, where, box)))
    return out


def dry_run(T, sc: CompiledScene) -> None:
    """きっかけの直後・動きの終わり・場面の終わりで 1 度ずつ組み立て、文字のはみ出しを描く前に見つける。"""
    times = {T.by_id[sc.sid]["end"] - 1.0 / T.fps}
    for _, c, end in sc.cues():
        times |= {c.t + 1.0 / T.fps, end}
    for t in sorted(times):
        try:
            sc.draw(Frame(), t)
        except SpecError:
            raise
        except LayoutError as e:
            raise SpecError(f"場面 {sc.sid}、{t:.2f}s: {e}") from e


def check_motion(cls, ps: dict, where: str) -> None:
    for key, allowed in cls.MOTION_FIELDS.items():
        v = ps.get(key)
        if v is not None and mo.STAGGER_ALIASES.get(v, v) not in allowed:
            raise SpecError(f"{where}: {key} {v!r} はこの型では使えません（使えるもの: {', '.join(allowed)}）")
