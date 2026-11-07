"""``erkit draft``: 資料から、手元の LLM で台本の下書きを作る。

流れ（AI は判断の層だけ。この PC の LLM だけを使う）:

1. 渡された資料（README・説明のテキストなど。手元のファイルだけ。何も取りに行かない）を読む
2. task ``draft`` のモデルに、**小さな中間の JSON**（題名・要約・前提・冒頭・シーン・まとめ）を
   ``structured.generate`` で書かせる（LLM に Markdown は書かせない）
3. **コード**が中間の JSON から台本（Markdown、スキーマ kit-1.1.0）を組み立て、``storyboard`` で検証する。
   検証の不合格・シーン数の違い・Markdown の記号は、書き直しの依頼として LLM に返す
4. 柔らかい確かめ（資料にない数値・長さ・セレクタらしい書き方・動画で触れない語）は警告にする

できるのは**下書き**です。人が直してから使います。画像は予定のパス（未撮影・未作成）、注釈（mark）は未設定、
撮影の手順は人が読む文章です。区分（confidentiality）は既定で ``confidential``（安全側）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .. import storyboard as sb
from .budget import DEFAULT_CONTEXT, Budget, BudgetError, Measurer, estimate_messages
from .client import LLMClient
from .condense import LightTask, fit_sources
from .confidentiality import CONFIDENTIAL, GENERAL
from .confidentiality import VALUES as CONFIDENTIALITY_VALUES
from .confidentiality import normalize as normalize_confidentiality
from .config import Task, task_settings
from .errors import ConfigError, OutputError, RouteBlockedError
from .structured import DEFAULT_RETRIES, StructuredResult, generate, schema_problems

DRAFT_FORMAT = "explainer-reel-kit/storyboard-draft"
DRAFT_VERSION = 1
RECORD_NAME = "draft.json"
REELS_DIR = "reels"
SOURCE_LIMIT_CHARS = 40000  # 念のための上限。送る量はトークンの予算（budget.py）で決める
# 答えが max_tokens で切れたときに、何を短くするか（「短く」だけでなく具体的に）
LENGTH_ADVICE = ("次を短くしてください: 各シーンの narration は 2〜3 文、capture_steps は 3 つまで（各 1 文）、"
                 "on_screen_text は 60 字以内、check は 1 文、prerequisites と outro.checks は 3 つまで（各 1 文）、"
                 "intro_narration と outro.narration は 2〜3 文")
# 答えの予算はシーン数から（llm/README.md「出力の予算」）
DRAFT_TOKENS_BASE = 800  # 題名・要約・前提・冒頭・まとめと JSON のキー
DRAFT_TOKENS_PER_SCENE = 400  # 見出し・場所・画面の文・ナレーション（2〜3 文）・確認・手順 1〜3
DEFAULT_SCENES = 5
RECOMMENDED_SCENES = sb.RECOMMENDED_SCENES
#: 見る人（docs/design/storyboard.md の audience）
AUDIENCES = {
    "A": "初めての人。専門用語は言い換え、何ができるか・何が分かるかを中心に話す",
    "B": "よく使う人・詳しい人。前提と判断の根拠を丁寧に話す",
    "C": "専門家・作る人。手順・前提・制約を具体的に話す",
}
#: 画像の作り方（全シーン共通）。diagram は説明図（generated）、web は Web 画面の撮影、manual は人が用意する画像
CAPTURES = ("diagram", "web", "manual")
KINDS = sb.KINDS  # tool_intro / work_manual / explainer
#: 種別ごとの、指示の文での呼び方
KIND_PROMPTS = {"tool_intro": "ツールの紹介動画", "work_manual": "作業の手順の動画", "explainer": "一般の解説動画"}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SHOT = re.compile(r"^[a-z0-9_]{1,24}$")
_SENTENCE_END = re.compile(r"[。！？!?]")
_SELECTOR = re.compile(r"(?:^|\s)[#.][A-Za-z_][\w-]*|\[[\w-]+\s*[*^$|~]?=|//[a-z]+\[|>\s*[a-z]+[.#]")
# 単位つきの数（mm・%・m² など）。その数が資料のどこかにあること
_NUMBER_WITH_UNIT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:mm|ミリ|cm|センチ|m/s|m³/h|m3/h|㎥/h|立方メートル|%|％|パーセント|m²|㎡|平方メートル|"
    r"kg|キロ|Pa|パスカル|kW|W|ワット|lx|ルクス|℃|度|円|件|行|個|枚|人|字|回|分|秒|時間|日|メートル|m(?![a-zA-Z]))"
)
_ANY_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def intermediate_schema(scenes: int) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    return {
        "type": "object",
        "required": ["title", "summary", "intro_narration", "scenes", "outro"],
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 80},
            "summary": {"type": "string", "minLength": 1, "maxLength": 120},
            "prerequisites": {"type": "array", "items": text},
            "intro_narration": text,
            "scenes": {
                "type": "array",
                "minItems": scenes,
                "maxItems": scenes,
                "items": {
                    "type": "object",
                    "required": ["heading", "where", "narration", "check", "capture_steps", "shot_name"],
                    "properties": {
                        "heading": {"type": "string", "minLength": 1, "maxLength": 40},
                        "where": text,
                        "on_screen_text": {"type": "string", "maxLength": 60},
                        "narration": text,
                        "check": text,
                        "capture_steps": {"type": "array", "minItems": 1, "items": text},
                        "shot_name": {"type": "string", "pattern": _SHOT.pattern},
                    },
                },
            },
            "outro": {
                "type": "object",
                "required": ["summary", "narration"],
                "properties": {
                    "summary": {"type": "string", "minLength": 1, "maxLength": 120},
                    "checks": {"type": "array", "items": text},
                    "next": {"type": "string"},
                    "narration": text,
                },
            },
        },
    }


SYSTEM_PROMPT = (
    "あなたは説明動画（ツールの紹介・作業の手順）の台本を書く担当です。与えられた資料に書かれた事実だけを使い、"
    "日本語で簡潔に書きます。答えは JSON だけを出力します。"
)


@dataclass(frozen=True)
class DraftRequest:
    reel_id: str
    sources: list[Path]
    title: str | None = None
    audience: str = "A"
    capture: str = "diagram"
    url: str | None = None
    scenes: int | None = None  # None: DEFAULT_SCENES
    kind: str = "tool_intro"
    confidentiality: str = CONFIDENTIAL  # reel.confidentiality に書く。general 以外は社外秘
    avoid_words: tuple[str, ...] = ()  # 動画で触れない語（設定 avoid_words）

    def scene_count(self) -> int:
        return self.scenes if self.scenes is not None else DEFAULT_SCENES

    def validate(self) -> None:
        if not _SLUG.match(self.reel_id) or len(self.reel_id) > 64:
            raise ConfigError(f"台本の id は英小文字・数字・-・_ で書いてください（64 字まで）: {self.reel_id}")
        if not self.sources:
            raise ConfigError("--source（資料のテキスト）を 1 つ以上指定してください")
        if self.audience not in AUDIENCES:
            raise ConfigError(f"--audience は A / B / C のどれかです: {self.audience}")
        if self.capture not in CAPTURES:
            raise ConfigError(f"--capture は {' / '.join(CAPTURES)} のどれかです: {self.capture}")
        if self.capture == "web" and not (self.url and re.match(r"^https?://", self.url)):
            raise ConfigError("--capture web のときは --url（http:// か https:// で始まる）が必要です")
        if self.capture != "web" and self.url:
            raise ConfigError("--url は --capture web のときだけ使えます")
        if self.scenes is not None and not 1 <= self.scenes <= 8:
            raise ConfigError("--scenes は 1〜8 にしてください（intro・outro を除く本編のシーン数）")
        if self.confidentiality not in CONFIDENTIALITY_VALUES:
            raise ConfigError(f"--confidentiality は {' / '.join(CONFIDENTIALITY_VALUES)} のどちらかです: {self.confidentiality}")
        if self.kind not in KINDS:
            raise ConfigError(f"--kind は {' / '.join(KINDS)} のどれかです: {self.kind}")
        if self.title is not None and not 1 <= len(self.title) <= 80:
            raise ConfigError("--title は 1〜80 字にしてください")


def default_out_dir(reel_id: str, cwd: Path | None = None) -> Path:
    """``reels/<id>/``（今のフォルダから）。"""
    return (cwd or Path.cwd()) / REELS_DIR / reel_id


@dataclass
class SourceText:
    path: Path
    text: str
    sha256: str
    chars: int
    truncated: bool = False
    condensed_from: int | None = None  # 要点に縮めたとき、元の字数


def read_sources(paths: list[Path], limit: int = SOURCE_LIMIT_CHARS) -> tuple[list[SourceText], list[str]]:
    """手元のファイルだけ。合計が ``limit`` 字を超えたら切る（警告つき）。

    下書きの呼び出しに収まるかはトークンの予算で決める（長ければ要点に縮める）。"""
    out: list[SourceText] = []
    warnings: list[str] = []
    budget = limit
    for path in paths:
        try:
            raw = Path(path).read_text(encoding="utf-8-sig")
        except FileNotFoundError as cause:
            raise ConfigError(f"--source のファイルがありません: {path}") from cause
        except UnicodeDecodeError as cause:
            raise ConfigError(f"--source を UTF-8 として読めません: {path}") from cause
        except OSError as cause:
            raise ConfigError(f"--source を読めません: {path}: {cause}") from cause
        text = raw.strip()
        if not text:
            raise ConfigError(f"--source が空です: {path}")
        piece = text[:budget]
        truncated = len(piece) < len(text)
        if truncated:
            warnings.append(f"{Path(path).name}: 長いため先頭 {len(piece)} 字だけを使いました（全 {len(text)} 字）")
        budget -= len(piece)
        out.append(SourceText(Path(path), piece, hashlib.sha256(raw.encode("utf-8")).hexdigest(), len(text), truncated))
        if budget <= 0:
            rest = paths[paths.index(path) + 1:]
            if rest:
                warnings.append("資料が長いため、次のファイルは使いませんでした: " + ", ".join(Path(p).name for p in rest))
            break
    return out, warnings


_CAPTURE_NOTE = {
    "diagram": ("各シーンの画像は説明図（あとで HTML で描く）。capture_steps には、その図に描くもの（部品・矢印・数値）を"
                "文章で書く"),
    "web": "Web 画面（{url}）を撮影する。capture_steps はブラウザでの操作の手順を文章で書く",
    "manual": "人が画面を撮影・用意する。capture_steps は撮影・用意の指示を文章で書く",
}


def build_prompt(req: DraftRequest, sources: list[SourceText]) -> str:
    scenes = req.scene_count()
    title_rule = f"- title は「{req.title}」とする" if req.title else "- title は動画の題名（40 字程度まで）"
    kind = KIND_PROMPTS[req.kind]
    lines = [
        f"次の資料から、{kind}の台本の下書きを、JSON だけで出力してください。説明文やコードブロックは付けません。",
        "",
        "## 条件",
        f"- 見る人: {AUDIENCES[req.audience]}",
        f"- 画像: {_CAPTURE_NOTE[req.capture].format(url=req.url)}",
        f"- 本編のシーンは {scenes} つ。冒頭（intro）とまとめ（outro）は別に書く",
        title_rule,
        *(["- 構成の決まり: 問い（身近な場面）→ しくみ → 比べる・条件 → 選び方・減らし方 → まとめ（確認すること）。"
            "この順でシーンを並べる"] if req.kind == "explainer" else []),
        "- summary: この動画で分かること（画面に出す 1〜2 文、120 字以内）",
        "- intro_narration: 冒頭のナレーション（2〜3 文、話し言葉）",
        "- scenes[].heading: 行動の見出し。20 字以内で、動詞で終える（例: 条件を入力する、結果を確かめる、しくみをつかむ）",
        "- scenes[].where: 画面・図のどこか（例: ブラウザ（左の入力欄）、説明図）",
        "- scenes[].on_screen_text: 画面に出す短文（60 字以内、任意）",
        "- scenes[].narration: そのシーンのナレーション（2〜3 文、話し言葉）",
        "- scenes[].check: そのシーンで確かめること（1 文）",
        "- scenes[].capture_steps: 人が読める文章で 1〜3 個。CSS セレクタや XPath は書かない",
        "- scenes[].shot_name: 画像の短い名前（英小文字・数字・_ で 24 字以内。例: input_form）",
        "- outro: summary（120 字以内）、checks（注意点・確認事項）、next（次の行動）、narration（2〜3 文）",
        "- 資料に書かれていない機能・数値を足さない。数値は資料に書かれたとおりに使う",
    ]
    if req.avoid_words:
        lines.append(f"- 次の語には触れない: {'、'.join(req.avoid_words)}")
    lines += [
        "",
        "## 形式",
        '{"title": "…", "summary": "…", "prerequisites": ["…"], "intro_narration": "…",',
        ' "scenes": [{"heading": "…", "where": "…", "on_screen_text": "…", "narration": "…", "check": "…",',
        '             "capture_steps": ["…"], "shot_name": "…"}],',
        ' "outro": {"summary": "…", "checks": ["…"], "next": "…", "narration": "…"}}',
        "",
        "## 資料",
    ]
    for source in sources:
        note = f"（要点。元の資料 {source.condensed_from} 字を縮めたもの）" if source.condensed_from else ""
        lines += [f"### {source.path.name}{note}", source.text, ""]
    return "\n".join(lines).rstrip() + "\n"


# -- 台本（Markdown。コードが組み立てる） --------------------------------------------------------

def _yaml_block(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False).rstrip()


def _plain(text: str) -> str:
    """ナレーションを段落だけの文章に（段落の間は空行。Markdown の構造は持たない）。"""
    paragraphs = [" ".join(line.strip() for line in block.splitlines() if line.strip())
                  for block in re.split(r"\n\s*\n", text.strip())]
    return "\n\n".join(p for p in paragraphs if p)


def output_name(reel_id: str) -> str:
    return reel_id.replace("-", "_")


def scene_image(req: DraftRequest, sid: str, shot: str, steps: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(image, capture) — 1 シーンぶん。"""
    if req.capture == "web":
        image = {"source": "web", "ref": f"captures/{req.reel_id}/{sid}_{shot}.png", "label": "実キャプチャ"}
        return image, {"url": req.url, "steps": steps}
    if req.capture == "manual":
        image = {"source": "manual", "ref": f"captures/{req.reel_id}/{sid}_{shot}.png", "label": "実キャプチャ"}
        return image, {"instructions": " / ".join(steps)}
    image = {"source": "generated", "ref": f"assets/{sid}_{shot}.png", "label": "説明用再構成図"}
    return image, {"prompt": " / ".join(steps)}


def build_markdown(req: DraftRequest, value: dict[str, Any], *, model: str, sources: list[SourceText],
                   condensed: bool = False) -> str:
    title = req.title or value["title"].strip()
    reel = {"id": req.reel_id, "title": title, "schema_version": sb.SCHEMA_VERSION, "audience": req.audience,
            "kind": req.kind, "confidentiality": normalize_confidentiality(req.confidentiality), "aspect": "16:9",
            "output_name": output_name(req.reel_id)}
    not_ready = {"diagram": "説明図は未作成（ref は書き出しの予定パス。capture.prompt を見て diagrams/ に HTML を書き、"
                            "capture に tool: html と src を足す）。",
                 "web": "画像は未撮影（ref は撮影の予定パス）。",
                 "manual": "画像は未用意（ref の場所に置くまで erkit check は不合格）。"}[req.capture]
    out = ["---", _yaml_block(reel), "---", "", f"# {title}", "",
           "<!--",
           f"台本の下書き。手元の LLM（{model}）が次の資料から作った。人が直してから使う。",
           *[f"資料: {s.path.name}（sha256 {s.sha256[:12]}…、{s.chars} 字{'、一部のみ使用' if s.truncated else ''}"
             f"{'、要点に縮めて使用（draft.json の condensed）' if condensed else ''}）" for s in sources],
           not_ready + "注釈（recipe_params.mark）は撮影・説明図の mark の名前が決まってから書く。",
           "数値・事実は資料で確かめる。区分（confidentiality）を general に変えるのは人だけ。",
           "-->", ""]

    def section(title_line: str, data: dict[str, Any], narration: str) -> None:
        out.extend([f"## {title_line}", "```yaml", _yaml_block(data), "```", _plain(narration), ""])

    intro: dict[str, Any] = {"summary": value["summary"].strip()}
    prerequisites = [p.strip() for p in value.get("prerequisites") or [] if isinstance(p, str) and p.strip()]
    if prerequisites:
        intro["prerequisites"] = prerequisites
    intro["duration_note"] = "未計測"
    section("intro", intro, value["intro_narration"])

    for index, scene in enumerate(value["scenes"], start=1):
        sid = f"s{index:02d}"
        shot = scene["shot_name"].strip()
        steps = [s.strip() for s in scene["capture_steps"] if s.strip()]
        image, capture = scene_image(req, sid, shot, steps)
        data: dict[str, Any] = {"where": scene["where"].strip(), "image": image}
        on_screen = (scene.get("on_screen_text") or "").strip()
        if on_screen:
            data["on_screen_text"] = on_screen
        data["recipe"] = "highlight_box"
        data["check"] = scene["check"].strip()
        data["capture"] = capture
        section(f"{sid}: {scene['heading'].strip()}", data, scene["narration"])

    outro_src = value["outro"]
    outro: dict[str, Any] = {"summary": outro_src["summary"].strip()}
    checks = [c.strip() for c in outro_src.get("checks") or [] if isinstance(c, str) and c.strip()]
    if checks:
        outro["checks"] = checks
    if isinstance(outro_src.get("next"), str) and outro_src["next"].strip():
        outro["next"] = outro_src["next"].strip()
    section("outro", outro, outro_src["narration"])
    return "\n".join(out).rstrip() + "\n"


# -- 確かめ ---------------------------------------------------------------------------------------

def _spoken_and_shown(value: dict[str, Any]) -> list[tuple[str, str]]:
    """動画で話す・見せるすべての (場所, 文)。"""
    items = [("title", value.get("title")), ("summary", value.get("summary")),
             ("intro_narration", value.get("intro_narration"))]
    for i, scene in enumerate(value.get("scenes") or []):
        if isinstance(scene, dict):
            for key in ("heading", "on_screen_text", "narration", "check"):
                items.append((f"scenes[{i}].{key}", scene.get(key)))
    outro = value.get("outro") if isinstance(value.get("outro"), dict) else {}
    for key in ("summary", "next", "narration"):
        items.append((f"outro.{key}", outro.get(key)))
    for i, check in enumerate(outro.get("checks") or []):
        items.append((f"outro.checks[{i}]", check))
    return [(w, t) for w, t in items if isinstance(t, str)]


def markup_problems(value: dict[str, Any]) -> list[str]:
    problems = []
    for where, text in _spoken_and_shown(value):
        if "```" in text or "<!--" in text or re.search(r"(?m)^\s*##", text):
            problems.append(f"{where} に Markdown の記号（``` / ## / <!--）を使わないでください")
    return problems


def avoid_word_warnings(value: dict[str, Any], words: tuple[str, ...] | list[str]) -> list[str]:
    """動画で触れない語（設定 avoid_words）が、話す・見せる文や撮影の手順に出ていないか。大文字・小文字は区別しない。"""
    out = []
    targets = list(_spoken_and_shown(value))
    for i, scene in enumerate(value.get("scenes") or []):
        if isinstance(scene, dict):
            targets += [(f"scenes[{i}].capture_steps", s) for s in scene.get("capture_steps") or [] if isinstance(s, str)]
    for word in words:
        if not word:
            continue
        needle = word.casefold()
        for where, text in targets:
            if needle in text.casefold():
                out.append(f"{where} に、動画で触れない語「{word}」が出ています")
    return out


def _numbers(text: str) -> set[float]:
    found = set()
    for m in _ANY_NUMBER.finditer(text):
        try:
            found.add(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return found


def unsupported_numbers(value: dict[str, Any], sources: list[SourceText], req: DraftRequest) -> list[str]:
    """単位つきの数で、資料のどこにもないもの（作り話の疑い）。"""
    known = set()
    for s in sources:
        known |= _numbers(s.text)
    known |= _numbers(req.title or "") | _numbers(req.url or "")
    warnings = []
    seen = set()
    for where, text in _spoken_and_shown(value):
        for m in _NUMBER_WITH_UNIT.finditer(text):
            try:
                number = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if number in known or (where, m.group(0)) in seen:
                continue
            seen.add((where, m.group(0)))
            warnings.append(f"{where}: 「{m.group(0)}」の数値が資料のどこにもありません（作り話の疑い）")
    return warnings


def soft_warnings(value: dict[str, Any], sources: list[SourceText], req: DraftRequest) -> list[str]:
    warnings = unsupported_numbers(value, sources, req) + avoid_word_warnings(value, req.avoid_words)
    for i, scene in enumerate(value.get("scenes") or []):
        heading = scene.get("heading", "")
        if len(heading) > 20:
            warnings.append(f"scenes[{i}].heading が {len(heading)} 字です（20 字以内を推奨）: {heading}")
        n = len(_SENTENCE_END.findall(scene.get("narration", "")))
        if not 2 <= n <= 3:
            warnings.append(f"scenes[{i}].narration が {n} 文です（2〜3 文を推奨）")
        for step in scene.get("capture_steps") or []:
            if _SELECTOR.search(step):
                warnings.append(f"scenes[{i}].capture_steps にセレクタらしい書き方があります（操作定義で書く）: {step}")
    n = len(_SENTENCE_END.findall(value.get("intro_narration", "")))
    if not 2 <= n <= 4:
        warnings.append(f"intro_narration が {n} 文です（2〜3 文を推奨）")
    return warnings


# -- 実行 ---------------------------------------------------------------------------------------

@dataclass
class DraftResult:
    ok: bool
    out_dir: Path
    markdown: Path | None
    record: Path
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    rewrites: int = 0


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_new(path: Path, text: str) -> None:
    """``path`` が無いときだけ書く（上書きしない。先に一時ファイルへ書いてから置く）。"""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        with open(path, "x", encoding="utf-8"):
            pass
    except FileExistsError as cause:
        tmp.unlink(missing_ok=True)
        raise OutputError(f"既にあります（上書きしません）: {path}") from cause
    tmp.replace(path)


def draft_max_tokens(scenes: int, cap: int) -> int:
    return min(cap, DRAFT_TOKENS_BASE + DRAFT_TOKENS_PER_SCENE * scenes)


def storyboard_path(out_dir: Path, reel_id: str) -> Path:
    return Path(out_dir) / f"{reel_id}.storyboard.md"


def draft_storyboard(
    client: LLMClient,
    req: DraftRequest,
    out_dir: Path,
    *,
    task: Task | None,
    explicit_model: str | None = None,
    explicit_thinking: str | None = None,
    explicit_max_tokens: int | None = None,
    retries: int = DEFAULT_RETRIES,
    offline_checks: list[dict[str, Any]] | None = None,
    condense_task: Task | None = None,
    measure: bool = True,
    log: Callable[[str], None] = lambda message: None,
) -> DraftResult:
    """生成 → 確かめ → 書き直し → 組み立て → 検証。``<id>.storyboard.md`` と ``draft.json`` を書く。

    失敗（書き直しても不合格・サーバーの失敗）のときは ``draft.json`` だけを書く。台本は上書きしない。
    """
    req.validate()
    if normalize_confidentiality(req.confidentiality) != GENERAL and client.confidentiality == GENERAL:
        raise RouteBlockedError("社外秘の区分（confidential）の資料は、社外秘の区分で作ったクライアント"
                                "（この PC だけに送る）でしか送りません")
    scenes = req.scene_count()
    out_dir = Path(out_dir)
    md_path = storyboard_path(out_dir, req.reel_id)
    if md_path.exists():
        raise OutputError(f"既にあります（上書きしません）: {md_path}")
    sources, warnings = read_sources(req.sources)
    low, high = RECOMMENDED_SCENES
    if not low <= scenes <= high:
        warnings.append(f"本編のシーン数 {scenes} は、台本の検証の推奨 {low}〜{high} の外です")
    settings = task_settings(task, client.endpoint, explicit_model=explicit_model, explicit_thinking=explicit_thinking,
                             explicit_max_tokens=explicit_max_tokens, default_thinking="off", default_max_tokens=4096)
    model = client.require_model(settings.model, task=None if explicit_model else settings.task) \
        if settings.model else client.resolve_model()
    budget = Budget(settings.expected_context or DEFAULT_CONTEXT)
    cap = settings.max_tokens
    if explicit_max_tokens:
        max_tokens, max_tokens_source = explicit_max_tokens, "--max-tokens"
    else:  # 答えに要るぶんだけにして、残りの文脈を資料に回す
        max_tokens = draft_max_tokens(scenes, cap)
        max_tokens_source = f"シーン数から（{DRAFT_TOKENS_BASE}＋{DRAFT_TOKENS_PER_SCENE}×{scenes}、上限 {cap}）"
    measurer = Measurer(client, model, settings.thinking, enabled=measure)

    def draft_messages(texts: list[SourceText]) -> list[dict[str, str]]:
        return [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(req, texts)}]

    # 呼び出しが文脈長に収まること。長い資料は先に task light で要点に縮める
    bare = draft_messages([])
    budget.require(bare, max_tokens, what="台本の下書き（資料なしの指示だけ）")
    messages = draft_messages(sources)
    room = budget.room(max_tokens)
    full_estimate = estimate_messages(messages)
    full_tokens, full_measured = full_estimate, False
    if full_estimate > room:  # 見積もりは多めなので、縮めると決める前に測る
        log(f"資料の全文の見積もり {full_estimate} トークンが予算 {room} を超えるため、実際のトークン数を測ります…")
        full_tokens, full_measured = measurer.cost(messages, what="資料の全文での下書きの呼び出し")
    base_tokens = full_tokens if full_measured else None
    light = None
    light_model = ""
    if full_tokens > room:
        if condense_task is None:
            raise BudgetError(f"資料が長く（{'実測' if full_measured else '見積もり'} {full_tokens} トークン）、下書きの"
                              f"呼び出しが文脈長 {budget.context} に収まりません。縮めるための task light が設定にありません")
        light = task_settings(condense_task, client.endpoint, default_thinking="off", default_max_tokens=2048)
        light_model = client.require_model(light.model, task=light.task) if light.model else model
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as cause:
        raise OutputError(f"出力フォルダを作れません: {out_dir}: {cause}") from cause

    built: dict[str, Any] = {}
    condensed: dict[str, Any] = {}
    record_path = out_dir / RECORD_NAME
    budget_record: dict[str, Any] = {
        "context": budget.context, "max_tokens": max_tokens, "max_tokens_source": max_tokens_source,
        "max_tokens_cap": cap, "margin": budget.margin,
        "estimate": "日本語など 1 字 ≈ 1 トークン、英数字 4 字 ≈ 1 トークン（多め）",
        "measure": "max_tokens=1 の呼び出しの usage.prompt_tokens（測れなければ見積もり）",
        "full_input_estimated_tokens": full_estimate,
        "full_input_measured_tokens": full_tokens if full_measured else None,
        "input": "full" if light is None else "condensed", "measurements": measurer.log}

    def texts_from(by_name: dict[str, str]) -> list[SourceText]:
        return [SourceText(s.path, by_name.get(s.path.name, ""), s.sha256, s.chars, s.truncated, condensed_from=s.chars)
                for s in sources]

    def base_record() -> dict[str, Any]:
        return _base_record(req, scenes, offline_checks, sources, client, model, settings, retries)

    if light is not None:
        ratio = full_tokens / full_estimate if full_measured else 1.0
        target = int((room - estimate_messages(bare) - 32 * len(sources)) * 0.85)
        seen: dict[str, tuple[int, bool]] = {}

        def fits(by_name: dict[str, str], what: str) -> tuple[bool, int, bool]:
            msgs = draft_messages(texts_from(by_name))
            key = json.dumps(by_name, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                estimate = estimate_messages(msgs)
                predicted = math.ceil(estimate * ratio)  # 全文で測った比で
                if estimate <= room:
                    seen[key] = (estimate, False)
                elif predicted > budget.context:  # 明らかに長い: サーバーが断るので送らない
                    seen[key] = (predicted, False)
                else:
                    seen[key] = measurer.cost(msgs, what=what)
            tokens, was_measured = seen[key]
            return tokens <= room, tokens, was_measured

        outcome = fit_sources(client, [(s.path.name, s.text) for s in sources],
                              light=LightTask(light_model, Budget(light.expected_context or DEFAULT_CONTEXT),
                                              light.max_tokens, light.thinking),
                              total_target_chars=target, fits=fits, room=room, ratio=ratio, log=log)
        condensed.update(task=light.task, model=light_model, thinking=light.thinking, max_tokens_cap=light.max_tokens,
                         target_chars=target, ratio_measured_to_estimated=round(ratio, 3), stages=outcome.stages,
                         pieces=[p.as_dict() for p in outcome.pieces], trimmed=outcome.trimmed)
        texts = texts_from(outcome.texts)
        condensed["text"] = "\n\n".join(t.text for t in texts)
        warnings += outcome.warnings
        if outcome.error is not None:
            failed = base_record()
            failed.update(status="failed", error=outcome.error, warnings=warnings, budget=budget_record,
                          condensed=condensed, attempts=[], rewrites=0)
            _atomic_write(record_path, json.dumps(failed, ensure_ascii=False, indent=2) + "\n")
            return DraftResult(False, out_dir, None, record_path, warnings, outcome.error, 0)
        messages = draft_messages(texts)
        tokens, was_measured = seen[json.dumps(outcome.texts, ensure_ascii=False, sort_keys=True)]
        base_tokens = tokens if was_measured else None
        warnings.append(f"資料が長いため、task {light.task}（{light_model}）で要点に縮めてから下書きを作りました"
                        "（要点は draft.json の condensed。数値の照合は元の全文に対して行う）")

    schema = intermediate_schema(scenes)

    def validate(value: Any) -> list[str]:
        problems = schema_problems(value, schema) or markup_problems(value)
        if problems:
            return problems
        markdown = build_markdown(req, value, model=model, sources=sources, condensed=bool(condensed))
        try:
            doc = sb.markdown_to_storyboard(markdown)
        except sb.ConversionError as error:
            return [f"台本に組み立てられません: {error}"]
        report = sb.validate_storyboard(doc, base_dir=out_dir)
        # manual の画像は実在を確かめる。下書きではまだ無い — 書き直しではなく警告にする
        not_ready = [e for e in report.errors if e.startswith("[image]")]
        errors = [e for e in report.errors if e not in not_ready]
        if errors:
            return [f"台本の検証で不合格: {e}" for e in errors]
        built.update(markdown=markdown,
                     report_warnings=list(report.warnings) + [f"{e}（撮影・用意してから置く）" for e in not_ready])
        return []

    budget_record["draft_estimated_tokens"] = estimate_messages(messages)
    budget_record["draft_measured_tokens"] = base_tokens
    prompt_tokens = base_tokens if base_tokens is not None else estimate_messages(messages)
    started = time.monotonic()
    log(f"台本の下書きを作ります（{model}、思考 {settings.thinking}、本編のシーン {scenes}、"
        f"{'実測' if base_tokens is not None else '見積もり'} {prompt_tokens}＋出力 {max_tokens} / 文脈長 {budget.context} トークン）…")
    result: StructuredResult = generate(client, messages, model=model, validate=validate, retries=retries,
                                        max_tokens=max_tokens, temperature=0.3, thinking=settings.thinking,
                                        budget=budget, length_advice=LENGTH_ADVICE, what="台本の下書き",
                                        base_tokens=base_tokens,
                                        max_tokens_cap=None if explicit_max_tokens else cap, log=log)
    elapsed = time.monotonic() - started

    record = base_record()
    record.update({
        "status": "done" if result.ok else "failed",
        "budget": budget_record,
        "condensed": condensed or None,
        "elapsed_sec": round(elapsed, 3),
        "rewrites": result.rewrites,
        "attempts": [a.as_dict() for a in result.attempts],
        "error": result.error,
    })
    record["llm"]["thinking_params"] = result.thinking_params
    if not result.ok:
        record["warnings"] = warnings
        record["last_answer"] = result.attempts[-1].content if result.attempts else ""
        _atomic_write(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return DraftResult(False, out_dir, None, record_path, warnings, result.error, result.rewrites)

    warnings = warnings + soft_warnings(result.value, sources, req) + [f"台本の検証: {w}" for w in built["report_warnings"]]
    _write_new(md_path, built["markdown"])
    record["warnings"] = warnings
    record["outputs"] = {"markdown": str(md_path)}
    record["intermediate"] = result.value
    _atomic_write(record_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return DraftResult(True, out_dir, md_path, record_path, warnings, None, result.rewrites)


def _base_record(req: DraftRequest, scenes: int, offline_checks: list[dict[str, Any]] | None,
                 sources: list[SourceText], client: LLMClient, model: str, settings: Any,
                 retries: int) -> dict[str, Any]:
    return {
        "format": DRAFT_FORMAT,
        "version": DRAFT_VERSION,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "failed",
        "reel_id": req.reel_id,
        "request": {"title": req.title, "audience": req.audience, "capture": req.capture, "url": req.url,
                    "scenes": scenes, "scenes_source": "--scenes" if req.scenes is not None else f"既定 {DEFAULT_SCENES}",
                    "kind": req.kind, "avoid_words": list(req.avoid_words)},
        "confidentiality": normalize_confidentiality(req.confidentiality),
        "client_confidentiality": client.confidentiality,
        "offline": offline_checks is not None,
        "offline_checks": offline_checks or [],
        "sources": [{"path": str(s.path), "sha256": s.sha256, "chars": s.chars, "truncated": s.truncated}
                    for s in sources],
        "llm": {"profile": client.endpoint.name, "base_url": client.endpoint.base_url,
                "model": model, "model_source": settings.model_source or "サーバーに読み込まれているモデル",
                "task": settings.task, "thinking": settings.thinking, "thinking_params": {},
                "max_tokens": settings.max_tokens, "retries": retries},
        "elapsed_sec": 0.0,
        "rewrites": 0,
        "attempts": [],
        "error": None,
        "warnings": [],
        "outputs": {},
    }
