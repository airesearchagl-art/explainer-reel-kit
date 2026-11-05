"""Text preparation: pronunciation dictionary, paragraph and sentence splitting.

Splitting rules (fixed by tests/narration/test_textproc.py):

0. A line break separates **paragraphs** (one paragraph per
   annotation mark). Blank / whitespace-only lines are ignored, so several line
   breaks in a row are one boundary. A chunk never spans two paragraphs.
1. Inside a paragraph, a sentence ends right after a terminal mark
   ``。 ！ ？ ! ?`` (runs such as ``！？`` stay together), plus any closing
   brackets that directly follow it (``」 』 ） ) 】 〕 ］ ]``).
2. Leading/trailing whitespace of each sentence is removed and empty sentences
   are dropped.
3. Inside a paragraph, sentences are packed greedily, in order, into chunks of
   at most ``max_chars`` characters, concatenated without any separator.
4. A paragraph that fits in ``max_chars`` is one chunk.
5. A single sentence longer than ``max_chars`` is NOT cut further; it becomes
   its own chunk. (Only 句点-like marks and line breaks are split points.)

The chunks are synthesized separately and their audio is joined back to back
with no inserted silence. The start of each paragraph's first chunk in the
joined audio is that paragraph's start time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from .errors import InputError

DEFAULT_MAX_CHARS = 120

_TERMINALS = "。！？!?"
_CLOSERS = "」』）)】〕］]"
_SENTENCE_RE = re.compile(
    rf"[^{re.escape(_TERMINALS)}\n]*(?:[{re.escape(_TERMINALS)}]+[{re.escape(_CLOSERS)}]*)?"
)


def split_paragraphs(text: str) -> list[str]:
    """Rule 0: non-blank lines, stripped."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _sentences_of_line(line: str) -> list[str]:
    pieces = (m.group(0).strip() for m in _SENTENCE_RE.finditer(line))
    return [p for p in pieces if p]


def split_sentences(text: str) -> list[str]:
    """Split into sentences by rules 0–2 (no packing). Line breaks also end a sentence."""
    return [s for paragraph in split_paragraphs(text) for s in _sentences_of_line(paragraph)]


def _pack(sentences: Sequence[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks


def split_paragraph_chunks(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[list[str]]:
    """Synthesis chunks grouped by paragraph (rules 0–5). Every group is non-empty."""
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    groups = [_pack(_sentences_of_line(p), max_chars) for p in split_paragraphs(text)]
    return [g for g in groups if g]


def split_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Flat list of synthesis chunks (rules 0–5)."""
    return [chunk for group in split_paragraph_chunks(text, max_chars) for chunk in group]


class PronunciationDictionary:
    """Surface form → reading, applied as plain text replacement before synthesis.

    Matching is longest-first in a single pass, so ``見付け`` wins over ``見付``
    and a reading is never re-replaced.

    ``check_terms`` are words that are NOT replaced but are listed by the
    ``kana`` command so a human can confirm the engine already reads them right.
    """

    def __init__(self, entries: Mapping[str, str], check_terms: Sequence[str] = ()) -> None:
        self.entries = dict(entries)
        self.check_terms = [t for t in dict.fromkeys(check_terms) if t not in self.entries]
        keys = sorted(self.entries, key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(k) for k in keys)) if keys else None

    def apply(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self.entries[m.group(0)], text)

    def matches(self, text: str) -> list[str]:
        """Dictionary surfaces that the replacement would actually hit in ``text`` (in order, unique)."""
        if self._pattern is None:
            return []
        return list(dict.fromkeys(m.group(0) for m in self._pattern.finditer(text)))

    @classmethod
    def empty(cls) -> "PronunciationDictionary":
        return cls({})

    @classmethod
    def merge(cls, dictionaries: Sequence["PronunciationDictionary"]) -> "PronunciationDictionary":
        """Several dictionaries as one. A later dictionary wins for the same surface."""
        entries: dict[str, str] = {}
        checks: list[str] = []
        for d in dictionaries:
            entries.update(d.entries)
            checks.extend(d.check_terms)
        return cls(entries, checks)

    @classmethod
    def load(cls, path: str | Path) -> "PronunciationDictionary":
        path = Path(path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as cause:
            raise InputError(f"読み辞書が見つかりません: {path}") from cause
        except UnicodeDecodeError as cause:
            raise InputError(f"読み辞書を UTF-8 として読めません。UTF-8 で保存してください: {path}") from cause
        except yaml.YAMLError as cause:
            raise InputError(f"読み辞書の YAML を解釈できません: {path}: {cause}") from cause
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            raise InputError(f"読み辞書には entries（表記: 読み の対応）が必要です: {path}")
        entries: dict[str, str] = {}
        for surface, reading in data["entries"].items():
            if not isinstance(surface, str) or not surface.strip():
                raise InputError(f"読み辞書の表記が不正です: {surface!r} ({path})")
            if not isinstance(reading, str) or not reading.strip():
                raise InputError(f"読み辞書の読みが不正です: {surface} → {reading!r} ({path})")
            entries[surface.strip()] = reading.strip()

        raw_checks = data.get("check_terms", [])
        if raw_checks is None:
            raw_checks = []
        if not isinstance(raw_checks, list):
            raise InputError(f"読み辞書の check_terms は語のリストにしてください: {path}")
        checks: list[str] = []
        for term in raw_checks:
            if not isinstance(term, str) or not term.strip():
                raise InputError(f"読み辞書の check_terms の語が不正です: {term!r} ({path})")
            checks.append(term.strip())
        return cls(entries, checks)
