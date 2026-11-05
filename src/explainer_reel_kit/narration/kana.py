"""``kana`` command: show how the engine reads dictionary terms and check terms.

For every term found in the narration, the term is sent to ``/audio_query``
twice — as written and after the dictionary — and the reading (katakana)
the engine returns is listed side by side. A human runs this once on the
machine with AivisSpeech Engine and pastes the report; nothing is synthesized.

The reading is built from ``accent_phrases[].moras[].text`` (accent phrases
separated by ``/``, a pause as ``、``). When those are absent, the AudioQuery's
``kana`` string is used instead. This is the engine's text analysis result; how
it finally sounds still has to be confirmed by listening.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import storyboard as sb
from .tts import TTSEngine
from .tts.aivisspeech import reading_of  # noqa: F401  (kept for callers that build readings from an AudioQuery)
from .errors import EngineError, EngineErrorKind, InputError
from .synth import load_input
from .textproc import DEFAULT_MAX_CHARS, PronunciationDictionary, split_paragraph_chunks


@dataclass(frozen=True)
class SourceText:
    source: str  # file name
    item_id: str
    text: str


@dataclass
class TermRow:
    term: str
    dictionary_reading: str | None
    occurrences: int
    items: list[str] = field(default_factory=list)
    engine_raw: str = ""
    engine_with_dictionary: str | None = None


# -- sources ---------------------------------------------------------------------


def load_storyboard_texts(path: str | Path) -> tuple[list[SourceText], int | None]:
    """Narration of a storyboard (.storyboard.md / .json: intro / scenes[] / outro) and its integer speaker, if any.

    Only the narration fields are read; the storyboard schema itself is validated
    by ``erkit check``, not here.
    """
    path = Path(path)
    try:
        doc = sb.load_storyboard(path)
    except FileNotFoundError as cause:
        raise InputError(f"台本が見つかりません: {path}") from cause
    except UnicodeDecodeError as cause:
        raise InputError(f"台本を UTF-8 として読めません: {path}") from cause
    except json.JSONDecodeError as cause:
        raise InputError(f"台本が JSON として解釈できません: {path}: {cause}") from cause
    except sb.ConversionError as cause:
        raise InputError(f"台本を読めません: {path}: {cause}") from cause

    def narration_of(node: Any, where: str) -> str:
        if not isinstance(node, dict) or not isinstance(node.get("narration"), str):
            raise InputError(f"台本の {where}.narration がありません: {path}")
        return node["narration"]

    if not isinstance(doc, dict) or not isinstance(doc.get("scenes"), list):
        raise InputError(f"台本に scenes がありません（台本 JSON ではない？）: {path}")
    label = source_label(path)
    texts = [SourceText(label, "intro", narration_of(doc.get("intro"), "intro"))]
    for index, scene in enumerate(doc["scenes"]):
        scene_id = scene.get("id") if isinstance(scene, dict) else None
        if not isinstance(scene_id, str):
            raise InputError(f"台本の scenes[{index}].id がありません: {path}")
        texts.append(SourceText(label, scene_id, narration_of(scene, f"scenes[{index}]")))
    texts.append(SourceText(label, "outro", narration_of(doc.get("outro"), "outro")))

    reel = doc.get("reel") if isinstance(doc.get("reel"), dict) else {}
    voice = reel.get("voice") if isinstance(reel.get("voice"), dict) else {}
    speaker = voice.get("speaker")
    speaker = speaker if isinstance(speaker, int) and not isinstance(speaker, bool) else None
    return [t for t in texts if t.text.strip()], speaker


def source_label(path: str | Path) -> str:
    name = Path(path).name
    for suffix in (".storyboard.json", ".storyboard.md", ".json", ".md"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def load_input_texts(path: str | Path) -> tuple[list[SourceText], int]:
    narration = load_input(path)
    name = source_label(path)
    return [SourceText(name, item.id, item.text) for item in narration.items], narration.speaker


# -- readings ----------------------------------------------------------------------


class _Reader:
    def __init__(self, engine: TTSEngine, speaker: int) -> None:
        self.engine = engine
        self.speaker = speaker
        self._cache: dict[str, str] = {}

    def __call__(self, text: str) -> str:
        if text not in self._cache:
            reading = self.engine.reading(text, self.speaker)
            self._cache[text] = reading if reading is not None else "（このエンジンは読みを返しません）"
        return self._cache[text]


# -- report ----------------------------------------------------------------------


def collect_terms(
    texts: list[SourceText], dictionary: PronunciationDictionary, *, include_absent: bool = False
) -> list[TermRow]:
    rows: list[TermRow] = []
    candidates = list(dictionary.entries) + dictionary.check_terms
    for term in candidates:
        hits = [t for t in texts if term in t.text]
        if not hits and not include_absent:
            continue
        rows.append(
            TermRow(
                term=term,
                dictionary_reading=dictionary.entries.get(term),
                occurrences=sum(t.text.count(term) for t in hits),
                items=list(dict.fromkeys(f"{t.source}:{t.item_id}" for t in hits)),
            )
        )
    return rows


def _cell(text: str | None) -> str:
    if text is None:
        return "—"
    return text.replace("|", "\\|").replace("\n", " ")


def build_report(
    texts: list[SourceText],
    dictionary: PronunciationDictionary,
    engine: TTSEngine,
    *,
    speaker: int | None,
    include_absent: bool = False,
    sentences: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    sources: list[str] | None = None,
    log: Callable[[str], None] = lambda message: None,
) -> str:
    return build_report_and_rows(
        texts, dictionary, engine, speaker=speaker, include_absent=include_absent, sentences=sentences,
        max_chars=max_chars, sources=sources, log=log,
    )[0]


def build_report_and_rows(
    texts: list[SourceText],
    dictionary: PronunciationDictionary,
    engine: TTSEngine,
    *,
    speaker: int | None,
    include_absent: bool = False,
    sentences: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    sources: list[str] | None = None,
    log: Callable[[str], None] = lambda message: None,
) -> tuple[str, list[TermRow]]:
    """Same report as :func:`build_report`, plus the rows (for the LLM reading candidates)."""
    version = engine.check().version
    voices = engine.voices()
    if not voices:
        raise EngineError(EngineErrorKind.MALFORMED_RESPONSE, "エンジンに話者が 1 つもありません。", endpoint="/speakers")
    by_id = {v.style_id: v for v in voices}
    speaker_note = ""
    if speaker is None:
        speaker = voices[0].style_id
        speaker_note = "（指定なしのためエンジンの先頭の話者）"
    elif speaker not in by_id:
        raise InputError(
            f"声（style id）{speaker} がエンジンにありません。"
            " `erkit voice list` で一覧を確認してください。"
        )
    read = _Reader(engine, speaker)

    rows = collect_terms(texts, dictionary, include_absent=include_absent)
    for row in rows:
        log(f"reading: {row.term}")
        row.engine_raw = read(row.term)
        replaced = dictionary.apply(row.term)
        if replaced != row.term:  # also check terms that contain a dictionary word
            row.engine_with_dictionary = read(replaced)

    lines = [
        "# kana check — エンジンの読み",
        "",
        f"- engine: {engine.name} {engine.url}（version {version}）",
        f"- speaker: {speaker} {by_id[speaker].label}{speaker_note}",
        f"- sources: {', '.join(sources or sorted({t.source for t in texts}))}",
        f"- 辞書: entries {len(dictionary.entries)} 語 / check_terms {len(dictionary.check_terms)} 語"
        f"（本文に出る語 {len(rows)} 語を表示）",
        "- 読みはエンジンの解析結果（AivisSpeech では /audio_query。アクセント句を / で区切る）。実際の聞こえ方は WAV で確認する",
        "",
        "## 用語ごとの読み",
        "",
        "| 用語 | 種別 | 辞書の読み | エンジン（原文のまま） | エンジン（辞書適用後） | 出現 | 場所 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        kind = "辞書" if row.dictionary_reading is not None else "確認のみ"
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row.term),
                    kind,
                    _cell(row.dictionary_reading),
                    _cell(row.engine_raw),
                    _cell(row.engine_with_dictionary),
                    str(row.occurrences),
                    _cell(", ".join(row.items) or "（本文になし）"),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "見方:",
        "- 種別「辞書」: 「原文のまま」が正しければ、その語は辞書に不要（削除候補）。「辞書適用後」が誤りなら読みを直す",
        "- 種別「確認のみ」: 「原文のまま」が誤りなら、その語を entries に追加する",
    ]

    if sentences:
        lines += ["", "## 文ごとの読み（辞書適用後、合成に送る単位）", ""]
        for text in texts:
            groups = split_paragraph_chunks(dictionary.apply(text.text), max_chars)
            lines.append(f"### {text.source}:{text.item_id}")
            lines.append("")
            for p_index, group in enumerate(groups, start=1):
                for chunk in group:
                    log(f"reading: {text.item_id} 段落{p_index}")
                    lines.append(f"- 段落{p_index}: {chunk}")
                    lines.append(f"  - {read(chunk)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n", rows


def _context_of(term: str, texts: list[SourceText], limit: int = 60) -> str:
    """The first sentence in the narration that contains ``term`` (for the LLM)."""
    from .textproc import split_sentences

    for text in texts:
        for sentence in split_sentences(text.text):
            if term in sentence:
                return sentence if len(sentence) <= limit else sentence[:limit] + "…"
    return ""


def reading_checks(rows: list[TermRow], texts: list[SourceText]):
    """kana rows → explainer_reel.llm.readings.ReadingCheck (what the engine reads now, per term)."""
    from explainer_reel.llm.readings import ReadingCheck

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
