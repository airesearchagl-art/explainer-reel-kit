"""イントロのタイトルの行頭禁則・所要時間（動画の長さ）、カードの行。"""
from __future__ import annotations

import json

import pytest
from pptx import Presentation
from pptx.util import Inches

from deck_helpers import SAMPLES
from explainer_reel_kit.deck.builder import build_deck, format_duration
from explainer_reel_kit.deck.textfit import EMU_PER_PT, INSET_X, KINSOKU_HEAD, estimate_height_pt, one_line_scale, wrap_lines
from deck_helpers import pptx_total_sec
from test_deck_marks import _story


# ------------------------------------------------------------------ 行頭禁則

@pytest.mark.parametrize("text", [
    "自作ツールの一覧（Webツール）",
    "あいうえおかきくけこ、さしすせそ。たちつてと」なにぬねの",
    "ガラリ・パンチングメタル・アンダーカットを比べる。",
    "設計条件の整理、作業計画、設計変更の差分確認。",
])
@pytest.mark.parametrize("width", [40, 55, 70, 90, 130, 200])
def test_no_line_starts_with_closing_or_punctuation(text, width):
    lines = wrap_lines(text, 10, width)
    assert "".join(lines) == text
    for ln in lines[1:]:
        assert ln and ln[0] not in KINSOKU_HEAD, lines
    assert all(c in KINSOKU_HEAD for c in "）」、。")


def test_wrap_pushes_previous_char_with_the_closing_bracket():
    # 「（Web」の次で幅が尽きると、従来は「）」だけが 2 行目に来る
    lines = wrap_lines("一覧（Webツール）", 10, 10 * (3 + 0.55 * 3 + 3))
    assert lines == ["一覧（Webツー", "ル）"]


def test_estimate_counts_kinsoku_lines():
    w = int(10 * 4 * EMU_PER_PT + INSET_X)  # 4 文字分の幅
    # 「あいうえ」「お。」→ 2 行
    assert estimate_height_pt([("あいうえお。", 10)], w) == pytest.approx(2 * 10 * 1.2)


def test_one_line_scale():
    assert one_line_scale("短い", 36, Inches(6.5)) == 1.0
    # 幅の 90% に収める（実際の描画は見積もりより広くなることがある）
    assert one_line_scale("自作ツールの一覧（Webツール）", 36, Inches(6.5)) == pytest.approx(0.75)
    assert one_line_scale("自作ツールの一覧（プラグイン・デスクトップ・ナレッジ）", 36, Inches(11.733)) == pytest.approx(0.75)
    assert one_line_scale("とても長いタイトル" * 4, 36, Inches(6.5)) is None  # 0.75 倍でも収まらなければ縮めない


def _title(prs):
    return next(s for s in prs.slides[0].shapes if s.name == "Title")


def test_catalog_title_is_one_line_with_slightly_smaller_font(tmp_path):
    """「自作ツールの一覧（Webツール）」: 右に縮小画像がある幅（6.5in）でも、0.75 倍で 1 行にする。"""
    sb = _story(tmp_path, [("s01", "fade_sequence", None)])
    doc = json.loads(sb.read_text(encoding="utf-8"))
    doc["reel"]["title"] = "自作ツールの一覧（Webツール）"
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    prs = Presentation(str(build_deck(sb, tmp_path / "o.pptx").output))
    t = _title(prs)
    assert t.width == Inches(6.5)  # 縮小画像あり
    run = t.text_frame.paragraphs[0].runs[0]
    assert run.font.size.pt == pytest.approx(36 * 0.75, abs=0.1)
    width_pt = (t.width - INSET_X) / EMU_PER_PT
    assert len(wrap_lines(run.text, run.font.size.pt, width_pt)) == 1
    # PowerPoint に日本語の改行規則を使わせる
    xml = t._element.xml
    assert 'lang="ja-JP"' in xml and 'eaLnBrk="1"' in xml


def test_long_title_keeps_wrapping_without_kinsoku_violation(tmp_path):
    from deck_helpers import variant

    def edit(doc):
        doc["reel"]["title"] = "経路に沿って部材を等間隔に並べる、設定から結果の確認までの手順（入力・確認・やり直し）"
    prs = Presentation(str(build_deck(variant("generated", tmp_path, edit), tmp_path / "o.pptx").output))
    t = _title(prs)
    run = t.text_frame.paragraphs[0].runs[0]
    lines = wrap_lines(run.text, run.font.size.pt, (t.width - INSET_X) / EMU_PER_PT)
    assert all(ln[0] not in KINSOKU_HEAD for ln in lines[1:])


# ------------------------------------------------------------------ 所要時間

def test_format_duration():
    assert format_duration(88.4) == "約 1 分 28 秒"
    assert format_duration(45) == "約 45 秒"
    assert format_duration(59.6) == "約 1 分 0 秒"
    assert format_duration(600) == "約 10 分 0 秒"


def _durations(tmp_path, ids, sec=7.0):
    p = tmp_path / "durations.json"
    p.write_text(json.dumps({"format": "explainer-reel/narration-durations", "version": 2, "pre_pause_sec": 0.3,
                             "items": [{"id": i, "slide_sec": sec} for i in ids]}), encoding="utf-8")
    return p


def _intro_meta(prs) -> str:
    shp = next((s for s in prs.slides[0].shapes if s.name == "Prerequisites"), None)
    return shp.text_frame.text if shp is not None else ""


@pytest.mark.parametrize("note", [None, "", "未計測"])
def test_duration_from_narration_when_unmeasured(tmp_path, note):
    sb = _story(tmp_path, [("s01", "fade_sequence", None), ("s02", "fade_sequence", None)])
    doc = json.loads(sb.read_text(encoding="utf-8"))
    if note is not None:
        doc["intro"]["duration_note"] = note
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    res = build_deck(sb, tmp_path / "o.pptx", durations=_durations(tmp_path, ["intro", "s01", "s02", "outro"], 22.0))
    # 動画の長さ（reel mux と同じ計算: advTm ＋ フェード 0.75 秒）と一致
    total = pptx_total_sec(res.output)
    assert res.video_sec == pytest.approx(total)
    assert f"所要時間: {format_duration(total)}" in _intro_meta(Presentation(str(res.output)))
    assert "未計測" not in _intro_meta(Presentation(str(res.output)))


def test_duration_note_with_a_value_is_kept(tmp_path):
    sb = _story(tmp_path, [("s01", "fade_sequence", None)])
    doc = json.loads(sb.read_text(encoding="utf-8"))
    doc["intro"]["duration_note"] = "約 5 分（入力から確認まで）"
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    for dur in (None, _durations(tmp_path, ["intro", "s01", "outro"])):
        prs = Presentation(str(build_deck(sb, tmp_path / "o.pptx", durations=dur).output))
        assert "所要時間: 約 5 分（入力から確認まで）" in _intro_meta(prs)


def test_deck_alone_shows_no_duration(tmp_path):
    sb = _story(tmp_path, [("s01", "fade_sequence", None)])
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.video_sec is None
    prs = Presentation(str(res.output))
    assert "所要時間" not in _intro_meta(prs)
    assert all(s.name != "Prerequisites" for s in prs.slides[0].shapes)  # 前提も無ければ枠ごと出さない


def test_duration_includes_split_slides_and_morph(tmp_path):
    from test_deck_morph_pan import _split_story

    from explainer_reel_kit.deck.builder import load_storyboard

    sb = _split_story(tmp_path)
    d = load_storyboard(sb, None)
    ids = ["intro", *[s["id"] for s in d["scenes"]], "outro"]
    res = build_deck(sb, tmp_path / "o.pptx", durations=_durations(tmp_path, ids, 9.0))
    assert res.split  # Morph でつないだスライドがある
    assert res.video_sec == pytest.approx(pptx_total_sec(res.output))
