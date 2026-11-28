"""Narration input loading and the synth pipeline (input JSON → WAVs + durations.json).

This is the part outside the engine boundary: splitting, the pronunciation dictionary,
joining WAVs, durations.json and the re-generation rules are the same for every engine.
The engine (narration.tts.TTSEngine) only turns one chunk of text into a WAV.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

from importlib import resources

from jsonschema import Draft202012Validator

from .errors import EngineError, InputError, OutputError, OverwriteRefusedError
from .tts import DEFAULT_ENGINE, TTSEngine
from .textproc import DEFAULT_MAX_CHARS, PronunciationDictionary, split_chunk_sentences, split_paragraph_chunks
from .wavutil import WavInfo, concat, engine_wav_info, read_info

DURATIONS_FILENAME = "durations.json"
DURATIONS_FORMAT = "explainer-reel/narration-durations"
# v2: items[].paragraph_starts_sec added; chunks never span paragraphs;
# synth_hash is computed from the synthesized chunks. All v1 fields are unchanged.
# Still v2, fields only added: items[].chunk_frames / chunk_hashes / chunk_sentences (one per synthesis chunk, in
# order), synthesized_paragraphs (paragraphs sent to the engine in this run), reused_from, and fit (narration/fit.py).
# The shape is the same as the durations.json of the system the kit was ported from.
DURATIONS_VERSION = 2

# CON.wav, NUL.wav ... cannot be created on Windows.
_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$", re.IGNORECASE)


@dataclass(frozen=True)
class NarrationItem:
    id: str
    text: str


@dataclass(frozen=True)
class NarrationInput:
    speaker: int
    items: list[NarrationItem]
    engine_url: str | None = None
    engine: str = DEFAULT_ENGINE
    speed: float = 1.0
    volume: float = 1.0
    pre_pause_sec: float = 0.3
    post_pause_sec: float = 0.5


# -- input -----------------------------------------------------------------


def _load_schema(schema_path: str | Path | None) -> dict[str, Any]:
    if schema_path is None:
        text = resources.files("explainer_reel_kit").joinpath("data/schema/narration-input.schema.json").read_text(
            encoding="utf-8")
        return json.loads(text)
    schema_path = Path(schema_path)
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError as cause:
        raise InputError(f"入力スキーマが見つかりません: {schema_path}") from cause


def load_input(path: str | Path, schema_path: str | Path | None = None) -> NarrationInput:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as cause:
        raise InputError(f"入力ファイルが見つかりません: {path}") from cause
    except UnicodeDecodeError as cause:
        raise InputError(f"入力ファイルを UTF-8 として読めません。UTF-8 で保存してください: {path}") from cause
    except json.JSONDecodeError as cause:
        raise InputError(f"入力ファイルが JSON として解釈できません: {path}: {cause}") from cause
    return parse_input(data, schema_path)


def parse_input(data: Any, schema_path: str | Path | None = None) -> NarrationInput:
    schema = _load_schema(schema_path)

    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = []
        for error in errors:
            location = "/".join(str(p) for p in error.path) or "(root)"
            lines.append(f"  - {location}: {error.message}")
        raise InputError("ナレーション入力がスキーマに合いません:\n" + "\n".join(lines))

    reserved = [i["id"] for i in data["items"] if _WINDOWS_RESERVED.match(i["id"])]
    if reserved:
        raise InputError("items[].id に Windows の予約名は使えません: " + ", ".join(reserved))

    seen: dict[str, str] = {}
    duplicates = []
    for item in data["items"]:
        key = item["id"].casefold()  # Windows のファイル名は大文字小文字を区別しない
        if key in seen:
            duplicates.append(f"{seen[key]} / {item['id']}")
        seen[key] = item["id"]
    if duplicates:
        raise InputError("items[].id が重複しています（大文字小文字は区別しない）: " + ", ".join(duplicates))

    return NarrationInput(
        speaker=data["speaker"],
        items=[NarrationItem(id=i["id"], text=i["text"]) for i in data["items"]],
        engine_url=data.get("engine_url"),
        engine=data.get("engine", DEFAULT_ENGINE),
        speed=float(data.get("speed", 1.0)),
        volume=float(data.get("volume", 1.0)),
        pre_pause_sec=float(data.get("pre_pause_sec", 0.3)),
        post_pause_sec=float(data.get("post_pause_sec", 0.5)),
    )


# -- seconds & hashes ------------------------------------------------------


def audio_seconds(duration: Decimal) -> float:
    """audio_sec as recorded: rounded half-up to milliseconds."""
    return float(duration.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def slide_seconds(duration: Decimal, pre_pause_sec: float, post_pause_sec: float) -> float:
    """slide_sec = exact audio duration + pre + post, rounded UP to 0.01 s."""
    total = duration + Decimal(str(pre_pause_sec)) + Decimal(str(post_pause_sec))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def synth_hash(paragraph_chunks: list[list[str]], *, speaker: int, speed: float, volume: float) -> str:
    """Identity of a WAV: the exact chunks sent to the engine (after the dictionary,
    grouped by paragraph) + every setting that changes the audio.

    Pauses are deliberately excluded: they only change slide_sec, not the WAV.
    """
    payload = json.dumps(
        {
            "paragraph_chunks": paragraph_chunks,
            "speaker": speaker,
            "speed": speed,
            "volume": volume,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return sha256_text(payload)


def chunk_hash(chunk: str, *, speaker: int, speed: float, volume: float) -> str:
    """Identity of one synthesis chunk: the text sent to the engine + the same settings as synth_hash.

    Used only to reuse the audio of unchanged chunks when an item is re-synthesized; the WAV of an item is still
    identified by :func:`synth_hash`.
    """
    payload = json.dumps({"chunk": chunk, "speaker": speaker, "speed": speed, "volume": volume},
                         ensure_ascii=False, sort_keys=True)
    return sha256_text(payload)


# -- durations.json --------------------------------------------------------

#: Fields that narration/fit.py replaces for a fixed-length slot; the synthesized values are kept in fit.source.
FIT_SOURCE_FIELDS = ("wav", "audio_sec", "slide_sec", "paragraph_starts_sec")


def synthesized_record(record: dict[str, Any]) -> dict[str, Any]:
    """The record as synthesized (a slot fit of narration/fit.py undone): ``<id>.wav`` and its own times."""
    fit = record.get("fit")
    if not isinstance(fit, dict) or not isinstance(fit.get("source"), dict):
        return record
    out = {k: v for k, v in record.items() if k not in ("fit", "pre_pause_sec")}
    out.update({k: fit["source"][k] for k in FIT_SOURCE_FIELDS if k in fit["source"]})
    return out


def _load_previous(path: Path, log: Callable[[str], None]) -> tuple[dict[str, dict[str, Any]], Any]:
    """Records of the previous run, and the previous format version.

    Records of another format version are not reused: their synth_hash is
    computed differently, so the WAVs cannot be proven identical.
    """
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["items"]
        version = data.get("version")
        records = {rec["id"]: synthesized_record(rec) for rec in items if isinstance(rec, dict) and "id" in rec}
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as cause:
        log(f"warning: 既存の {path.name} を読めないため、過去の記録なしとして扱います: {cause}")
        return {}, None
    if version != DURATIONS_VERSION:
        return {}, version
    return records, version


def _atomic_write(path: Path, data: bytes) -> None:
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as cause:
        raise OutputError(f"出力フォルダに書き込めません: {path.parent}: {cause}") from cause
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException as error:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(error, OSError):
            raise OutputError(
                f"{path} を書き込めません（他のアプリで開いていないか確認してください）: {error}"
            ) from error
        raise


# -- pipeline ----------------------------------------------------------------


@dataclass(frozen=True)
class _ChunkAudio:
    """Where the audio of an unchanged chunk can be cut from (a WAV of a previous run)."""

    wav: Path
    offset: int  # first frame
    frames: int


@dataclass
class _Plan:
    item: NarrationItem
    prepared: str
    paragraphs: list[list[str]]
    text_hash: str
    synth_hash: str
    wav_path: Path
    action: str  # "skip" | "copy" | "generate"
    existing: WavInfo | None = None
    chunk_hashes: list[str] = field(default_factory=list)
    reuse: list[_ChunkAudio | None] = field(default_factory=list)  # per chunk, for "generate"
    copy_from: Path | None = None  # for "copy"
    source_record: dict[str, Any] | None = None  # record the skipped / copied WAV came with


def _existing_wav(path: Path) -> WavInfo | None:
    try:
        return read_info(path)
    except (wave.Error, EOFError, OSError):
        return None


def _chunk_index(records: dict[str, dict[str, Any]], wav_dir: Path, ids: set[str] | None = None) -> dict[str, _ChunkAudio]:
    """chunk hash → audio in a previous WAV. Records without chunk_frames (older runs) or whose WAV no longer
    matches them are ignored. ``ids`` limits the WAVs looked at."""
    index: dict[str, _ChunkAudio] = {}
    for rid, rec in records.items():
        if ids is not None and rid not in ids:
            continue
        frames, hashes = rec.get("chunk_frames"), rec.get("chunk_hashes")
        if not (isinstance(frames, list) and isinstance(hashes, list) and len(frames) == len(hashes) and frames):
            continue
        wav = wav_dir / f"{rid}.wav"
        info = _existing_wav(wav)
        if info is None or info.frames != sum(frames) or rec.get("sample_rate") not in (None, info.sample_rate):
            continue
        offset = 0
        for h, n in zip(hashes, frames):
            index.setdefault(h, _ChunkAudio(wav, offset, int(n)))
            offset += int(n)
    return index


def _cut(audio: _ChunkAudio) -> bytes:
    """The frames of one chunk as a WAV of its own (same format as the WAV it is cut from)."""
    with wave.open(str(audio.wav), "rb") as reader:
        params = reader.getparams()
        reader.setpos(audio.offset)
        data = reader.readframes(audio.frames)
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(params.nchannels)
        writer.setsampwidth(params.sampwidth)
        writer.setframerate(params.framerate)
        writer.writeframes(data)
    return out.getvalue()


def run_synth(
    narration: NarrationInput,
    out_dir: str | Path,
    engine: TTSEngine,
    *,
    dictionary: PronunciationDictionary | None = None,
    force: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    reuse_from: str | Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Generate ``<id>.wav`` for each item and write ``durations.json``.

    - An existing WAV whose recorded synth_hash matches is reused (not re-synthesized).
    - An existing WAV that would change is never overwritten unless ``force``;
      in that case nothing is generated and OverwriteRefusedError is raised.
    - ``reuse_from``: the narration folder of a previous run (read only; the folder with its durations.json).
      A WAV recorded there with the same synth_hash is copied instead of synthesized.
    - When an item has to be made again, only its changed chunks are sent to the engine: the audio of a chunk
      whose chunk_hash is unchanged is cut from the previous WAV of the same item (in ``out_dir``, read before it
      is overwritten) or from any WAV of ``reuse_from``. The records say which paragraphs were synthesized.
    - durations.json is rewritten after every generated item, so an interrupted
      run still leaves records that let the next run skip finished items.
    """
    dictionary = dictionary or PronunciationDictionary.empty()
    out_dir = Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as cause:
        raise OutputError(f"出力フォルダを作成できません: {out_dir}: {cause}") from cause
    durations_path = out_dir / DURATIONS_FILENAME
    previous, previous_version = _load_previous(durations_path, log)

    source_dir: Path | None = Path(reuse_from) if reuse_from else None
    source: dict[str, dict[str, Any]] = {}
    if source_dir is not None:
        if source_dir.resolve() == out_dir.resolve():
            source_dir = None  # the same folder: its records are already "previous"
        elif not (source_dir / DURATIONS_FILENAME).is_file():
            raise InputError(f"使い回す WAV の記録（{DURATIONS_FILENAME}）がありません: {source_dir}")
        else:
            source, source_version = _load_previous(source_dir / DURATIONS_FILENAME, log)
            if not source and source_version not in (None, DURATIONS_VERSION):
                log(f"note: {source_dir / DURATIONS_FILENAME} は旧形式（version {source_version}）のため使い回しません")
    source_index = _chunk_index(source, source_dir) if source_dir is not None else {}

    settings = {"speaker": narration.speaker, "speed": narration.speed, "volume": narration.volume}
    plans: list[_Plan] = []
    conflicts: list[str] = []
    for item in narration.items:
        prepared = dictionary.apply(item.text)
        paragraphs = split_paragraph_chunks(prepared, max_chars)
        digest = synth_hash(paragraphs, **settings)
        wav_path = out_dir / f"{item.id}.wav"
        plan = _Plan(
            item=item,
            prepared=prepared,
            paragraphs=paragraphs,
            text_hash=sha256_text(item.text),
            synth_hash=digest,
            wav_path=wav_path,
            action="generate",
            chunk_hashes=[chunk_hash(c, **settings) for group in paragraphs for c in group],
        )
        record = previous.get(item.id)
        if wav_path.exists():
            existing = _existing_wav(wav_path)
            if (
                existing is not None
                and record is not None
                and record.get("synth_hash") == digest
                and isinstance(record.get("paragraph_starts_sec"), list)
            ):
                plan.action = "skip"
                plan.existing = existing
                plan.source_record = record
            elif not force:
                conflicts.append(item.id)
        if plan.action == "generate" and source_dir is not None:
            rec = source.get(item.id)
            info = _existing_wav(source_dir / f"{item.id}.wav")
            if (rec is not None and info is not None and rec.get("synth_hash") == digest
                    and isinstance(rec.get("paragraph_starts_sec"), list)):
                plan.action, plan.copy_from, plan.existing, plan.source_record = (
                    "copy", source_dir / f"{item.id}.wav", info, rec)
        plans.append(plan)

    if conflicts:
        if previous_version is not None and previous_version != DURATIONS_VERSION:
            log(
                f"note: 既存の {DURATIONS_FILENAME} は旧形式（version {previous_version}）のため、"
                f"既存 WAV が同じ内容か判定できません。作り直すには --force を付けてください。"
            )
        raise OverwriteRefusedError(conflicts)

    for plan in plans:  # which chunks can be cut from a previous WAV (the item's own first, then reuse_from)
        if plan.action != "generate":
            continue
        own = _chunk_index(previous, out_dir, {plan.item.id})
        plan.reuse = [own.get(h) or source_index.get(h) for h in plan.chunk_hashes]

    if any(p.action == "generate" and not all(p.reuse) for p in plans):
        voices = engine.voices()
        if narration.speaker not in {voice.style_id for voice in voices}:
            listed = "\n".join(f"  {v.style_id}  {v.label}" for v in voices) or "  （声がありません）"
            raise InputError(
                f"声（style id）{narration.speaker} がエンジンにありません。"
                " 声を入れるか、`erkit voice list` の一覧から選んで --speaker か config/kit.yaml の voice.speaker で指定してください。\n"
                f"エンジンにある声:\n{listed}"
            )

    engine_url = engine.url
    records: dict[str, dict[str, Any]] = {
        p.item.id: previous[p.item.id] for p in plans if p.item.id in previous
    }

    def document(complete: bool) -> dict[str, Any]:
        order = [p.item.id for p in plans]
        return {
            "format": DURATIONS_FORMAT,
            "version": DURATIONS_VERSION,
            "complete": complete,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine": engine.name,
            "engine_url": engine_url,
            "speaker": narration.speaker,
            "speed": narration.speed,
            "volume": narration.volume,
            "pre_pause_sec": narration.pre_pause_sec,
            "post_pause_sec": narration.post_pause_sec,
            "max_chars": max_chars,
            "items": [records[i] for i in order if i in records],
        }

    def write_document(complete: bool) -> dict[str, Any]:
        doc = document(complete)
        payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(durations_path, payload.encode("utf-8"))
        return doc

    def make_record(plan: _Plan, info: WavInfo, paragraph_starts_sec: list[float],
                    chunk_frames: list[int] | None, synthesized: list[int],
                    reused_from: Path | None = None) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "id": plan.item.id,
            "wav": plan.wav_path.name,
            "audio_sec": audio_seconds(info.duration),
            "slide_sec": slide_seconds(info.duration, narration.pre_pause_sec, narration.post_pause_sec),
            "chunks": sum(len(group) for group in plan.paragraphs),
            "sample_rate": info.sample_rate,
            "channels": info.channels,
            "text_hash": plan.text_hash,
            "synth_hash": plan.synth_hash,
            "paragraph_starts_sec": paragraph_starts_sec,
        }
        if chunk_frames is not None and len(chunk_frames) == len(plan.chunk_hashes):
            rec["chunk_frames"] = chunk_frames
            rec["chunk_hashes"] = plan.chunk_hashes
        # sentences of each chunk (to time sentences and subtitles from the WAV)
        rec["chunk_sentences"] = [len(c) for group in split_chunk_sentences(plan.prepared, max_chars) for c in group]
        rec["synthesized_paragraphs"] = synthesized
        if reused_from is not None:
            rec["reused_from"] = str(reused_from)
        return rec

    def summary(rec: dict[str, Any]) -> str:
        starts = ", ".join(f"{s:g}" for s in rec["paragraph_starts_sec"])
        return (
            f"audio {rec['audio_sec']}s, slide {rec['slide_sec']}s, "
            f"段落 {len(rec['paragraph_starts_sec'])} (開始 {starts}s)"
        )

    def known_frames(plan: _Plan, rec: dict[str, Any] | None) -> list[int] | None:
        frames = (rec or {}).get("chunk_frames")
        hashes = (rec or {}).get("chunk_hashes")
        return frames if isinstance(frames, list) and hashes == plan.chunk_hashes else None

    for plan in plans:
        if plan.action == "skip":
            assert plan.existing is not None and plan.source_record is not None
            rec = plan.source_record
            records[plan.item.id] = make_record(plan, plan.existing, rec["paragraph_starts_sec"],
                                                known_frames(plan, rec), [],
                                                Path(rec["reused_from"]) if rec.get("reused_from") else None)
            log(f"skip      {plan.item.id}: 同一内容の WAV を再利用 ({summary(records[plan.item.id])})")
            continue
        if plan.action == "copy":
            assert plan.copy_from is not None and plan.existing is not None and plan.source_record is not None
            _atomic_write(plan.wav_path, plan.copy_from.read_bytes())
            rec = plan.source_record
            records[plan.item.id] = make_record(plan, plan.existing, rec["paragraph_starts_sec"],
                                                known_frames(plan, rec), [], plan.copy_from.parent)
            write_document(complete=False)
            log(f"reuse     {plan.item.id}: 前の WAV を写して再利用 ({summary(records[plan.item.id])})")
            continue
        _generate(plan, engine, narration, records, make_record, write_document, summary, log)

    return write_document(complete=True)


def _generate(plan: _Plan, engine: TTSEngine, narration: NarrationInput, records: dict[str, dict[str, Any]],
              make_record: Callable[..., dict[str, Any]], write_document: Callable[[bool], Any],
              summary: Callable[[dict[str, Any]], str], log: Callable[[str], None]) -> None:
    """Make the WAV of one item: unchanged chunks are cut from a previous WAV, the others are synthesized."""
    # cut every reusable chunk BEFORE the item's own WAV is overwritten
    pieces: list[bytes | None] = [_cut(a) if a is not None else None for a in plan.reuse]
    chunk_texts = [(p_index, chunk) for p_index, group in enumerate(plan.paragraphs) for chunk in group]

    def fill(pieces: list[bytes | None]) -> list[bytes]:
        return [piece if piece is not None else
                engine.synthesize(chunk, narration.speaker, speed=narration.speed, volume=narration.volume)
                for piece, (_, chunk) in zip(pieces, chunk_texts)]

    synthesized_idx = [k for k, piece in enumerate(pieces) if piece is None]
    parts = fill(pieces)
    try:
        audio = concat(parts)
    except EngineError:
        if len(synthesized_idx) == len(pieces):  # nothing was reused: the engine's output itself does not match
            raise
        # a reused chunk has another format than the engine's output now: synthesize the whole item
        log(f"note: {plan.item.id}: 使い回す音声と新しく合成した音声の形式が違うため、全体を合成し直します")
        synthesized_idx = list(range(len(pieces)))
        parts = fill([None] * len(pieces))
        audio = concat(parts)
    frames = [engine_wav_info(part).frames for part in parts]
    info = engine_wav_info(audio)
    assert info.frames == sum(frames), "concat must not add or drop frames"
    starts_frames, k = [], 0
    for group in plan.paragraphs:
        starts_frames.append(sum(frames[:k]))
        k += len(group)
    paragraph_starts = [audio_seconds(Decimal(f) / Decimal(info.sample_rate)) for f in starts_frames]
    synthesized_paragraphs = sorted({chunk_texts[k][0] + 1 for k in synthesized_idx})
    reused = len(parts) - len(synthesized_idx)
    sources = {a.wav.parent for a in plan.reuse if a is not None} if reused else set()
    _atomic_write(plan.wav_path, audio)
    records[plan.item.id] = make_record(plan, info, paragraph_starts, frames, synthesized_paragraphs,
                                        next(iter(sources)) if len(sources) == 1 else None)
    write_document(False)
    detail = (f"合成 {len(synthesized_idx)}・使い回し {reused}、合成した段落 "
              f"{', '.join(map(str, synthesized_paragraphs)) or 'なし'}") if reused else f"{len(parts)} 分割"
    log(f"generated {plan.item.id}: {detail}, {summary(records[plan.item.id])}")


def resolve_engine_url(cli_url: str | None, narration: NarrationInput) -> str | None:
    """--engine-url ＞ 入力の engine_url ＞ None（エンジンの既定）。"""
    return cli_url or narration.engine_url
