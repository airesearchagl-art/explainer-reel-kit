"""``erkit voice review``: 読みの確かめの表。

``erkit voice review <台本> --run <出力フォルダ>``

文ごとに、原稿・字幕・合成入力（辞書の後）・エンジンの読み（AivisSpeech では ``/audio_query`` のカナ）・書き起こし・印を
並べた ``review.tsv`` と、印の付いた文だけを並べた試聴ページ ``listen.html`` を、出力フォルダの ``checks/`` に書く。

- 書き起こしは faster-whisper（任意の依存）があるときだけ。無ければ空欄のまま表を出し、警告する。モデルはこの PC の中で
  読み込み（初回の取得もこの PC）、音声も原稿も外へ送らない。語の時刻（word_timestamps）を ``transcript.json`` に残す
- 書き起こしは確かめる所を絞るためだけに使う（読みの正否はエンジンの読みと試聴で決める）。印:
  - ``ずれ``: 書き起こしが原稿と違う（記号・空白・全角半角を除いて比べる）。モーラと試聴で確かめる
  - ``辞書``: 辞書で読みを直した語がある。書き起こしが合っていても、意図した読みかは聞かないと分からない
  - ``確認語``: 辞書の check_terms（読みを直していないが、エンジンの読みを確かめたい語）がある
- 文の時刻は interactive と同じ（合成の分割の境目と WAV の無音、interactive/sync.py）。試聴ページはその区間を再生する
- 社外秘の台本でも、エンジンへの問い合わせはこの PC の中だけ（CLI が確かめる）。書き起こしもこの PC の中で行う
"""

from __future__ import annotations

import difflib
import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import InputError, OutputError
from .kana import _Reader
from .synth import DURATIONS_FILENAME
from .textproc import PronunciationDictionary, paragraph_sentences, split_paragraphs
from .tts import TTSEngine

TSV_NAME = "review.tsv"
HTML_NAME = "listen.html"
TRANSCRIPT_NAME = "transcript.json"
COLUMNS = ["場面", "文", "段落", "開始秒", "終了秒", "原稿", "字幕", "合成入力", "モーラ", "書き起こし", "印", "辞書・確認語", "ずれ"]

#: 書き起こし（faster-whisper の segments を {start, end, text, words: [{start, end, word, probability}]} にしたもの）
Transcriber = Callable[[Path], list[dict[str, Any]]]


@dataclass
class Row:
    scene: str
    sentence: str
    paragraph: int
    start: float
    end: float
    original: str
    subtitle: str
    prepared: str
    moras: str = ""
    transcript: str = ""
    marks: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    diff: str = ""
    wav: str = ""

    def cells(self) -> list[str]:
        return [self.scene, self.sentence, str(self.paragraph), f"{self.start:.3f}", f"{self.end:.3f}", self.original,
                self.subtitle, self.prepared, self.moras, self.transcript, "・".join(self.marks), "、".join(self.terms),
                self.diff]


# ---------------------------------------------------------------- 書き起こし

def load_transcriber(model: str = "small", *, device: str = "cpu", compute_type: str = "int8") -> Transcriber | None:
    """faster-whisper が入っていれば書き起こしの関数、無ければ None。日本語・語の時刻つき。"""
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        return None
    whisper = WhisperModel(model, device=device, compute_type=compute_type)

    def run(wav: Path) -> list[dict[str, Any]]:
        segments, _ = whisper.transcribe(str(wav), language="ja", word_timestamps=True, beam_size=5)
        out = []
        for seg in segments:
            words = [{"start": round(float(w.start), 3), "end": round(float(w.end), 3), "word": w.word,
                      "probability": round(float(getattr(w, "probability", 0.0)), 3)} for w in (seg.words or [])]
            out.append({"start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "text": seg.text,
                        "words": words})
        return out

    return run


def words_in(segments: list[dict[str, Any]], a: float, b: float) -> list[dict[str, Any]]:
    """区間 [a, b) に真ん中がある語（語の時刻が無い区間は、区間の真ん中で決める）。"""
    out = []
    for seg in segments:
        words = seg.get("words") or [{"start": seg["start"], "end": seg["end"], "word": seg.get("text", "")}]
        for w in words:
            mid = (float(w["start"]) + float(w["end"])) / 2
            if a <= mid < b:
                out.append(w)
    return out


_STRIP = re.compile(r"[\s、。，．,.!?！？「」『』（）()【】・…―〜~:：;；\"'“”‘’]")


def normalize(text: str) -> str:
    """書き起こしと原稿を比べる形（全角半角をそろえ、記号・空白を除き、英字は小文字）。"""
    return _STRIP.sub("", unicodedata.normalize("NFKC", text)).lower()


def diff_text(original: str, transcript: str) -> str:
    """ずれた所だけ（原稿の[…]→書き起こしの[…]）。"""
    a, b = normalize(original), normalize(transcript)
    parts = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            parts.append(f"[{a[i1:i2]}]→[{b[j1:j2]}]")
    return " ".join(parts)


# ---------------------------------------------------------------- 表

def _texts(doc: dict) -> list[tuple[str, str, dict[int, str]]]:
    """(item id, ナレーション, 字幕の別表記 {段落: 文})。順は intro → シーン → outro。"""
    nodes = [("intro", doc.get("intro") or {})] + [(s["id"], s) for s in doc.get("scenes") or []] + \
            [("outro", doc.get("outro") or {})]
    out = []
    for sid, node in nodes:
        subs = {int(x["paragraph"]): str(x["text"]) for x in node.get("subtitles") or []
                if isinstance(x, dict) and "paragraph" in x and "text" in x}
        out.append((sid, str(node.get("narration") or ""), subs))
    return out


def narration_dir_of(run: Path) -> Path:
    """出力フォルダ（その work/narration）か、durations.json のあるフォルダそのもの。"""
    run = Path(run)
    for cand in (run / "work" / "narration", run):
        if (cand / DURATIONS_FILENAME).is_file():
            return cand
    raise InputError(f"{DURATIONS_FILENAME} が見つかりません（erkit make の出力フォルダか、erkit voice synth の出力先を指定する）: {run}")


def build_rows(doc: dict, narration_dir: Path, dictionary: PronunciationDictionary, client: TTSEngine | None,
               *, speaker: int | None, transcriber: Transcriber | None = None,
               log: Callable[[str], None] = lambda m: None) -> tuple[list[Row], dict[str, Any]]:
    """文ごとの行と、書き起こしの記録（transcript.json の中身）。"""
    from ..interactive.sync import item_silences, measure

    durations = json.loads((narration_dir / DURATIONS_FILENAME).read_text(encoding="utf-8"))
    records = {it["id"]: it for it in durations.get("items") or [] if isinstance(it, dict) and "id" in it}
    speaker = speaker if speaker is not None else durations.get("speaker")
    reader = _Reader(client, int(speaker)) if client is not None and speaker is not None else None
    transcripts: dict[str, Any] = {}
    rows: list[Row] = []
    for sid, text, subs in _texts(doc):
        rec = records.get(sid)
        if not text.strip():
            continue
        if rec is None:
            log(f"warning: {sid}: durations.json に記録が無いため、時刻と書き起こしを空にします")
        wav = narration_dir / str((rec or {}).get("wav", f"{sid}.wav"))
        runs = item_silences(wav) if rec is not None and wav.is_file() else []
        m = measure(text, rec or {"audio_sec": 0.0}, wav, runs=runs)
        segments: list[dict[str, Any]] = []
        if transcriber is not None and rec is not None and wav.is_file():
            log(f"[review] 書き起こし {sid}（{wav.name}）")
            segments = transcriber(wav)
            transcripts[sid] = {"wav": wav.name, "segments": segments}
        n = 0
        for i, (para, sents, times) in enumerate(zip(split_paragraphs(text), m["sentences"], m["paragraphs"])):
            alt = subs.get(i + 1)
            alt_sents = paragraph_sentences(alt) if alt else None
            for j, (s, (a, b)) in enumerate(zip(sents, times)):
                n += 1
                sub = alt_sents[j] if alt_sents and len(alt_sents) == len(sents) else (alt or s)
                prepared = dictionary.apply(s)
                row = Row(sid, f"{sid}-{n}", i + 1, a, b, s, sub if alt else "", prepared, wav=wav.name)
                if reader is not None:
                    row.moras = reader(prepared)
                hits = dictionary.matches(s)
                checks = [t for t in dictionary.check_terms if t in s]
                row.terms = [f"{h}→{dictionary.entries[h]}" for h in hits] + checks
                if hits:
                    row.marks.append("辞書")
                if checks:
                    row.marks.append("確認語")
                if transcriber is not None and rec is not None:
                    row.transcript = "".join(w["word"] for w in words_in(segments, a, b)).strip()
                    if normalize(row.transcript) != normalize(s):
                        row.marks.insert(0, "ずれ")
                        row.diff = diff_text(s, row.transcript)
                rows.append(row)
    return rows, {"model": None, "items": transcripts}


def write_tsv(rows: list[Row], path: Path) -> None:
    def cell(v: str) -> str:
        return v.replace("\t", " ").replace("\r", " ").replace("\n", " ")

    lines = ["\t".join(COLUMNS)] + ["\t".join(cell(c) for c in r.cells()) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")   # Excel でそのまま開ける（BOM 付き）


def write_html(rows: list[Row], path: Path, narration_dir: Path, *, transcribed: bool) -> int:
    """印の付いた文だけの試聴ページ。戻り値は載せた文の数。外の URL は読まない。"""
    picked = [r for r in rows if r.marks]
    rel = Path(os.path.relpath(narration_dir, path.parent)).as_posix()
    esc = html.escape
    body = []
    for k, r in enumerate(picked):
        src = f"{rel}/{r.wav}"
        body.append(
            f'<tr><td>{esc(r.sentence)}</td><td class="m">{esc("・".join(r.marks))}</td>'
            f'<td><button data-k="{k}" data-a="{r.start:.3f}" data-b="{r.end:.3f}" data-src="{esc(src)}">▶ 聞く</button>'
            f'<div class="t">{r.start:.2f}–{r.end:.2f}s</div></td>'
            f'<td>{esc(r.original)}<div class="s">合成入力: {esc(r.prepared)}</div>'
            f'<div class="s">モーラ: {esc(r.moras or "（エンジンに問い合わせていない）")}</div></td>'
            f'<td>{esc(r.transcript) if transcribed else "—"}<div class="s">{esc(r.diff)}</div></td>'
            f'<td>{esc("、".join(r.terms))}</td></tr>')
    note = "" if transcribed else '<p class="w">書き起こし無し（faster-whisper が無いか、--no-transcribe）。辞書・確認語の文だけを載せています。</p>'
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>試聴（読みの確かめ）</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:"Noto Sans JP","Yu Gothic UI",sans-serif;margin:16px;color:#222;background:#fff}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;vertical-align:top;font-size:14px}}
th{{background:#f3f3f3}}.m{{font-weight:bold;color:#b00}}.s{{color:#555;font-size:12px;margin-top:4px}}
.t{{color:#777;font-size:12px}}.w{{color:#b00}}button{{white-space:nowrap}}
</style></head><body>
<h1>試聴（読みの確かめ）</h1>
<p>印の付いた文 {len(picked)} / 全 {len(rows)} 文。▶ でその文の区間だけを再生します。書き起こしは確かめる所を絞るためだけのもので、
読みの正否はモーラと試聴で決めます。</p>{note}
<table><tr><th>文</th><th>印</th><th>再生</th><th>原稿・合成入力・モーラ</th><th>書き起こし（ずれ）</th><th>辞書・確認語</th></tr>
{"".join(body)}
</table>
<audio id="p"></audio>
<script>
const p = document.getElementById('p'); let stopAt = null;
p.addEventListener('timeupdate', () => {{ if (stopAt !== null && p.currentTime >= stopAt) {{ p.pause(); stopAt = null; }} }});
document.querySelectorAll('button[data-k]').forEach(b => b.addEventListener('click', () => {{
  const a = parseFloat(b.dataset.a), e = parseFloat(b.dataset.b);
  const go = () => {{ p.currentTime = a; stopAt = e; p.play(); }};
  if (p.getAttribute('src') !== b.dataset.src) {{ p.src = b.dataset.src; p.addEventListener('loadedmetadata', go, {{once: true}}); p.load(); }}
  else go();
}}));
</script>
</body></html>
"""
    path.write_text(page, encoding="utf-8")
    return len(picked)


def run_review(storyboard_doc: dict, run_dir: Path, dictionary: PronunciationDictionary,
               client: TTSEngine | None, *, speaker: int | None = None, out_dir: Path | None = None,
               transcriber: Transcriber | None = None, model: str | None = None,
               log: Callable[[str], None] = print) -> dict[str, Any]:
    narration_dir = narration_dir_of(run_dir)
    out_dir = Path(out_dir) if out_dir else Path(run_dir) / "checks"
    rows, transcript = build_rows(storyboard_doc, narration_dir, dictionary, client, speaker=speaker,
                                  transcriber=transcriber, log=log)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        tsv, page = out_dir / TSV_NAME, out_dir / HTML_NAME
        write_tsv(rows, tsv)
        listed = write_html(rows, page, narration_dir, transcribed=transcriber is not None)
        result = {"tsv": str(tsv), "html": str(page), "sentences": len(rows), "listed": listed,
                  "mismatch": sum(1 for r in rows if "ずれ" in r.marks),
                  "dictionary": sum(1 for r in rows if "辞書" in r.marks),
                  "check_terms": sum(1 for r in rows if "確認語" in r.marks),
                  "transcribed": transcriber is not None, "transcript": None}
        if transcriber is not None:
            transcript["model"] = model
            path = out_dir / TRANSCRIPT_NAME
            path.write_text(json.dumps(transcript, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            result["transcript"] = str(path)
    except OSError as cause:
        raise OutputError(f"確かめの表を書けません: {out_dir}: {cause}") from cause
    return result
