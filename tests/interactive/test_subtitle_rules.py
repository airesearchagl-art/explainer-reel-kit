"""字幕の分け方（改行は読点の直後だけ）・字幕の別表記・SRT の時刻・文の時刻の寄せ方。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from explainer_reel_kit.interactive.convert import from_storyboard, split_for_subtitles, subtitle_text
from explainer_reel_kit.interactive.subtitles import frame_ms, parse_srt, srt_frame, srt_text, wrap_subtitle_info, write_srt
from explainer_reel_kit.interactive.sync import snap


def test_srt_time_maps_back_to_the_same_frame():
    """SRT の時刻（フレームの始まりをミリ秒に切り捨て）→ その時刻以降の最初のフレーム、で元のフレームに戻る。"""
    for fps in (30, 25, 24, 60):
        assert all(srt_frame(frame_ms(f, fps), fps) == f for f in range(0, 200000, 7))


def test_srt_text_uses_the_same_lines_as_the_burned_subtitles():
    cues = [{"text": "まず、設定を開きます", "start_frame": 0, "end_frame": 46, "lines": ["まず、", "設定を開きます"]},
            {"text": "次へ", "start_frame": 46, "end_frame": 109}]
    assert srt_text(cues, 30) == ("1\n00:00:00,000 --> 00:00:01,533\nまず、\n設定を開きます\n\n"
                                  "2\n00:00:01,533 --> 00:00:03,633\n次へ\n")


def test_written_srt_reads_back_to_the_same_frames(tmp_path):
    cues = [{"text": "まず、設定を開きます", "start_frame": 7, "end_frame": 46, "lines": ["まず、", "設定を開きます"]},
            {"text": "次へ", "start_frame": 46, "end_frame": 109}]
    write_srt(cues, 30, tmp_path / "a.srt")
    back = parse_srt(tmp_path / "a.srt")
    assert [(srt_frame(c["start_ms"]), srt_frame(c["end_ms"]), c["text"]) for c in back] == [
        (7, 46, "まず、設定を開きます"), (46, 109, "次へ")]


def test_long_sentences_break_lines_only_after_commas():
    text = subtitle_text("室内の暖かい空気が冷たい窓に触れると、空気が冷やされて、含みきれなくなった水蒸気が水滴になり、"
                         "窓の表面に付きます。そのため、冬の朝は窓の下の方に水がたまりやすく、木の枠が傷むこともあります。")
    pieces = split_for_subtitles(text)
    assert "".join(pieces) == text and len(pieces) > 1
    for p in pieces:
        lines, at_comma = wrap_subtitle_info(p)
        assert len(lines) <= 2 and (len(lines) == 1 or at_comma), lines


def test_snap_moves_estimates_to_the_nearest_long_enough_silence():
    runs = [(1.0, 1.05), (1.9, 2.3), (4.0, 4.5)]
    out, hits = snap([2.0, 4.6], runs, min_gap=0.15, window=0.5)
    assert hits == 2 and out == [pytest.approx(2.2), pytest.approx(4.4)]   # 無音の終わりの 0.1 秒前
    out, hits = snap([3.0], runs, min_gap=0.15, window=0.5)
    assert hits == 0 and out == [3.0]                                       # 近くに無音が無ければ推定のまま


DOC = {"reel": {"id": "r", "title": "T"}, "intro": {"summary": "s", "narration": "はじめ。"},
       "scenes": [{"id": "s01", "heading": "見る", "narration": "一つ目です。二つ目です。\n三つ目です。",
                   "subtitles": [{"paragraph": 1, "text": "1 つ目です。2 つ目です。"},
                                 {"paragraph": 2, "text": "三つ目、別の表記で長く書いた字幕です。続きもあります。"}]}],
       "outro": {"summary": "s", "narration": "おわり。"}}


def _timings():
    t = SimpleNamespace
    return [t(id="intro", start_ms=0, adv_ms=2000, transition_ms=0),
            t(id="s01", start_ms=2000, adv_ms=6000, transition_ms=0),
            t(id="outro", start_ms=8000, adv_ms=2000, transition_ms=0)]


def _durations():
    return {"pre_pause_sec": 0.3, "items": [
        {"id": "intro", "audio_sec": 1.0, "paragraph_starts_sec": [0.0]},
        {"id": "s01", "audio_sec": 5.0, "paragraph_starts_sec": [0.0, 3.0]},
        {"id": "outro", "audio_sec": 1.0, "paragraph_starts_sec": [0.0]}]}


def test_subtitle_alternative_per_sentence_and_per_paragraph():
    narration = {"intro": "はじめ。", "s01": "一つ目です。二つ目です。\n三つ目です。", "outro": "おわり。"}
    readings = {"intro": "はじめ。", "s01": "ひとつめです。ふたつめです。\nみっつめです。", "outro": "おわり。"}
    tl, warns = from_storyboard(DOC, _timings(), _durations(), narration, readings=readings)
    sents = {e["id"]: e for e in tl["sentences"]}
    # 段落 1: 別表記の文の数が原稿と同じ → 文ごとの字幕
    assert sents["s01-1"]["subtitle"] == "1 つ目です。" and sents["s01-2"]["subtitle"] == "2 つ目です。"
    assert sents["s01-1"]["reading"] == "ひとつめです。" and sents["s01-1"]["paragraph"] == 1
    assert sents["s01-1"]["timing"] == "estimated"     # chunk_frames の無い記録は推定
    texts = [c["text"] for c in tl["cues"]]
    assert "1 つ目です" in texts and "2 つ目です" in texts and "一つ目です" not in texts
    # 段落 2: 別表記の文の数（2）が原稿（1）と違う → 段落の時間を別表記で分ける。原稿の文は変えない
    assert sents["s01-3"]["spoken"] == "三つ目です。" and sents["s01-3"]["subtitle"].startswith("三つ目、別の表記")
    p2 = [c for c in tl["cues"] if c["sentence"] == "s01-3"]
    assert "".join(c["text"] for c in p2) == "三つ目、別の表記で長く書いた字幕です続きもあります"
    assert p2[0]["start_frame"] == round((2.0 + 0.3 + 3.0) * 30) and p2[-1]["end_frame"] == round((2.0 + 0.3 + 5.0) * 30)
    assert all(c.get("lines") for c in tl["cues"])
