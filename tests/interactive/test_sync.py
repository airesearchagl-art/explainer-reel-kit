"""文の時刻を WAV の実尺から測る（sync.measure）と、作り直した前後の比較（sync.resync_report）。

durations.json の item（chunk_frames・chunk_sentences・sample_rate・paragraph_starts_sec・fit.cuts）は
ナレーションの段の記録の形。ここでは WAV と記録を直接作って確かめる。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from interactive_helpers import EDGE_SEC, GAP_SEC, RATE, SEC_PER_CHAR, speech_pcm, wav_bytes

from explainer_reel_kit.interactive import sync

P1 = "まず、印刷の設定を開きます。用紙の大きさを選ぶ欄があります。"
P2 = "大きさを選んだら、印刷を押します。"
TEXT = P1 + "\n" + P2


def _item(tmp_path: Path) -> tuple[dict, Path]:
    """段落 1（2 文）と段落 2（1 文）を、段落ごとの分割で合成した WAV と記録。"""
    chunks = [speech_pcm(P1), speech_pcm(P2)]
    wav = tmp_path / "s01.wav"
    wav.write_bytes(wav_bytes(b"".join(chunks)))
    frames = [len(c) // 2 for c in chunks]
    rec = {"id": "s01", "wav": "s01.wav", "audio_sec": round(sum(frames) / RATE, 3), "sample_rate": RATE,
           "chunk_frames": frames, "chunk_sentences": [2, 1], "paragraph_starts_sec": [0.0, round(frames[0] / RATE, 3)]}
    return rec, wav


def test_sentence_boundary_inside_a_chunk_snaps_to_the_silence(tmp_path):
    rec, wav = _item(tmp_path)
    m = sync.measure(TEXT, rec, wav)
    assert m["timing"] == "measured" and m["warnings"] == []
    (a1, b1), (a2, b2) = m["paragraphs"][0]
    first = "まず、印刷の設定を開きます。"
    # 境目は 1 文目の音の終わり ＋ 文の間の無音 − 0.1 秒（次の文の声の始まりの少し前）
    assert b1 == a2 == pytest.approx(EDGE_SEC + len(first) * SEC_PER_CHAR + GAP_SEC - 0.1, abs=0.02)
    # 分割の境目（段落 2 の始まり）は chunk_frames から正確に
    assert m["paragraphs"][1][0][0] == pytest.approx(rec["chunk_frames"][0] / RATE, abs=1e-6)
    assert m["paragraphs"][1][0][1] == pytest.approx(rec["audio_sec"], abs=1e-3)
    assert m["snapped"] == 1


def test_without_chunk_frames_the_times_are_estimated_from_paragraph_starts(tmp_path):
    rec, wav = _item(tmp_path)
    for k in ("chunk_frames", "chunk_sentences", "sample_rate"):
        rec.pop(k)
    m = sync.measure(TEXT, rec, wav)
    assert m["timing"] == "estimated"
    assert m["paragraphs"][1][0][0] == rec["paragraph_starts_sec"][1]


def test_mismatched_chunk_sentences_fall_back_with_a_warning(tmp_path):
    rec, wav = _item(tmp_path)
    rec["chunk_sentences"] = [1, 2]
    m = sync.measure(TEXT, rec, wav)
    assert m["timing"] == "estimated" and any("合わない" in w for w in m["warnings"])


def test_fit_cuts_are_mapped_to_the_squeezed_wav(tmp_path):
    rec, wav = _item(tmp_path)
    full = sync.measure(TEXT, rec, wav)
    gap = (EDGE_SEC + len("まず、印刷の設定を開きます。") * SEC_PER_CHAR, None)
    cut = [round(gap[0] + 0.05, 6), round(gap[0] + 0.25, 6)]          # 文の間の無音から 0.2 秒抜いた
    rec2 = dict(rec, fit={"cuts": [cut]})
    m = sync.measure(TEXT, rec2, wav, runs=[])                       # 寄せずに、分割の境目の換算だけを見る
    assert m["paragraphs"][1][0][0] == pytest.approx(full["paragraphs"][1][0][0] - 0.2, abs=1e-6)
    assert sync.map_sec(cut[0] + 0.1, [cut]) == pytest.approx(cut[0])   # 抜いた区間の中は抜いた始まりへ


def test_silences_reads_the_wav(tmp_path):
    _, wav = _item(tmp_path)
    runs, n, rate = sync.silences(wav)
    assert rate == RATE and runs[0][0] == 0 and runs[-1][1] == n
    secs = sync.item_silences(wav)
    assert any(b - a >= GAP_SEC - 0.02 for a, b in secs)


def test_resync_report_lists_changed_sentences_and_scene_shifts(tmp_path):
    def tl(shift: float, spoken3: str) -> dict:
        sents = [{"id": "intro-1", "scene": "intro", "paragraph": 1, "spoken": "はじめます。", "start_sec": 0.3,
                  "end_sec": 1.0 + shift},
                 {"id": "s01-1", "scene": "s01", "paragraph": 1, "spoken": "一つ目。", "start_sec": 2.0 + shift,
                  "end_sec": 2.5 + shift},
                 {"id": "s01-2", "scene": "s01", "paragraph": 1, "spoken": "二つ目。", "start_sec": 2.5 + shift,
                  "end_sec": 3.0 + shift},
                 {"id": "s01-3", "scene": "s01", "paragraph": 2, "spoken": spoken3, "start_sec": 3.0 + shift,
                  "end_sec": 3.8 + shift}]
        f = round(shift * 30)
        return {"fps": 30, "total_frames": 150 + f, "cues": [{}] * 4, "sentences": sents,
                "scenes": [{"id": "intro", "start_frame": 0, "end_frame": 50 + f},
                           {"id": "s01", "start_frame": 50 + f, "end_frame": 150 + f}]}

    old, new = tl(0.0, "三つ目。"), tl(-0.2, "三つ目です。")
    durations = {"items": [{"id": "intro", "synthesized_paragraphs": [1]}, {"id": "s01", "synthesized_paragraphs": [2]}]}
    rec = sync.resync_report(old, new, durations, tmp_path / "checks")
    assert rec["compared"] is True and rec["synthesized_paragraphs"] == {"intro": [1], "s01": [2]}
    roles = {e["id"]: e["role"] for e in rec["sentences"]}
    assert roles["s01-3"] == "再合成" and roles["intro-1"] == "再合成" and roles["s01-2"] == "前後の文"
    shifts = {s["id"]: s.get("shift_frames") for s in rec["scenes"]}
    assert shifts == {"intro": 0, "s01": -6}
    md = (tmp_path / "checks" / "resync.md").read_text(encoding="utf-8")
    assert "再合成した段落" in md and "s01-3" in md
    assert json.loads((tmp_path / "checks" / "resync.json").read_text(encoding="utf-8"))["cues_before"] == 4
    first = sync.resync_report(None, new, None, tmp_path / "c2")
    md2 = (tmp_path / "c2" / "resync.md").read_text(encoding="utf-8")
    assert first["compared"] is False and first["first"] is True and "初めての合成（前の出力なし）" in md2


def test_first_build_does_not_say_resynthesized(tmp_path):
    """初めての作成では、すべての段落を合成していても「再合成」と書かない（文の一覧も出さない）。"""
    new = {"fps": 30, "scenes": [{"id": "s01", "start_frame": 0, "end_frame": 90}],
           "sentences": [{"id": "s01-1", "scene": "s01", "paragraph": 1, "spoken": "はじめの文。",
                          "start_sec": 0.2, "end_sec": 1.5}], "cues": [], "total_frames": 90}
    durations = {"items": [{"id": "s01", "synthesized_paragraphs": [1]}]}
    rec = sync.resync_report(None, new, durations, tmp_path / "first")
    md = (tmp_path / "first" / "resync.md").read_text(encoding="utf-8")
    assert rec["first"] is True and rec["sentences"] == []
    assert "再合成" not in md and "初めての合成（前の出力なし）" in md
    # 前の出力の WAV を使い回したとき（--reuse-run）は、前の中間データが無くても初めての作成ではない
    durations2 = {"items": [{"id": "s01", "synthesized_paragraphs": [1], "reused_from": "prev/work/narration"}]}
    rec2 = sync.resync_report(None, new, durations2, tmp_path / "again")
    assert rec2["first"] is False and "再合成した段落: s01 の段落 1" in (tmp_path / "again" / "resync.md").read_text(encoding="utf-8")
