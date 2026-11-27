"""画面の組み立ての誤りを仕組みで防ぐ: はみ出し検査、表の見出しの文字での指定、
細線の太らせ方、字幕の折り方。"""
from __future__ import annotations

import pytest

from explainer_reel_kit.interactive.engine import Frame, LayoutError, texts_of, thicken_mode, tw
from explainer_reel_kit.interactive.parts import Table, card_text
from explainer_reel_kit.interactive.subtitles import (SUB_MAXW, SUB_SIZE, SUB_WEIGHT, cue_lines, fits_subtitle,
                                                  wrap_subtitle, wrap_subtitle_info)

# ---------------------------------------------------------------- 同梱の書体（OTF 2 つと OFL。sha256 は fonts/README.md）


def test_bundled_fonts_are_noto_sans_jp_otf_with_recorded_sha256():
    import hashlib
    import re

    from explainer_reel_kit.interactive import engine

    readme = (engine.FONT_DIR / "README.md").read_text(encoding="utf-8")
    for weight, style in (("R", "Regular"), ("B", "Bold")):
        path = engine.FONT_DIR / engine.FONT_FILES[weight]
        data = path.read_bytes()
        assert path.suffix == ".otf" and data[:4] == b"OTTO"
        assert engine.font(weight, 32).getname() == ("Noto Sans JP", style)
        row = re.search(rf"`{re.escape(path.name)}`.*`([0-9a-f]{{64}})`", readme)
        assert row and row.group(1) == hashlib.sha256(data).hexdigest()
    assert (engine.FONT_DIR / "OFL.txt").read_text(encoding="utf-8").startswith(
        "This Font Software is licensed under the SIL Open Font License")
    assert not list(engine.FONT_DIR.glob("*.ttc"))


# ---------------------------------------------------------------- 文字のはみ出し


def test_text_with_maxw_raises_when_too_wide():
    f = Frame()
    f.text("短い", 0, 0, size=32, maxw=200)
    with pytest.raises(LayoutError, match="枠に入りません"):
        f.text("とても長い見出しの文字はこの枠には入りません", 0, 0, size=48, maxw=200)


def test_text_box_wraps_and_raises_when_too_tall():
    f = Frame()
    lines = f.text_box("結露を減らすには、窓の表面を冷やさないことと、部屋の湿度を上げないことが大切です。", 0, 0, 400, 200, size=28)
    assert len(lines) > 1 and all(tw(s, "R", 28) <= 400 for s in lines)
    with pytest.raises(LayoutError, match="行"):
        Frame().text_box("結露を減らすには、窓の表面を冷やさないことと、部屋の湿度を上げないことが大切です。", 0, 0, 400, 60, size=28)


def test_card_text_checks_title_and_body():
    card_text(Frame(), 0, 0, 400, 220, title="① 暖かい空気", body="目に見えない水蒸気を含む")
    with pytest.raises(LayoutError):
        card_text(Frame(), 0, 0, 200, 220, title="とても長いカードの見出しです", body="x")
    with pytest.raises(LayoutError):
        card_text(Frame(), 0, 0, 400, 100, title="見出し", body="本文が長すぎてカードの高さに収まらない場合はエラーにします。" * 3)


# ---------------------------------------------------------------- 表の行・列は見出しの文字で

TB = Table(100, 200, [300, 200, 200], [60, 80, 80], cols=["ガラス", "表面", "判定"], rows=["見出し", "1 枚", "複層"])


def test_table_is_addressed_by_heading_text():
    assert TB.cell("1 枚", "表面") == (400, 260, 200, 80)
    assert TB.row("複層") == (100, 340, 700, 80)
    assert TB.col("判定") == (600, 200, 200, 220)
    assert TB.col("判定", from_row="1 枚") == (600, 260, 200, 160)


def test_table_rejects_numbers_and_unknown_headings():
    with pytest.raises(LayoutError, match="見出しの文字"):
        TB.row(1)
    with pytest.raises(LayoutError, match="見出しの文字"):
        TB.cell("1 枚", 2)
    with pytest.raises(LayoutError, match="ありません"):
        TB.row("3 枚")


def test_table_rejects_duplicate_or_mismatched_headings():
    with pytest.raises(LayoutError, match="重複"):
        Table(0, 0, [10, 10], [10], cols=["a", "a"], rows=["r"])
    with pytest.raises(LayoutError, match="数"):
        Table(0, 0, [10, 10], [10], cols=["a"], rows=["r"])


def test_table_cell_text_overflow_is_an_error():
    f = Frame()
    TB.draw_cell(f, "1 枚", "表面", "約 6℃", size=40)
    assert "約 6℃" in texts_of(f.ops)
    with pytest.raises(LayoutError):
        TB.draw_cell(Frame(), "1 枚", "表面", "セルの幅には入らない長い文字列です", size=40)
    with pytest.raises(LayoutError):
        TB.draw_cell(Frame(), "見出し", "表面", ["1 行目", "2 行目"], size=40)   # 高さ 60 に 2 行は入らない


def test_table_veil_cells_uses_heading_text():
    f = Frame()
    TB.veil_cells(f, lambda r, c: 1.0 if r == "1 枚" else 0.0, from_row="1 枚")
    assert len(f.ops) == 3   # 「複層」の行の 3 セルだけ沈める


# ---------------------------------------------------------------- 細線の太らせ方


def test_thicken_mode_by_scale():
    assert thicken_mode(2000, 1000, 800, 400) == "thick2"   # 半分より小さく縮める → 1 画素
    assert thicken_mode(2000, 1000, 1500, 750) == "thick"   # 少し縮める → 半画素
    assert thicken_mode(1000, 500, 1000, 500) == ""         # 縮めない


# ---------------------------------------------------------------- 字幕の折り方


def test_short_subtitle_is_one_line():
    assert wrap_subtitle("窓に水滴がつくのはなぜでしょうか") == ["窓に水滴がつくのはなぜでしょうか"]


def test_two_lines_break_right_after_comma():
    text = "たとえば、室温が二十度、湿度が六十パーセントの部屋では、露点はおよそ十二度"
    lines, at_comma = wrap_subtitle_info(text)
    assert len(lines) == 2 and at_comma and lines[0][-1] == "、" and "".join(lines) == text


def test_never_breaks_inside_alphanumerics():
    text = "設定ファイルの名前は ExplainerReelInteractiveRenderTimelineSchemaVersionOne です。ここを書き換えます"
    lines = wrap_subtitle(text)
    assert len(lines) == 2
    a, b = lines
    assert not (a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum())


def test_no_line_head_kinsoku():
    text = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんあいうえお。かきくけこ"
    for line in wrap_subtitle(text)[1:]:
        assert line[0] not in "、。）」"


def test_three_lines_is_an_error():
    text = "あ" * 140
    assert not fits_subtitle(text)
    with pytest.raises(LayoutError, match="2 行"):
        wrap_subtitle(text)


def test_cue_lines_respects_given_lines_and_limits():
    assert cue_lines({"text": "a", "lines": ["一行目", "二行目"]}) == ["一行目", "二行目"]
    with pytest.raises(LayoutError):
        cue_lines({"text": "a", "lines": ["1", "2", "3"]})
    with pytest.raises(LayoutError):
        cue_lines({"text": "a", "lines": ["あ" * 60]})
    assert tw("あ" * 60, SUB_WEIGHT, SUB_SIZE) > SUB_MAXW
