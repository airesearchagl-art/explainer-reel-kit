"""合成の分割ごとの使い回し（synth）・固定尺の枠（fit）・読みの確かめの表（review）。"""
from __future__ import annotations

import io
import json
import math
import struct
import wave
from pathlib import Path

import pytest

from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.narration import cli, review
from explainer_reel_kit.narration.adapter import storyboard_to_narration_input
from explainer_reel_kit.narration.errors import InputError, OverwriteRefusedError
from explainer_reel_kit.narration.fit import SlotOverflowError, fit_slots, map_sec, plan_fit, slot_seconds
from explainer_reel_kit.narration.review import diff_text, normalize, run_review
from explainer_reel_kit.narration.synth import chunk_hash, parse_input, run_synth, synthesized_record
from explainer_reel_kit.narration.textproc import PronunciationDictionary, split_chunk_sentences, split_paragraph_chunks
from explainer_reel_kit.narration.tts.aivisspeech import AivisSpeechEngine, HttpResponse

ROOT = Path(__file__).resolve().parents[2]
A3 = ROOT / "tests" / "fixtures" / "readings" / "a3-paper.storyboard.md"
SPEAKER = 888753760


def tone(seconds: float, rate: int = 24000) -> bytes:
    n = round(seconds * rate)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n))


def wav_bytes(pcm: bytes, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def silence(seconds: float, rate: int = 24000) -> bytes:
    return b"\x00\x00" * round(seconds * rate)


def _client(engine) -> AivisSpeechEngine:
    return AivisSpeechEngine("http://127.0.0.1:10101/", transport=engine)


def _input(items):
    return parse_input({"speaker": SPEAKER, "items": items})


def _tone_engine(engine):
    """偽エンジンの /synthesis を、無音ではない音（文字数で長さが決まる）に替える。"""
    def synth(call):
        q = json.loads(call.body.decode("utf-8"))
        return HttpResponse(200, wav_bytes(silence(0.05) + tone(len(q["kana"]) * 0.01) + silence(0.05)), "audio/wav")
    engine.overrides["/synthesis"] = synth
    return engine


def run(narration, out_dir, engine, **kw):
    kw.setdefault("log", lambda m: None)
    return run_synth(narration, out_dir, _client(engine), **kw)


# ---------------------------------------------------------------- textproc

def test_chunk_sentences_join_to_the_same_chunks():
    text = "一つ目の文です。二つ目の文です。\n三つ目。" + "長い文です。" * 30
    assert [["".join(c) for c in g] for g in split_chunk_sentences(text, 40)] == split_paragraph_chunks(text, 40)


# ---------------------------------------------------------------- synth: 変わった分割だけ合成する

def test_durations_record_the_chunks(tmp_path, engine):
    _tone_engine(engine)
    doc = run(_input([{"id": "s1", "text": "一つ目です。二つ目です。\n三つ目です。"}]), tmp_path, engine, max_chars=8)
    rec = doc["items"][0]
    assert doc["version"] == 2
    assert rec["chunk_sentences"] == [1, 1, 1] and rec["synthesized_paragraphs"] == [1, 2]
    assert len(rec["chunk_frames"]) == len(rec["chunk_hashes"]) == rec["chunks"] == 3
    with wave.open(str(tmp_path / "s1.wav")) as w:
        assert sum(rec["chunk_frames"]) == w.getnframes()
    assert rec["paragraph_starts_sec"][1] == round(sum(rec["chunk_frames"][:2]) / rec["sample_rate"], 3)
    assert "reused_from" not in rec


def test_only_changed_paragraph_is_resynthesized_in_place(tmp_path, engine):
    _tone_engine(engine)
    item = {"id": "s1", "text": "まず設定を開きます。\nここではA3用紙を選びます。"}
    first = run(_input([item]), tmp_path, engine, dictionary=PronunciationDictionary({"A3用紙": "エースリーヨウシ"}))
    rec1 = first["items"][0]
    assert rec1["synthesized_paragraphs"] == [1, 2] and len(rec1["chunk_frames"]) == 2 and rec1["chunk_sentences"] == [1, 1]
    old = (tmp_path / "s1.wav").read_bytes()
    engine.calls.clear()
    fixed = PronunciationDictionary({"A3用紙": "エーサンヨウシ"})
    with pytest.raises(OverwriteRefusedError):  # 変わる WAV は --force なしでは上書きしない（今までどおり）
        run(_input([item]), tmp_path, engine, dictionary=fixed)
    second = run(_input([item]), tmp_path, engine, dictionary=fixed, force=True)
    rec2 = second["items"][0]
    assert engine.synthesized_texts() == ["ここではエーサンヨウシを選びます。"]
    assert rec2["synthesized_paragraphs"] == [2] and rec2["synth_hash"] != rec1["synth_hash"]
    assert rec2["chunk_hashes"][0] == rec1["chunk_hashes"][0] and rec2["chunk_frames"][0] == rec1["chunk_frames"][0]
    n0 = rec1["chunk_frames"][0]
    with wave.open(io.BytesIO(old)) as a, wave.open(str(tmp_path / "s1.wav")) as b:
        assert a.readframes(n0) == b.readframes(n0)  # 1 段落目の音声は前と同じ


def test_same_content_is_skipped_without_engine_calls(tmp_path, engine):
    _tone_engine(engine)
    items = [{"id": "a", "text": "一つ目。"}]
    run(_input(items), tmp_path, engine)
    engine.calls.clear()
    doc = run(_input(items), tmp_path, engine)
    assert engine.paths() == []  # 声の一覧も聞かない
    assert doc["items"][0]["synthesized_paragraphs"] == [] and "chunk_frames" in doc["items"][0]


def test_reuse_from_copies_same_wavs_and_cuts_changed_items(tmp_path, engine):
    _tone_engine(engine)
    items = [{"id": "a", "text": "変わらない段落です。"}, {"id": "b", "text": "一つ目。\nA3用紙を選びます。"}]
    run(_input(items), tmp_path / "run1", engine, dictionary=PronunciationDictionary({"A3用紙": "エースリーヨウシ"}))
    before = {p.name: p.read_bytes() for p in (tmp_path / "run1").iterdir()}
    engine.calls.clear()
    doc = run(_input(items), tmp_path / "run2", engine, dictionary=PronunciationDictionary({"A3用紙": "エーサンヨウシ"}),
              reuse_from=tmp_path / "run1")
    recs = {r["id"]: r for r in doc["items"]}
    assert engine.synthesized_texts() == ["エーサンヨウシを選びます。"]
    assert recs["a"]["synthesized_paragraphs"] == [] and recs["a"]["reused_from"] == str(tmp_path / "run1")
    assert (tmp_path / "run2" / "a.wav").read_bytes() == (tmp_path / "run1" / "a.wav").read_bytes()
    assert recs["b"]["synthesized_paragraphs"] == [2] and recs["b"]["reused_from"] == str(tmp_path / "run1")
    assert {p.name: p.read_bytes() for p in (tmp_path / "run1").iterdir()} == before  # 前の実行のフォルダは変えない


def test_reuse_from_needs_durations(tmp_path, engine):
    (tmp_path / "empty").mkdir()
    with pytest.raises(InputError, match="durations.json"):
        run(_input([{"id": "a", "text": "一つ目。"}]), tmp_path / "out", engine, reuse_from=tmp_path / "empty")


def test_reuse_from_the_same_folder_is_the_previous_run(tmp_path, engine):
    _tone_engine(engine)
    items = [{"id": "a", "text": "一つ目。"}]
    run(_input(items), tmp_path, engine)
    engine.calls.clear()
    doc = run(_input(items), tmp_path, engine, reuse_from=tmp_path)
    assert engine.synthesized_texts() == [] and "reused_from" not in doc["items"][0]


def test_subtitle_only_change_does_not_touch_synthesis(tmp_path, engine):
    """字幕の別表記はナレーションの入力に入らない: 同じ入力なら synth_hash も同じで、合成しない。"""
    base = A3.read_text(encoding="utf-8")
    with_sub = base.replace("ここではA3用紙を選びます。\n",
                            "ここではA3用紙を選びます。\n<!-- subtitle: ここでは A3 の用紙を選びます。 -->\n")
    doc_b = sb.markdown_to_storyboard(with_sub)
    assert doc_b["scenes"][0]["subtitles"] == [{"paragraph": 2, "text": "ここでは A3 の用紙を選びます。"}]
    a = storyboard_to_narration_input(sb.markdown_to_storyboard(base), default_speaker=SPEAKER)
    b = storyboard_to_narration_input(doc_b, default_speaker=SPEAKER)
    assert a == b and "subtitle" not in json.dumps(b, ensure_ascii=False)
    _tone_engine(engine)
    run(parse_input(a), tmp_path, engine)
    engine.calls.clear()
    doc = run(parse_input(b), tmp_path, engine)
    assert engine.synthesized_texts() == [] and all(r["synthesized_paragraphs"] == [] for r in doc["items"])


def test_old_records_without_chunk_frames_resynthesize_the_item(tmp_path, engine):
    _tone_engine(engine)
    item = {"id": "s1", "text": "一つ目。\n二つ目のA3用紙。"}
    run(_input([item]), tmp_path, engine)
    path = tmp_path / "durations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for r in data["items"]:
        r.pop("chunk_frames")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    engine.calls.clear()
    run(_input([item]), tmp_path, engine, dictionary=PronunciationDictionary({"A3用紙": "エーサンヨウシ"}), force=True)
    assert len(engine.synthesized_texts()) == 2  # どの段落が同じか分からないので全体を合成


def test_reused_audio_in_another_format_falls_back_to_full_synthesis(tmp_path, engine):
    _tone_engine(engine)
    item = {"id": "s1", "text": "一つ目。\nA3用紙。"}
    run(_input([item]), tmp_path, engine)
    engine.calls.clear()

    def synth_44k(call):  # エンジンの出力の形式が前と違う（24 kHz → 44.1 kHz）
        q = json.loads(call.body.decode("utf-8"))
        return HttpResponse(200, wav_bytes(tone(len(q["kana"]) * 0.01, 44100), 44100), "audio/wav")
    engine.overrides["/synthesis"] = synth_44k
    doc = run(_input([item]), tmp_path, engine, dictionary=PronunciationDictionary({"A3用紙": "エーサンヨウシ"}),
              force=True)
    assert len(engine.synthesized_texts()) == 3  # 変わった 1 つ ＋ 形式が合わないので全体（2 つ）
    assert doc["items"][0]["synthesized_paragraphs"] == [1, 2] and doc["items"][0]["sample_rate"] == 44100


def test_reuse_works_with_any_tts_engine(tmp_path, fake_tts):
    """エンジンの口（TTSEngine）の外の共通部分なので、AivisSpeech 以外のエンジンでも同じ。"""
    voice = fake_tts.voices_[0].style_id
    items = [{"id": "a", "text": "一つ目。\n二つ目。"}]
    run_synth(parse_input({"speaker": voice, "items": items}), tmp_path, fake_tts, log=lambda m: None)
    fake_tts.spoken.clear()
    changed = [{"id": "a", "text": "一つ目。\n二つ目を直した。"}]
    doc = run_synth(parse_input({"speaker": voice, "items": changed}), tmp_path, fake_tts, force=True, log=lambda m: None)
    assert [s[0] for s in fake_tts.spoken] == ["二つ目を直した。"]
    assert doc["items"][0]["synthesized_paragraphs"] == [2]


def test_chunk_hash_uses_the_same_settings_as_synth_hash():
    h = chunk_hash("あ。", speaker=1, speed=1.0, volume=1.0)
    assert h != chunk_hash("あ。", speaker=1, speed=1.1, volume=1.0) != chunk_hash("あ。", speaker=2, speed=1.0, volume=1.0)


def test_cli_synth_reuse_from(tmp_path, engine, capsys):
    _tone_engine(engine)
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"speaker": SPEAKER, "items": [{"id": "a", "text": "一つ目。"}]}, ensure_ascii=False),
                   encoding="utf-8")
    url = ["--engine-url", "http://127.0.0.1:10101"]
    assert cli.main(["synth", str(inp), "--out-dir", str(tmp_path / "run1"), *url], transport=engine) == 0
    engine.calls.clear()
    assert cli.main(["synth", str(inp), "--out-dir", str(tmp_path / "run2"), "--reuse-from", str(tmp_path / "run1"), *url],
                    transport=engine) == 0
    assert engine.synthesized_texts() == []
    assert cli.main(["synth", str(inp), "--out-dir", str(tmp_path / "run3"), "--reuse-from", str(tmp_path / "nothing"),
                     *url], transport=engine) == 2
    assert "--reuse-from" in capsys.readouterr().err


# ---------------------------------------------------------------- fit: 固定尺の枠

def _gap_wav(tmp_path: Path, name: str = "x.wav") -> Path:
    """頭 0.2 秒・音 1 秒・無音 0.6 秒・音 1 秒・終わり 0.2 秒（全体 3.0 秒）。"""
    p = tmp_path / name
    p.write_bytes(wav_bytes(silence(0.2) + tone(1.0) + silence(0.6) + tone(1.0) + silence(0.2)))
    return p


def test_fit_leaves_short_narration_alone(tmp_path):
    plan = plan_fit({"id": "x"}, _gap_wav(tmp_path), 5.0, pre_pause_sec=0.3, post_pause_sec=0.5)
    assert not plan.squeezed and plan.post_sec == pytest.approx(5.0 - 0.3 - 3.0)


def test_fit_squeezes_edges_and_post_first(tmp_path):
    wav = _gap_wav(tmp_path)
    plan = plan_fit({"id": "x"}, wav, 3.6, pre_pause_sec=0.3, post_pause_sec=0.5)  # 3.8 秒 → 0.2 秒詰める
    assert plan.squeezed and plan.removed_sec + (0.5 - plan.post_sec) == pytest.approx(0.2, abs=0.002)
    assert all(a == 0 or a + k == 3.0 * 24000 for a, k in plan.cuts)  # 文の間（0.6 秒）は触らない


def test_fit_then_squeezes_gaps_between_sentences(tmp_path):
    wav = _gap_wav(tmp_path)
    # 余白と頭・終わりで詰められるのは 0.4 + 0.15 × 2 = 0.7 秒。3.8 → 2.9 は 0.9 秒なので、文の間から 0.2 秒
    plan = plan_fit({"id": "x"}, wav, 2.9, pre_pause_sec=0.3, post_pause_sec=0.5)
    inner = [(a, k) for a, k in plan.cuts if 0 < a and a + k < 3.0 * 24000]
    assert len(inner) == 1 and inner[0][1] / 24000 == pytest.approx(0.2, abs=0.002)
    assert 0.3 + (3.0 - plan.removed_sec) + plan.post_sec == pytest.approx(2.9, abs=1e-6)


def test_fit_overflow_reports_seconds_and_choices(tmp_path):
    wav = _gap_wav(tmp_path)
    with pytest.raises(SlotOverflowError) as e:
        plan_fit({"id": "x"}, wav, 2.5, pre_pause_sec=0.3, post_pause_sec=0.5, speed=1.0)
    o = e.value.overflows[0]
    # 詰められるだけ詰めて 3.8 − 0.7 − 0.4（文の間 0.6 → 0.2）= 2.7 秒 → 0.2 秒超える
    assert o.min_sec == pytest.approx(2.7, abs=0.002) and o.over_sec == pytest.approx(0.2, abs=0.002)
    assert "0.20 秒超えます" in str(e.value) and "2.70 以上" in str(e.value) and "目安 1.12 以上" in str(e.value)


def test_map_sec_and_synthesized_record_undo_the_fit():
    cuts = [[0.0, 0.1], [1.5, 1.7]]
    assert map_sec(0.05, cuts) == 0.0 and map_sec(1.0, cuts) == pytest.approx(0.9) and map_sec(2.0, cuts) == pytest.approx(1.7)
    rec = {"id": "x", "wav": "x.fit.wav", "audio_sec": 1.0, "slide_sec": 2.0, "paragraph_starts_sec": [0.0],
           "synth_hash": "h", "fit": {"source": {"wav": "x.wav", "audio_sec": 1.3, "slide_sec": 2.1,
                                                 "paragraph_starts_sec": [0.0]}}}
    assert synthesized_record(rec) == {"id": "x", "wav": "x.wav", "audio_sec": 1.3, "slide_sec": 2.1,
                                       "paragraph_starts_sec": [0.0], "synth_hash": "h"}


def test_fit_slots_rewrites_durations_and_synth_still_skips(tmp_path, engine):
    _tone_engine(engine)
    items = [{"id": "a", "text": "一つ目の文です。\n二つ目の文です。"}, {"id": "b", "text": "短い。"}]
    doc = run(_input(items), tmp_path, engine)
    rec_a = doc["items"][0]
    tight = rec_a["audio_sec"] + 0.3 + 0.2  # 後ろの余白 0.5 → 0.2 まで詰めれば入る
    report = fit_slots(tmp_path, {"a": tight, "b": 3.0}, log=lambda m: None)
    data = json.loads((tmp_path / "durations.json").read_text(encoding="utf-8"))
    a, b = data["items"]
    assert a["slide_sec"] == pytest.approx(math.ceil(tight * 100) / 100) and b["slide_sec"] == 3.0
    assert a["fit"]["source"]["wav"] == "a.wav" and report["b"]["removed_sec"] == 0.0
    assert b["wav"] == "b.wav" and "cuts" not in b["fit"]
    # 詰めた後も、同じ内容なら合成しない（fit.source に戻して比べる）
    engine.calls.clear()
    again = run(_input(items), tmp_path, engine)
    assert engine.synthesized_texts() == [] and again["items"][0]["wav"] == "a.wav"


def test_fit_slots_overflow_leaves_durations_unchanged(tmp_path, engine):
    _tone_engine(engine)
    run(_input([{"id": "a", "text": "長めの文を一つ読みます。"}]), tmp_path, engine)
    before = (tmp_path / "durations.json").read_text(encoding="utf-8")
    with pytest.raises(SlotOverflowError, match="a: 枠 0.10 秒"):
        fit_slots(tmp_path, {"a": 0.1}, log=lambda m: None)
    assert (tmp_path / "durations.json").read_text(encoding="utf-8") == before


def test_slot_seconds_from_the_storyboard():
    doc = sb.markdown_to_storyboard(A3.read_text(encoding="utf-8"))
    assert slot_seconds(doc) == {}
    doc["scenes"][1]["slot_sec"] = 6
    doc["intro"]["slot_sec"] = 4.5
    assert slot_seconds(doc) == {"intro": 4.5, "s02": 6.0}


# ---------------------------------------------------------------- review: 読みの確かめの表

def _review_run(tmp_path, engine):
    doc = sb.markdown_to_storyboard(A3.read_text(encoding="utf-8"))
    narr = tmp_path / "run" / "work" / "narration"
    dictionary = PronunciationDictionary({"A3用紙": "エーサンヨウシ"}, check_terms=["図面"])
    _tone_engine(engine)
    data = storyboard_to_narration_input(doc, default_speaker=SPEAKER)
    run(parse_input(data), narr, engine, dictionary=dictionary)
    return doc, dictionary


def test_review_without_transcription_still_writes_the_table(tmp_path, engine):
    doc, dictionary = _review_run(tmp_path, engine)
    res = run_review(doc, tmp_path / "run", dictionary, _client(engine), log=lambda m: None)
    assert res["transcribed"] is False and res["transcript"] is None
    rows = Path(res["tsv"]).read_text(encoding="utf-8-sig").splitlines()
    head = rows[0].split("\t")
    assert head[:6] == ["場面", "文", "段落", "開始秒", "終了秒", "原稿"] and "書き起こし" in head and "モーラ" in head
    a3 = next(r.split("\t") for r in rows[1:] if "ここではA3用紙" in r)
    assert a3[head.index("合成入力")] == "ここではエーサンヨウシを選びます。"
    assert "エーサンヨウシ" in a3[head.index("モーラ")]  # 偽エンジンは読みに合成入力を返す
    assert a3[head.index("書き起こし")] == "" and a3[head.index("印")] == "辞書"
    page = Path(res["html"]).read_text(encoding="utf-8")
    assert "書き起こし無し" in page and "ここではA3用紙を選びます。" in page and "../work/narration/s01.wav" in page
    assert "http" not in page.replace("http-equiv", "")  # 外の URL を読まない
    assert res["dictionary"] == 3 and res["check_terms"] >= 1


def test_review_shows_the_subtitle_alternative(tmp_path, engine):
    _, dictionary = _review_run(tmp_path, engine)
    doc = sb.markdown_to_storyboard(A3.read_text(encoding="utf-8").replace(
        "ここではA3用紙を選びます。\n", "ここではA3用紙を選びます。\n<!-- subtitle: ここでは A3 の用紙を選びます。 -->\n"))
    res = run_review(doc, tmp_path / "run", dictionary, None, log=lambda m: None)
    rows = [r.split("\t") for r in Path(res["tsv"]).read_text(encoding="utf-8-sig").splitlines()]
    head = rows[0]
    by = {r[1]: r for r in rows[1:]}
    assert by["s01-3"][head.index("字幕")] == "ここでは A3 の用紙を選びます。"
    assert by["s01-3"][head.index("原稿")] == "ここではA3用紙を選びます。"
    assert by["s01-1"][head.index("字幕")] == ""  # 別表記の無い段落は空


def test_review_marks_transcript_mismatches_and_keeps_word_times(tmp_path, engine):
    doc, dictionary = _review_run(tmp_path, engine)

    def transcriber(wav: Path):
        if wav.stem == "s02":  # 「端」を「橋」と書き起こした、という作りの結果
            return [{"start": 0.0, "end": 0.6, "text": "", "words": [
                {"start": 0.02, "end": 0.15, "word": "A3の図面を印刷します。"},
                {"start": 0.3, "end": 0.5, "word": "出てきた紙の橋で、線が切れていないかを確かめます。"}]}]
        return []

    res = run_review(doc, tmp_path / "run", dictionary, None, transcriber=transcriber, model="fake", log=lambda m: None)
    rows = [r.split("\t") for r in Path(res["tsv"]).read_text(encoding="utf-8-sig").splitlines()]
    head = rows[0]
    by = {r[1]: r for r in rows[1:]}
    assert by["s02-1"][head.index("印")] == "確認語"  # 書き起こしは原稿と同じ（記号を除いて）
    assert by["s02-2"][head.index("印")] == "ずれ" and by["s02-2"][head.index("ずれ")] == "[端]→[橋]"
    assert res["mismatch"] >= 1 and res["transcribed"]
    tr = json.loads(Path(res["transcript"]).read_text(encoding="utf-8"))
    assert tr["model"] == "fake" and tr["items"]["s02"]["segments"][0]["words"][1]["start"] == 0.3
    assert by["s02-2"][head.index("モーラ")] == ""  # エンジンに問い合わせない（client=None）


def test_normalize_and_diff():
    assert normalize("ＡＩで、確かめる。") == normalize("AIで確かめる") == "aiで確かめる"
    assert diff_text("後半の端部です。", "後半の感度です") == "[端部]→[感度]"


def test_review_needs_durations(tmp_path):
    doc = sb.markdown_to_storyboard(A3.read_text(encoding="utf-8"))
    with pytest.raises(InputError, match="durations.json"):
        run_review(doc, tmp_path, PronunciationDictionary.empty(), None, log=lambda m: None)


def _dict_file(tmp_path: Path) -> Path:
    d = tmp_path / "dict.yaml"
    d.write_text("entries:\n  A3用紙: エーサンヨウシ\n", encoding="utf-8")
    return d


def test_cli_review_warns_without_faster_whisper(tmp_path, engine, monkeypatch, capsys):
    _review_run(tmp_path, engine)
    monkeypatch.setattr(review, "load_transcriber", lambda model: None)
    code = cli.main(["review", str(A3), "--run", str(tmp_path / "run"), "--dictionary", str(_dict_file(tmp_path)),
                     "--engine-url", "http://127.0.0.1:10101"], transport=engine)
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "faster-whisper が入っていない" in out.err and "review.tsv" in out.out
    assert (tmp_path / "run" / "checks" / "listen.html").is_file()


def test_cli_review_no_engine_no_transcribe(tmp_path, engine, capsys):
    _review_run(tmp_path, engine)
    engine.calls.clear()
    out_dir = tmp_path / "elsewhere"
    code = cli.main(["review", str(A3), "--run", str(tmp_path / "run"), "--no-engine", "--no-transcribe",
                     "--no-dictionary", "--out", str(out_dir)], transport=engine)
    assert code == 0, capsys.readouterr().err
    assert engine.calls == [] and (out_dir / "review.tsv").is_file() and not (tmp_path / "run" / "checks").exists()


def test_cli_review_confidential_keeps_the_engine_on_this_pc(tmp_path, engine, capsys):
    """社外秘の台本は、読みの問い合わせもこの PC のエンジンだけ（今までの voice の関所と同じ）。"""
    _review_run(tmp_path, engine)
    secret = tmp_path / "secret.storyboard.md"
    secret.write_text(A3.read_text(encoding="utf-8").replace("confidentiality: general", "confidentiality: confidential"),
                      encoding="utf-8")
    engine.calls.clear()
    code = cli.main(["review", str(secret), "--run", str(tmp_path / "run"), "--no-transcribe",
                     "--engine-url", "http://engine.example:10101"], transport=engine)
    assert code == 2 and engine.calls == [] and "社外秘" in capsys.readouterr().err
    assert not (tmp_path / "run" / "checks").exists()


def test_cli_review_rejects_a_missing_run(tmp_path, capsys):
    assert cli.main(["review", str(A3), "--run", str(tmp_path / "nothing"), "--no-engine", "--no-transcribe"]) == 2
    assert "出力フォルダがありません" in capsys.readouterr().err
