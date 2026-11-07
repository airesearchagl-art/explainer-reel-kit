"""台本の読み込み・スキーマ（kit-1.1.0）・互換・検証の独自チェック。"""
from __future__ import annotations

import pytest

from explainer_reel_kit import storyboard as sb
from conftest import COMPAT, EXAMPLE, TEMPLATE


def _errors(doc, base=None):
    return sb.validate_storyboard(doc, base_dir=base).errors


def test_example_passes_strict():
    rep = sb.validate_file(EXAMPLE)
    assert rep.errors == [] and rep.warnings == []


def test_template_passes():
    rep = sb.validate_file(TEMPLATE)
    assert rep.errors == []
    assert all("[scenes]" in w for w in rep.warnings)  # 2 シーンだけなので推奨数の警告だけ


def test_schema_is_packaged_data():
    schema = sb.load_schema()
    assert schema["$defs"]["reel"]["properties"]["schema_version"]["enum"] == ["1.0.0", "1.1.0", "kit-1.0.0", "kit-1.1.0"]
    assert "sketchup" not in schema["$defs"]["image"]["properties"]["source"]["enum"]
    assert "capture_sketchup" not in schema["$defs"]
    assert sb.recipe_names() == ["fade_sequence", "highlight_box", "arrow_move", "morph_transition", "text_build"]


def test_schema_has_no_source_repo_words():
    text = (sb.resources.files("explainer_reel_kit") / "data/schema/storyboard.schema.json").read_text(encoding="utf-8")
    for word in ("施" + "主", "Vault", "Walkthrough", "9876", "sketchup", "catalog"):  # 語は組み立てる（点検に当たらないように）
        assert word not in text


# ------------------------------------------------------------------ 互換（元の仕組みの一般の台本 2 本を写した例）

@pytest.mark.parametrize("path", COMPAT, ids=[p.name for p in COMPAT])
def test_compat_storyboards_pass(path):
    assert len(COMPAT) == 2
    rep = sb.validate_file(path)
    assert rep.errors == [], rep.errors


def test_compat_as_1_0_0_without_confidentiality(compat_docs, clone):
    doc = clone(compat_docs["compat-web"])
    doc["reel"]["schema_version"] = "1.0.0"
    del doc["reel"]["confidentiality"]
    rep = sb.validate_storyboard(doc)
    assert rep.errors == [] and rep.warnings == []  # 1.0.0 は区分なしで警告もない
    assert sb.confidentiality(doc) == sb.CONFIDENTIAL


def test_1_0_0_cannot_have_confidentiality(compat_docs, clone):
    doc = clone(compat_docs["compat-web"])
    doc["reel"]["schema_version"] = "1.0.0"
    assert any("schema_version" in e for e in _errors(doc))


def test_kit_only_fields_need_kit_version(example_doc, clone):
    doc = clone(example_doc)
    doc["reel"]["schema_version"] = "1.1.0"
    errs = _errors(doc)
    assert any(e.startswith("[version]") and "capture.src" in e for e in errs)
    assert any(e.startswith("[version]") and "tool = html" in e for e in errs)


def test_compat_storyboards_also_pass_as_kit_version(compat_docs, clone):
    for doc in compat_docs.values():
        d = clone(doc)
        d["reel"]["schema_version"] = "kit-1.0.0"
        assert _errors(d) == []


# ------------------------------------------------------------------ キットで使えないもの

def test_sketchup_source_is_rejected_with_reason(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"][0]["image"]["source"] = "sketchup"
    doc["scenes"][0]["capture"] = {"demo_script": "demo.rb", "scene": "s01", "port": 9876}
    errs = _errors(doc)
    assert any(e.startswith("[kit]") and "SketchUp" in e for e in errs)
    assert not any(e.startswith("[schema] scenes/0/image") or e.startswith("[schema] scenes/0/capture") for e in errs)


def test_catalog_kind_is_rejected_with_reason(example_doc, clone):
    doc = clone(example_doc)
    doc["reel"]["kind"] = "catalog"
    errs = _errors(doc)
    assert errs == ["[kit] reel.kind 'catalog': カタログ動画はキットに含まれません"]


# ------------------------------------------------------------------ generated（説明図）

def test_generated_html_requires_src(example_doc, clone):
    doc = clone(example_doc)
    del doc["scenes"][0]["capture"]["src"]
    assert any("scenes/0/capture" in e for e in _errors(doc))


def test_generated_needs_prompt_or_src(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"][3]["capture"] = {}
    assert any("scenes/3/capture" in e for e in _errors(doc))


def test_generated_src_must_be_html(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"][0]["capture"]["src"] = "diagrams/s01.png"
    assert any("scenes/0/capture/src" in e for e in _errors(doc))


# ------------------------------------------------------------------ 独自チェック

def test_unknown_recipe(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"][0]["recipe"] = "spin"
    errs = _errors(doc)
    assert any(e.startswith("[recipe]") for e in errs)
    assert not any("scenes/0/recipe" in e and e.startswith("[schema]") for e in errs)


def test_duplicate_and_reserved_ids(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"][1]["id"] = doc["scenes"][0]["id"]
    doc["scenes"][2]["id"] = "intro"
    errs = _errors(doc)
    assert any("重複" in e for e in errs) and any("予約名" in e for e in errs)


def test_no_scenes(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"] = []
    assert any(e.startswith("[scenes]") for e in _errors(doc))


def test_manual_image_must_exist(example_doc, clone, tmp_path):
    doc = clone(example_doc)
    doc["scenes"][0]["image"] = {"source": "manual", "ref": "img/s01.png", "label": "実キャプチャ"}
    doc["scenes"][0]["capture"] = {"instructions": "画面を用意する"}
    assert any(e.startswith("[image]") for e in _errors(doc, tmp_path))
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "s01.png").write_bytes(b"\x89PNG")
    assert _errors(doc, tmp_path) == []


def test_warnings(example_doc, clone):
    doc = clone(example_doc)
    doc["scenes"][0]["heading"] = "台本"  # 動詞で終わらない
    del doc["scenes"][2]["capture"]       # web に capture がない
    del doc["reel"]["confidentiality"]
    doc["scenes"] = doc["scenes"][:4]
    rep = sb.validate_storyboard(doc)
    tags = sorted(w.split("]")[0] + "]" for w in rep.warnings)
    assert rep.errors == []
    assert tags == ["[capture]", "[confidentiality]", "[heading]", "[scenes]"]


# ------------------------------------------------------------------ Markdown

def test_markdown_paragraphs_and_comments():
    text = """---
id: t
title: T
schema_version: kit-1.0.0
audience: A
kind: work_manual
aspect: "16:9"
output_name: t
---
# 説明（読み飛ばす）

## intro
```yaml
summary: S
```
一行目と
二行目。

<!-- 無視される -->
次の段落 ABC
DEF。

## s01: 画面を開く
```yaml
image: {source: generated, ref: a/b.png, label: 説明用再構成図}
recipe: fade_sequence
capture: {prompt: 図}
```
本文。

## outro
```yaml
summary: E
```
おわり。
"""
    doc = sb.markdown_to_storyboard(text)
    assert list(doc) == ["reel", "intro", "scenes", "outro"]
    assert doc["intro"]["narration"] == "一行目と二行目。\n次の段落 ABC DEF。"
    assert doc["scenes"][0]["heading"] == "画面を開く"
    assert sb.validate_storyboard(doc).errors == []


@pytest.mark.parametrize("text, msg", [
    ("no front matter", "front matter"),
    ("---\nid: x\naspect: 16:9\n---\n", "aspect"),
    ("---\nid: x\n---\n## s01\n```yaml\na: 1\n```\n", "シーン見出し"),
    ("---\nid: x\n---\n## intro\n本文だけ\n", "yaml ブロックがありません"),
    ("---\nid: x\n---\n## intro\n```yaml\na: 1\n", "閉じていません"),
    ("---\nid: x\n---\n## intro\n```yaml\na: 1\n```\n## intro\n```yaml\na: 1\n```\n", "重複"),
])
def test_markdown_errors(text, msg):
    with pytest.raises(sb.ConversionError, match=msg):
        sb.markdown_to_storyboard(text)


def test_validate_file_reports_markdown_and_json_errors(tmp_path):
    bad_md = tmp_path / "a.storyboard.md"
    bad_md.write_text("no front matter", encoding="utf-8")
    assert sb.validate_file(bad_md).errors[0].startswith("[markdown]")
    bad_json = tmp_path / "a.storyboard.json"
    bad_json.write_text("{", encoding="utf-8")
    assert sb.validate_file(bad_json).errors[0].startswith("[json]")


def test_bom_is_accepted(tmp_path):
    p = tmp_path / "bom.storyboard.md"
    p.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert sb.validate_file(p).errors == []
