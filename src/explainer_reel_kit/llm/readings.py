"""``erkit voice suggest``: 読み辞書への追記候補（表示だけ。辞書は書かない）。

流れ: ``kana`` の表には、語ごとに「エンジンが今どう読むか」がある。LLM に「ナレーションで
どう読むべきか」（カタカナ）を聞き、長音・区切りの違いを除いて比べ、違う語だけを
読み辞書（``dictionaries/<名前>.yaml`` の ``entries``）への追記案として**表示する**。
書き込みはしない。採るかどうかは人が、できれば聞いて確かめて決める。

ナレーションの原稿を LLM に送るので、クライアントは台本の区分で作る（未記入は社外秘 = この PC だけ）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .client import LLMClient
from .config import LLMConfig, task_settings
from .structured import DEFAULT_RETRIES, generate

# -- kana normalisation -------------------------------------------------------------------

_VOWEL_OF: dict[str, str] = {}
for _vowel, _row in {
    "ア": "アカサタナハマヤラワガザダバパァャヮ",
    "イ": "イキシチニヒミリギジヂビピィ",
    "ウ": "ウクスツヌフムユルグズヅブプゥュヴ",
    "エ": "エケセテネヘメレゲゼデベペェ",
    "オ": "オコソトノホモヨロヲゴゾドボポォョ",
}.items():
    for _char in _row:
        _VOWEL_OF[_char] = _vowel

_DROP = re.compile(r"[\s/,、。，．.'’・「」！？!?ー\u30fc]")  # ー is expanded before dropping


def to_katakana(text: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def normalize_kana(text: str) -> str:
    """Compare readings, not spellings: the engine writes long vowels as トオ / セエ / メエトル.

    - hiragana → katakana; accent-phrase marks, pauses and punctuation are removed
    - ー becomes the vowel of the mora before it
    - ウ after an o-row mora → オ, イ after an e-row mora → エ (トウ = トオ, セイ = セエ)
    """
    chars = list(to_katakana(text))
    out: list[str] = []
    for char in chars:
        if char in "ー\u30fc":
            if out and out[-1] in _VOWEL_OF:
                out.append(_VOWEL_OF[out[-1]])
            continue
        if _DROP.match(char):
            continue
        if out and char == "ウ" and _VOWEL_OF.get(out[-1]) == "オ":
            char = "オ"
        elif out and char == "イ" and _VOWEL_OF.get(out[-1]) == "エ":
            char = "エ"
        out.append(char)
    return "".join(out)


def is_katakana_reading(text: str) -> bool:
    return bool(text) and all(("ァ" <= c <= "ヺ") or c in "ー・ " for c in text)


# -- data -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadingCheck:
    term: str
    engine_reading: str  # what the engine reads now (after the dictionary, if the term has an entry)
    dictionary_reading: str | None = None
    engine_raw: str | None = None  # the term as written, without the dictionary
    context: str = ""


@dataclass
class Suggestion:
    term: str
    status: str  # "match" | "mismatch" | "no_candidate"
    engine_reading: str
    candidate: str | None
    dictionary_reading: str | None
    note: str = ""
    yaml_line: str | None = None


@dataclass
class SuggestionReport:
    model: str
    profile: str
    suggestions: list[Suggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    task: str | None = None
    thinking: str = "off"
    records: list[dict[str, Any]] = field(default_factory=list)  # attempts per batch (structured.py)

    @property
    def rewrites(self) -> int:
        return sum(r.get("rewrites", 0) for r in self.records)

    @property
    def mismatches(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.status == "mismatch"]


# -- asking the LLM ----------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "あなたは日本語のナレーション原稿の校正担当です。"
    "語の読みをカタカナで答えます。JSON だけを出力します。"
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["readings"],
    "properties": {
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["term", "reading"],
                "properties": {"term": {"type": "string"}, "reading": {"type": "string"}},
            },
        }
    },
}


def build_prompt(checks: list[ReadingCheck]) -> str:
    lines = [
        "解説動画のナレーションで、次の語をどう読み上げるべきかを、カタカナで答えてください。",
        "- 原稿の文脈での読み（同じ字で読みが変わる語は、原稿での使われ方で決める）",
        "- 英字の製品名・UI 名はカタカナの読みにする",
        "- 数字・単位・記号も読みに含める（例: 150ミリ → ヒャクゴジュウミリ）",
        "- 長音は「ー」で書いてよい",
        '形式: {"readings": [{"term": "語", "reading": "カタカナ"}]}（すべての語について 1 件ずつ）',
        "",
        "語（括弧内は原稿での使われ方）:",
    ]
    for check in checks:
        context = f"（{check.context}）" if check.context else ""
        lines.append(f"- {check.term}{context}")
    return "\n".join(lines)


def readings_validator(batch: list[ReadingCheck]) -> Callable[[Any], list[str]]:
    """Every term of the batch must have a katakana reading (problems are written for the model)."""
    wanted = [c.term for c in batch]

    def validate(value: Any) -> list[str]:
        got: dict[str, str] = {}
        for entry in value["readings"]:
            got.setdefault(entry["term"].strip(), entry["reading"].strip())
        problems = []
        missing = [t for t in wanted if t not in got]
        if missing:
            problems.append("次の語の読みがありません: " + "、".join(missing))
        bad = [f"{t}（{got[t]}）" for t in wanted if t in got and not is_katakana_reading(got[t])]
        if bad:
            problems.append("読みはカタカナだけで書いてください: " + "、".join(bad))
        return problems

    return validate


def ask_readings(
    client: LLMClient,
    checks: list[ReadingCheck],
    *,
    model: str,
    batch_size: int = 20,
    thinking: str = "off",
    max_tokens: int = 2048,
    retries: int = DEFAULT_RETRIES,
    records: list[dict[str, Any]] | None = None,
    log: Callable[[str], None] = lambda message: None,
) -> tuple[dict[str, str], list[str]]:
    """{term: katakana reading} and warnings, via generate → check → rewrite (structured.py).

    A batch that still fails after the rewrites is reported; its readable katakana entries are kept.
    ``records`` (if given) receives each batch's attempts, for the caller to keep.
    """
    readings: dict[str, str] = {}
    warnings: list[str] = []
    for start in range(0, len(checks), max(1, batch_size)):
        batch = checks[start : start + batch_size]
        label = f"語 {start + 1}–{start + len(batch)}"
        log(f"llm readings {start + 1}–{start + len(batch)} / {len(checks)} …")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": build_prompt(batch)}]
        result = generate(client, messages, model=model, schema=RESPONSE_SCHEMA, validate=readings_validator(batch),
                          retries=retries, max_tokens=max(max_tokens, 256 + 48 * len(batch)), temperature=0,
                          thinking=thinking, log=log)
        if records is not None:
            records.append({"batch": label, **result.as_dict()})
        if not result.ok:
            warnings.append(f"{label}: {result.error}")
        value = result.value
        if not isinstance(value, dict) or not isinstance(value.get("readings"), list):
            continue
        wanted = {c.term for c in batch}
        for entry in value["readings"]:
            if not isinstance(entry, dict):
                continue
            term, reading = str(entry.get("term", "")).strip(), str(entry.get("reading", "")).strip()
            if term not in wanted:
                continue
            if not is_katakana_reading(reading):
                warnings.append(f"{term}: 候補「{reading}」がカタカナではないため使いません")
                continue
            readings.setdefault(term, reading)
    return readings, warnings


# -- comparing ------------------------------------------------------------------------------


def compare(checks: list[ReadingCheck], candidates: dict[str, str]) -> list[Suggestion]:
    out: list[Suggestion] = []
    for check in checks:
        candidate = candidates.get(check.term)
        if candidate is None:
            out.append(Suggestion(check.term, "no_candidate", check.engine_reading, None, check.dictionary_reading,
                                  "LLM の候補なし"))
            continue
        expected = normalize_kana(candidate)
        if normalize_kana(check.engine_reading) == expected:
            note = ""
            if check.dictionary_reading is not None and check.engine_raw is not None \
                    and normalize_kana(check.engine_raw) == expected:
                note = "原文のままでも候補どおり（辞書から外せる候補）"
            out.append(Suggestion(check.term, "match", check.engine_reading, candidate, check.dictionary_reading, note))
            continue
        suggestion = Suggestion(check.term, "mismatch", check.engine_reading, candidate, check.dictionary_reading)
        if check.dictionary_reading is None:
            suggestion.note = "辞書への追加候補"
            suggestion.yaml_line = f"  {check.term}: {candidate.replace(' ', '')}"
        elif normalize_kana(check.dictionary_reading) != expected:
            suggestion.note = f"辞書の読み「{check.dictionary_reading}」と候補が違う（書き換え候補）"
            suggestion.yaml_line = f"  {check.term}: {candidate.replace(' ', '')}   # 現在: {check.dictionary_reading}"
        else:
            suggestion.note = "辞書の読みは候補どおりだが、エンジンが別に読む（ユーザー辞書への登録の候補）"
        out.append(suggestion)
    return out


def suggest(
    client: LLMClient,
    checks: list[ReadingCheck],
    *,
    model: str | None = None,
    task: str | None = "light",
    config: LLMConfig | None = None,
    batch_size: int = 20,
    log: Callable[[str], None] = lambda message: None,
) -> SuggestionReport:
    """Reading candidates with the ``light`` task's model . ``model`` (explicit) wins.

    The model must be on the server; otherwise ModelNotFoundError — no other model is used.
    """
    task_obj = config.tasks.get(task) if (config is not None and task) else None
    settings = task_settings(task_obj, client.endpoint, explicit_model=model, default_thinking="off")
    if settings.model:
        chosen = client.require_model(settings.model, task=None if model else settings.task)
    else:
        chosen = client.resolve_model()
    records: list[dict[str, Any]] = []
    candidates, warnings = ask_readings(client, checks, model=chosen, batch_size=batch_size,
                                        thinking=settings.thinking, max_tokens=settings.max_tokens,
                                        records=records, log=log)
    report = SuggestionReport(chosen, client.endpoint.name, compare(checks, candidates), warnings)
    report.task = settings.task
    report.thinking = settings.thinking
    report.records = records
    return report


def _cell(text: str | None) -> str:
    return "—" if text is None else text.replace("|", "\\|").replace("\n", " ")


def render_section(report: SuggestionReport) -> str:
    label = {"match": "一致", "mismatch": "**不一致**", "no_candidate": "候補なし"}
    lines = [
        "## LLM による読みの候補（追記案。自動では書きません）",
        "",
        f"- LLM: {report.model}（profile {report.profile}、"
        f"{'task ' + report.task if report.task else 'task なし'}、思考 {report.thinking}）",
        f"- 検査と書き直し: 書き直し {report.rewrites} 回（全 {len(report.records)} 回の問い合わせ）",
        "- エンジンの読みと LLM の候補を、長音・区切りの違いを無視して比べた。候補も誤ることがあるので、聞いて確かめてから採用する",
        "",
        "| 用語 | エンジンの読み（今） | LLM の候補 | 判定 | メモ |",
        "|---|---|---|---|---|",
    ]
    for s in report.suggestions:
        lines.append(f"| {_cell(s.term)} | {_cell(s.engine_reading)} | {_cell(s.candidate)} | {label[s.status]} | "
                     f"{_cell(s.note) if s.note else ''} |")
    yaml_lines = [s.yaml_line for s in report.mismatches if s.yaml_line]
    lines += ["", "### 読み辞書（dictionaries/<名前>.yaml）の entries への追記案", ""]
    if yaml_lines:
        lines += ["```yaml", *yaml_lines, "```"]
    else:
        lines.append("なし")
    if report.warnings:
        lines += ["", "### 警告", "", *[f"- {w}" for w in report.warnings]]
    return "\n".join(lines) + "\n"


def reading_checks(rows: list[Any], texts: list[Any]) -> list[ReadingCheck]:
    """``narration.kana`` の行（TermRow）と原稿 → ReadingCheck（語ごとに、エンジンが今どう読むか）。"""
    from ..narration.kana import _context_of

    return [
        ReadingCheck(
            term=row.term,
            engine_reading=row.engine_with_dictionary or row.engine_raw,
            dictionary_reading=row.dictionary_reading,
            engine_raw=row.engine_raw,
            context=_context_of(row.term, texts),
        )
        for row in rows
    ]
