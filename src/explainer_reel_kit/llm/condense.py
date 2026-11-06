"""Condense a long tool description with task ``light`` so the draft call fits its context .

Used only when the draft prompt with the full input does not fit (measured with the server when it
can, ``budget.Measurer``). The steps, each tried only when the previous one is not enough:

1. **stage 1** — split by headings (then paragraphs, lines, characters) into small pieces (about
   ``PIECE_TOKENS`` real tokens each) and condense each to key points, at most about 3 times shorter
   (``MAX_REDUCTION``). Numbers and units, screen item names, menu names, the order of operations and
   the notes / limitations are kept. The answer budget of each call fits its target (×1.5), not a fixed 2048;
2. **stage 2** — if the joined key points still do not fit the draft call, condense them once more;
3. **trim** — still too long: drop lines from the end by code, keeping lines with numbers / units,
   「」 names, menu / dialog / button names;
4. stop (nothing is sent to the draft model) only when even that does not fit.

A piece longer than its target is **not** an error (a warning): only the total has to fit. The draft
model then sees the key points; the check of numbers not found in the input still uses the **full**
original text.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .budget import Budget, estimate_messages, estimate_tokens
from .client import LLMClient
from .structured import Attempt, generate

CONDENSE_SYSTEM = (
    "あなたはツールや業務の説明を、台本作りのために要点へ縮める担当です。書かれた事実だけを使い、"
    "推測や補足を足しません。日本語で書きます。"
)
MIN_TARGET_CHARS = 200
PIECE_TOKENS = 2000  # real tokens per piece (stage 1)
MAX_REDUCTION = 3  # a piece is condensed to at most about 1/3 of its length
ANSWER_FACTOR = 1.5  # the answer budget of a piece: its target × 1.5 (1 character ≤ 1 token, conservative)
MAX_STAGES = 2
_HEADING = re.compile(r"^#{1,6}\s")
# lines that the code keeps when it trims: numbers / units, 「」 names, menus, dialogs, buttons, `code`
_KEEP = re.compile(r"\d|「|」|『|』|`|メニュー|ダイアログ|ボタン|Extensions|Menu|>")


@dataclass
class Piece:
    source: str  # file name
    index: int
    text: str
    stage: int = 1
    target_chars: int = 0
    max_tokens: int = 0
    summary: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    note: str = ""  # over the target / cut off and used as it is

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "source": self.source, "index": self.index, "chars_in": len(self.text),
                "estimated_tokens_in": estimate_tokens(self.text), "target_chars": self.target_chars,
                "max_tokens": self.max_tokens, "chars_out": len(self.summary), "note": self.note,
                "summary": self.summary, "attempts": [a.as_dict() for a in self.attempts]}


def condense_prompt(text: str, *, source: str, target_chars: int, part: str = "") -> str:
    return "\n".join([
        f"次は {source} の説明{part}です。台本のたたき台を作るために、要点だけに縮めてください。",
        "",
        "## 残すもの（省かない）",
        "- 数値と単位（例: 500mm、35%）。書かれたとおりに写す",
        "- 画面の項目名・メニュー名・ボタン名・ダイアログの入力項目（書かれたとおりの名前で）",
        "- 操作の順序（手順は番号付きで）",
        "- 注意書き・制限・前提条件（対応していないこと、動作環境）",
        "",
        "## 書き方",
        f"- 全体で {target_chars} 字以内。見出しごとに「- 」で始まる短い箇条書き",
        "- 説明に書かれていないことは足さない。インストール手順・開発者向けの内容・変更履歴は省いてよい",
        "- 要点の本文だけを出力する（前置きや「以下が要点です」は書かない）",
        "",
        "## 説明",
        text,
    ])


def split_pieces(text: str, max_tokens: int) -> list[str]:
    """Pieces of at most ``max_tokens`` (estimated), split at headings, then paragraphs, lines, characters."""
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if _HEADING.match(line) and current:
            sections.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current))

    def fit(block: str, seps: list[str]) -> list[str]:
        if estimate_tokens(block) <= max_tokens:
            return [block]
        if not seps:  # characters: conservative 1 token per character
            return [block[i:i + max_tokens] for i in range(0, len(block), max_tokens)]
        sep, rest = seps[0], seps[1:]
        out: list[str] = []
        for part in block.split(sep):
            out += fit(part, rest)
        return pack(out, sep)

    def pack(parts: list[str], sep: str) -> list[str]:
        out: list[str] = []
        for part in parts:
            if out and estimate_tokens(out[-1] + sep + part) <= max_tokens:
                out[-1] = out[-1] + sep + part
            else:
                out.append(part)
        return out

    pieces: list[str] = []
    for section in sections:
        pieces += fit(section, ["\n\n", "\n"])
    pieces = pack(pieces, "\n")
    return [p.strip() for p in pieces if p.strip()]


def plain_text(text: str) -> tuple[str | None, list[str]]:
    body = text.strip()
    body = re.sub(r"^```[a-z]*\n|\n```$", "", body).strip()
    return (body or None), ([] if body else ["本文が空です"])


@dataclass
class LightTask:
    model: str
    budget: Budget
    max_tokens: int  # the cap of one answer (task light, 2048)
    thinking: str = "off"


#: texts per source name -> (fits?, prompt tokens, measured?)
FitCheck = Callable[[dict[str, str], str], tuple[bool, int, bool]]


@dataclass
class FitOutcome:
    texts: dict[str, str]
    pieces: list[Piece]
    stages: list[dict[str, Any]]
    warnings: list[str]
    error: str | None = None
    trimmed: dict[str, Any] | None = None


def _overhead() -> int:
    empty = condense_prompt("", source="README.md", target_chars=9999, part="（999/999）")
    return estimate_messages([{"role": "system", "content": CONDENSE_SYSTEM}, {"role": "user", "content": empty}])


def plan_pieces(sources: list[tuple[str, str]], *, light: LightTask, total_target_chars: int, ratio: float,
                stage: int = 1) -> list[Piece]:
    """Small pieces (about PIECE_TOKENS real tokens; ``ratio`` = measured / estimated) with their targets."""
    ratio = min(max(ratio, 0.25), 1.0)
    room = light.budget.room(0) - _overhead()
    piece_est = int(PIECE_TOKENS / ratio)
    pieces: list[Piece] = []
    for name, text in sources:
        # a piece must fit task light with its answer, and 1/3 of it must fit one answer (max_tokens / 1.5)
        max_chars = int(light.max_tokens / ANSWER_FACTOR) * MAX_REDUCTION
        size = piece_est
        for _ in range(8):
            parts = split_pieces(text, size)
            biggest = max(estimate_tokens(p) for p in parts)
            longest = max(len(p) for p in parts)
            if longest <= max_chars and biggest + light.max_tokens <= room:
                break
            size = int(size * 0.8)
        pieces += [Piece(name, i, part, stage) for i, part in enumerate(parts, start=1)]
    total_in = sum(len(p.text) for p in pieces) or 1
    for p in pieces:
        share = int(total_target_chars * len(p.text) / total_in)
        floor = math.ceil(len(p.text) / MAX_REDUCTION)  # never more than about 3 times shorter in one step
        p.target_chars = max(MIN_TARGET_CHARS, share, floor)
        p.target_chars = min(p.target_chars, len(p.text), int(light.max_tokens / ANSWER_FACTOR))
        p.max_tokens = min(light.max_tokens, max(256, math.ceil(p.target_chars * ANSWER_FACTOR)),
                           light.budget.room(0) - _overhead() - estimate_tokens(p.text))
    return pieces


def condense_pieces(client: LLMClient, pieces: list[Piece], *, light: LightTask, retries: int = 1,
                    log: Callable[[str], None] = lambda message: None) -> tuple[list[str], str | None]:
    """Fill ``Piece.summary``. (warnings, error). Over the target is a warning; a cut-off answer is used as it is."""
    warnings: list[str] = []
    counts: dict[str, int] = {}
    for p in pieces:
        counts[p.source] = counts.get(p.source, 0) + 1
    for n, p in enumerate(pieces, start=1):
        part = f"（{p.index}/{counts[p.source]}）" if counts[p.source] > 1 else ""
        label = f"{'もう一度' if p.stage > 1 else ''}要点に縮める（{p.source}{part}）"
        messages = [{"role": "system", "content": CONDENSE_SYSTEM},
                    {"role": "user", "content": condense_prompt(p.text, source=p.source, target_chars=p.target_chars,
                                                                part=part)}]
        log(f"{'要点をもう一度縮めます' if p.stage > 1 else '説明が長いため要点に縮めます'} {n}/{len(pieces)}"
            f"（{light.model}、{p.source}{part}、{len(p.text)} 字 → {p.target_chars} 字以内、出力 {p.max_tokens} トークンまで）…")
        started = time.monotonic()
        result = generate(client, messages, model=light.model, parse=plain_text, retries=retries,
                          max_tokens=p.max_tokens, temperature=0.1, thinking=light.thinking, json_only=False,
                          budget=light.budget, max_tokens_cap=light.max_tokens,
                          length_advice=f"箇条書きを減らし、{p.target_chars} 字以内にしてください（数値・項目名・手順・注意書きは残す）",
                          what=label, log=log)
        p.attempts = result.attempts
        if result.ok:
            p.summary = result.value
        else:
            last = (result.attempts[-1].content if result.attempts else "").strip()
            if not last or result.attempts[-1].error_kind:
                return warnings, f"説明を要点に縮められませんでした（{p.source}{part}、{time.monotonic() - started:.0f} 秒）: {result.error}"
            p.summary, p.note = last, "途中で切れた要点をそのまま使った"
            warnings.append(f"要点（{p.source}{part}）が出力の上限で途中で切れたため、切れたところまでを使いました")
        if len(p.summary) > p.target_chars:
            p.note = (p.note + "、" if p.note else "") + f"目標 {p.target_chars} 字を超えた（{len(p.summary)} 字）"
            warnings.append(f"要点（{p.source}{part}）が {len(p.summary)} 字で、目標 {p.target_chars} 字を超えました"
                            "（全体が台本の呼び出しに収まるため、そのまま使う）")
    return warnings, None


def joined(pieces: list[Piece], names: list[str]) -> dict[str, str]:
    return {name: "\n\n".join(p.summary for p in pieces if p.source == name and p.summary) for name in names}


def trim(texts: dict[str, str], fits: FitCheck) -> tuple[dict[str, str] | None, dict[str, Any]]:
    """Drop lines from the end (keeping numbers, 「」 names, menus …) until the draft call fits. None if it cannot."""
    names = list(texts)
    lines = [(name, line) for name in names for line in texts[name].splitlines()]
    droppable = [i for i, (_, line) in enumerate(lines) if line.strip() and not _KEEP.search(line)]
    record: dict[str, Any] = {"lines": len(lines), "droppable": len(droppable), "dropped": 0, "checks": []}

    def build(drop: set[int]) -> dict[str, str]:
        return {name: "\n".join(line for i, (n, line) in enumerate(lines) if n == name and i not in drop).strip()
                for name in names}

    order = list(reversed(droppable))  # from the end
    for fraction in (0.2, 0.4, 0.6, 0.8, 1.0):
        drop = set(order[:max(1, math.ceil(len(order) * fraction))]) if order else set()
        ok, tokens, measured = fits(build(drop), "機械で短くした要点")
        record["checks"].append({"dropped": len(drop), "tokens": tokens, "measured": measured, "fits": ok})
        if ok:
            record.update(dropped=len(drop), dropped_lines=[lines[i][1] for i in sorted(drop)])
            return build(drop), record
        if not order:
            break
    return None, record


def fit_sources(client: LLMClient, sources: list[tuple[str, str]], *, light: LightTask, total_target_chars: int,
                fits: FitCheck, room: int, ratio: float = 1.0,
                log: Callable[[str], None] = lambda message: None) -> FitOutcome:
    """Stage 1 → (stage 2) → (trim) until ``fits``; error only when even the trimmed key points do not fit.

    ``room``: the tokens the draft prompt may use (context − margin − the draft's max_tokens).
    ``ratio``: measured / estimated tokens of the full input (sizes the pieces in real tokens).
    """
    names = [name for name, _ in sources]
    all_pieces: list[Piece] = []
    stages: list[dict[str, Any]] = []
    warnings: list[str] = []
    current = sources
    texts: dict[str, str] = {}
    for stage in range(1, MAX_STAGES + 1):
        pieces = plan_pieces(current, light=light, total_target_chars=total_target_chars, ratio=ratio, stage=stage)
        stage_warnings, error = condense_pieces(client, pieces, light=light, log=log)
        all_pieces += pieces
        warnings += stage_warnings
        if error:
            stages.append({"stage": stage, "pieces": len(pieces), "error": error})
            return FitOutcome(joined(all_pieces, names), all_pieces, stages, warnings, error)
        texts = joined(pieces, names)
        ok, tokens, measured = fits(texts, f"要点（{stage} 段目）")
        stages.append({"stage": stage, "pieces": len(pieces), "chars": sum(map(len, texts.values())),
                       "draft_prompt_tokens": tokens, "measured": measured, "fits": ok})
        if ok:
            return FitOutcome(texts, all_pieces, stages, warnings)
        current = [(name, texts[name]) for name in names if texts[name]]
        # the next stage aims at what is left: shrink by room / tokens (with 10 % to spare)
        total_target_chars = int(sum(len(t) for t in texts.values()) * min(0.9, room / max(tokens, 1) * 0.9))
    log("要点がまだ長いため、数値・項目名・メニュー名の行を残して、後ろの行から落とします…")
    trimmed, record = trim(texts, fits)
    stages.append({"stage": "trim", **record, "fits": trimmed is not None})
    if trimmed is None:
        return FitOutcome(texts, all_pieces, stages, warnings,
                          "要点に縮め、機械で短くしても台本のたたき台の呼び出しが文脈長に収まらないため、送りませんでした", record)
    warnings.append(f"要点がまだ長いため、機械で {record['dropped']} 行を落としました（数値・「」の項目名・メニュー名の行は残す）"
                    "。落とした行は draft.json の condensed で確かめられる")
    return FitOutcome(trimmed, all_pieces, stages, warnings, None, record)
