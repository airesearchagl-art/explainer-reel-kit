"""台本の版 kit-1.2.0: reel.render_mode、字幕の別表記 subtitles（Markdown では <!-- subtitle: … -->）、固定尺の枠 slot_sec。"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from explainer_reel_kit import storyboard as sb

ROOT = Path(__file__).resolve().parents[1]
U_VALUE = ROOT / "samples" / "u-value"


def _md(body: str = "本文です。", version: str = "kit-1.2.0", extra_reel: str = "") -> str:
    return f"""---
id: t
title: T
schema_version: {version}
audience: A
kind: work_manual
confidentiality: general
aspect: "16:9"
output_name: t
{extra_reel}---
## intro
```yaml
summary: s
```
{body}

## s01: 確かめる
```yaml
image: {{source: manual, ref: a.png, label: 実キャプチャ}}
recipe: fade_sequence
capture: {{instructions: 撮る}}
```
本文です。

## outro
```yaml
summary: s
```
おわりです。
"""


def _errors(doc) -> list[str]:
    return [e for e in sb.validate_storyboard(doc).errors if not e.startswith("[image]")]  # manual 画像の実在は見ない


# ------------------------------------------------------------------ 版

def test_versions():
    assert sb.SCHEMA_VERSION == "kit-1.2.0"
    assert sb.SCHEMA_VERSIONS == ("1.0.0", "1.1.0", "kit-1.0.0", "kit-1.1.0", "kit-1.2.0")
    schema = sb.load_schema()
    assert schema["$defs"]["reel"]["properties"]["render_mode"]["enum"] == ["slides", "interactive"]
    assert "subtitles" in schema["$defs"]["scene"]["properties"] and "slot_sec" in schema["$defs"]["intro"]["properties"]


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "kit-1.0.0", "kit-1.1.0", "kit-1.2.0"])
def test_older_storyboards_without_the_new_fields_still_pass(version):
    doc = sb.markdown_to_storyboard(_md(version=version))
    if version == "1.0.0":
        doc["reel"].pop("confidentiality")  # confidentiality は 1.1.0 から
    assert _errors(doc) == []
    assert sb.render_mode(doc) == "slides"


def test_kit_1_1_0_sample_still_passes():
    doc = sb.load_storyboard(U_VALUE / "u-value.storyboard.md")
    older = copy.deepcopy(doc)
    older["reel"]["schema_version"] = "kit-1.1.0"
    older["reel"].pop("render_mode", None)
    for node in [older["intro"], older["outro"], *older["scenes"]]:
        node.pop("subtitles", None)
        node.pop("slot_sec", None)
    assert sb.validate_storyboard(older, base_dir=U_VALUE).errors == []


# ------------------------------------------------------------------ render_mode

@pytest.mark.parametrize("value", ["slides", "interactive"])
def test_render_mode_values(value):
    doc = sb.markdown_to_storyboard(_md(extra_reel=f"render_mode: {value}\n"))
    assert _errors(doc) == []
    assert sb.render_mode(doc) == value


@pytest.mark.parametrize("value", ["Interactive", "video", ""])
def test_unknown_render_mode_is_a_schema_error(value):
    doc = sb.markdown_to_storyboard(_md())
    doc["reel"]["render_mode"] = value
    assert any(e.startswith("[schema] reel/render_mode") for e in _errors(doc))
    assert sb.render_mode(doc) == "slides"  # 読めない値は今までの経路


def test_command_option_wins_over_the_storyboard():
    doc = sb.markdown_to_storyboard(_md(extra_reel="render_mode: slides\n"))
    assert sb.render_mode(doc, "interactive") == "interactive"
    doc["reel"]["render_mode"] = "interactive"
    assert sb.render_mode(doc) == "interactive" and sb.render_mode(doc, "slides") == "slides"
    with pytest.raises(ValueError):
        sb.render_mode(doc, "video")


@pytest.mark.parametrize("version", ["1.1.0", "kit-1.0.0", "kit-1.1.0"])
def test_render_mode_needs_kit_1_2_0(version):
    doc = sb.markdown_to_storyboard(_md(version=version, extra_reel="render_mode: interactive\n"))
    assert _errors(doc) == ["[version] reel: 映像の作り方（reel.render_mode）は kit-1.2.0 以降の台本だけで使えます。"
                            "schema_version を kit-1.2.0 にしてください"]


# ------------------------------------------------------------------ 字幕の別表記

def test_subtitle_comment_belongs_to_the_paragraph_before_it():
    doc = sb.markdown_to_storyboard(_md("""一つ目の段落です。

二つ目の段落です。
<!-- subtitle: 2 つ目の段落です。 -->
<!-- ただのコメントは今までどおり捨てる -->

三つ目。

<!--
subtitle: 三つ目
（別表記）。
-->"""))
    intro = doc["intro"]
    assert intro["narration"] == "一つ目の段落です。\n二つ目の段落です。\n三つ目。"  # 原稿は変わらない
    assert intro["subtitles"] == [{"paragraph": 2, "text": "2 つ目の段落です。"},
                                  {"paragraph": 3, "text": "三つ目（別表記）。"}]
    assert "subtitles" not in doc["scenes"][0] and "subtitles" not in doc["outro"]
    assert _errors(doc) == []


def test_full_width_colon_and_scene():
    doc = sb.markdown_to_storyboard(_md().replace("```\n本文です。\n\n## outro",
                                                  "```\n本文です。\n<!-- subtitle：字幕です。 -->\n\n## outro"))
    assert doc["scenes"][0]["subtitles"] == [{"paragraph": 1, "text": "字幕です。"}]
    assert doc["scenes"][0]["narration"] == "本文です。"


@pytest.mark.parametrize("body, message", [
    ("<!-- subtitle: 前に段落が無い -->\n本文。", "前に段落がありません"),
    ("本文。\n<!-- subtitle:  -->", "中身が空"),
    ("本文。\n<!-- subtitle: a -->\n<!-- subtitle: b -->", "2 つあります"),
])
def test_subtitle_comment_errors(body, message):
    with pytest.raises(sb.ConversionError, match=message):
        sb.markdown_to_storyboard(_md(body))


def test_subtitles_in_yaml_and_comment_is_an_error():
    text = _md("本文。\n<!-- subtitle: 字幕。 -->").replace("summary: s\n```\n本文。",
                                                             "summary: s\nsubtitles: [{paragraph: 1, text: x}]\n```\n本文。", 1)
    with pytest.raises(sb.ConversionError, match="両方"):
        sb.markdown_to_storyboard(text)


def test_subtitle_paragraph_must_exist_and_be_unique():
    doc = sb.markdown_to_storyboard(_md("本文。"))
    doc["intro"]["subtitles"] = [{"paragraph": 3, "text": "x"}]
    assert _errors(doc) == ["[subtitles] intro: 段落 3 がありません（ナレーションの段落は 1）"]
    doc["intro"]["subtitles"] = [{"paragraph": 1, "text": "x"}, {"paragraph": 1, "text": "y"}]
    assert _errors(doc) == ["[subtitles] intro: 段落 1 の字幕の別表記が 2 つあります"]


def test_validate_file_reports_markdown_errors(tmp_path):
    path = tmp_path / "t.storyboard.md"
    path.write_text(_md("<!-- subtitle: x -->\n本文。"), encoding="utf-8")
    rep = sb.validate_file(path)
    assert len(rep.errors) == 1 and rep.errors[0].startswith("[markdown]") and "前に段落がありません" in rep.errors[0]


# ------------------------------------------------------------------ 固定尺の枠

@pytest.mark.parametrize("value, ok", [(12, True), (0.5, True), (600, True), (0, False), (-1, False), (601, False)])
def test_slot_sec_range(value, ok):
    doc = sb.markdown_to_storyboard(_md())
    doc["scenes"][0]["slot_sec"] = value
    errors = _errors(doc)
    assert (errors == []) is ok, errors
    if not ok:
        assert any("scenes/0/slot_sec" in e for e in errors)


def test_slot_sec_in_markdown_yaml():
    doc = sb.markdown_to_storyboard(_md().replace("summary: s\n```\n本文です。", "summary: s\nslot_sec: 8\n```\n本文です。", 1))
    assert doc["intro"]["slot_sec"] == 8 and _errors(doc) == []


def test_new_fields_need_kit_1_2_0():
    doc = sb.markdown_to_storyboard(_md("本文。\n<!-- subtitle: 字幕。 -->", version="kit-1.1.0"))
    doc["scenes"][0]["slot_sec"] = 12
    assert _errors(doc) == [
        "[version] intro: 字幕の別表記（subtitles）は kit-1.2.0 以降の台本だけで使えます。schema_version を kit-1.2.0 にしてください",
        "[version] scenes/0 (s01): 固定尺の枠（slot_sec）は kit-1.2.0 以降の台本だけで使えます。schema_version を kit-1.2.0 にしてください",
    ]
    doc["reel"]["schema_version"] = "kit-1.2.0"
    assert _errors(doc) == []
