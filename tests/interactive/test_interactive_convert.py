"""台本から中間データを作る変換器（convert.from_storyboard）。"""
from __future__ import annotations

from dataclasses import dataclass

from explainer_reel_kit.interactive.convert import (from_storyboard, split_for_subtitles, storyboard_images,
                                                    subtitle_text)
from explainer_reel_kit.interactive.subtitles import fits_subtitle
from explainer_reel_kit.interactive.timeline import validate_timeline

# ---------------------------------------------------------------- 台本から

@dataclass
class _T:
    id: str
    start_ms: int
    adv_ms: int
    transition_ms: int


DOC = {
    "reel": {"id": "demo", "title": "デモ"},
    "intro": {"summary": "要約です。", "prerequisites": ["特になし"]},
    "scenes": [{"id": "s01", "heading": "見る", "image": {"ref": "assets/s01.png"}}],
    "outro": {"summary": "まとめです。", "checks": ["一つ"]},
}


def test_from_storyboard_uses_slide_times_and_paragraphs():
    timings = [_T("intro", 0, 3000, 0), _T("s01", 3000, 4000, 750), _T("outro", 7750, 2000, 750)]
    durations = {"pre_pause_sec": 0.3, "items": [
        {"id": "intro", "audio_sec": 2.2, "paragraph_starts_sec": [0.0]},
        {"id": "s01", "audio_sec": 3.0, "paragraph_starts_sec": [0.0, 1.8]},
        {"id": "outro", "audio_sec": 1.0, "paragraph_starts_sec": [0.0]}]}
    narration = {"intro": "はじめます。", "s01": "一つ目の文です。二つ目の文です。\n次の段落です。", "outro": "おわりです。"}
    doc, warns = from_storyboard(DOC, timings, durations, narration, images={"s01": "assets/s01.png"}, credit="X")
    assert warns == [] and validate_timeline(doc) == []
    assert doc["total_frames"] == 315   # (3000 + 4750 + 2750) ms × 30 fps
    assert [(s["id"], s["start_frame"], s["end_frame"]) for s in doc["scenes"]] == [
        ("intro", 0, 90), ("s01", 90, 233), ("outro", 233, 315)]
    assert doc["scenes"][1]["image"] == "assets/s01.png" and doc["scenes"][0]["title"] == "デモ"
    assert doc["scenes"][0]["body"] == ["要約です。", "・特になし"] and doc["meta"]["credit"] == "X"
    s = {v["id"]: v for v in doc["sentences"]}
    # s01 の WAV はスライド開始 3.0 ＋ 切替 0.75 ＋ pre 0.3 = 4.05s から。段落 2 は 1.8 秒後
    assert s["s01-1"]["start_sec"] == 4.05 and s["s01-3"]["start_sec"] == round(4.05 + 1.8, 3)
    assert s["s01-2"]["end_sec"] == s["s01-3"]["start_sec"] and s["s01-3"]["end_sec"] == round(4.05 + 3.0, 3)
    assert [c["text"] for c in doc["cues"]] == ["はじめます", "一つ目の文です", "二つ目の文です", "次の段落です", "おわりです"]
    assert doc["cues"][1]["start_frame"] == 122   # ceil(4.05 × 30)


def test_paragraph_count_mismatch_warns_and_spreads():
    timings = [_T("intro", 0, 3000, 0), _T("s01", 3000, 3000, 0), _T("outro", 6000, 2000, 0)]
    durations = {"pre_pause_sec": 0.3, "items": [
        {"id": "s01", "audio_sec": 2.0, "paragraph_starts_sec": [0.0]}]}
    doc, warns = from_storyboard(DOC, timings, durations, {"s01": "一つ目。\n二つ目。"})
    assert any("段落の数" in w for w in warns)
    assert validate_timeline(doc) == []


def test_long_sentence_is_split_into_two_line_cues():
    long = "、".join(["結露を減らすには窓の表面を冷やさないことが大切です"] * 4) + "。"
    pieces = split_for_subtitles(subtitle_text(long))
    assert len(pieces) >= 2 and all(fits_subtitle(p) for p in pieces)
    assert "".join(pieces) == subtitle_text(long)
    assert all(p.endswith("、") for p in pieces[:-1])   # 読点の直後で分ける


def test_subtitle_text_drops_final_period_only():
    assert subtitle_text("おわりです。") == "おわりです" and subtitle_text("え？") == "え？"


def test_text_card_scene_uses_the_card_and_no_image(tmp_path):
    doc = {"reel": {"id": "demo", "title": "デモ"}, "intro": {"summary": "要約です。"},
           "scenes": [{"id": "s01", "heading": "見る", "image": {"source": "generated", "ref": "a.png"},
                       "recipe_params": {"card": {"title": "カードの見出し", "text": "カードの文"}}},
                      {"id": "s02", "heading": "比べる", "image": {"source": "manual", "ref": "b.png"},
                       "on_screen_text": "画面の文字"}],
           "outro": {"summary": "まとめです。"}}
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")
    assert storyboard_images(doc, tmp_path, rel_to=tmp_path) == {"s02": "b.png"}
    timings = [_T("intro", 0, 1000, 0), _T("s01", 1000, 1000, 0), _T("s02", 2000, 1000, 0), _T("outro", 3000, 1000, 0)]
    out, _ = from_storyboard(doc, timings, {"items": []}, {})
    sc = {s["id"]: s for s in out["scenes"]}
    assert sc["s01"]["title"] == "カードの見出し" and sc["s01"]["body"] == ["カードの文"]
    assert sc["s02"]["title"] == "比べる" and sc["s02"]["body"] == ["画面の文字"]
