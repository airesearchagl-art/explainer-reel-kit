"""erkit draft --update-marks: 操作定義の marks と説明図の data-mark から、mark の名前だけを入れる（LLM は使わない）。"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.llm.errors import ConfigError
from explainer_reel_kit.llm.marks import action_marks, html_marks, update_marks

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "u-value"


@pytest.fixture
def sample(tmp_path) -> Path:
    """サンプル題材の写しから、recipe_params の mark の行を消したもの。"""
    work = tmp_path / "u-value"
    shutil.copytree(SAMPLE, work, ignore=shutil.ignore_patterns("app"))
    md = work / "u-value.storyboard.md"
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"recipe_params:\n  mark: [^\n]+\n", "", text)
    md.write_text(text, encoding="utf-8")
    return md


def test_names_from_actions_and_html():
    actions = action_marks(SAMPLE / "u-value.actions.yaml")
    assert actions["s03"] == ["input_panel"] and actions["s04"] == ["glass_select", "u_row_lowe"]
    assert html_marks(SAMPLE / "diagrams" / "s01_heat_paths.html") == ["conduction", "convection", "radiation"]


def test_update_marks_restores_the_sample(sample):
    original = sb.load_storyboard(SAMPLE / "u-value.storyboard.md")
    before_text = sample.read_text(encoding="utf-8")
    result = update_marks(sample)
    assert result.updated["s01"] == ["conduction", "convection", "radiation"]
    assert result.updated["s03"] == ["input_panel"] and result.updated["s04"] == ["glass_select", "u_row_lowe"]
    doc = sb.load_storyboard(sample)
    for scene, want in zip(doc["scenes"], original["scenes"]):
        if scene["id"] in result.updated:
            got = scene["recipe_params"]["mark"]
            want_mark = want["recipe_params"]["mark"]
            assert (got if isinstance(got, list) else [got]) == (want_mark if isinstance(want_mark, list) else [want_mark])
    # 足しただけ: 元の行はすべて同じ順で残る
    after = sample.read_text(encoding="utf-8").split("\n")
    it = iter(after)
    assert all(line in it for line in before_text.split("\n"))
    assert all(line.strip().startswith(("recipe_params:", "mark:")) for line in after if line not in before_text.split("\n"))
    assert sb.validate_storyboard(doc, base_dir=sample.parent).errors == []


def test_existing_marks_are_left_alone(sample):
    update_marks(sample)
    text = sample.read_text(encoding="utf-8")
    again = update_marks(sample)
    assert again.updated == {} and sample.read_text(encoding="utf-8") == text
    assert "既にある" in again.skipped["s01"]


def test_without_actions_web_scenes_are_skipped(sample):
    (sample.parent / "u-value.actions.yaml").unlink()
    result = update_marks(sample)
    assert "s01" in result.updated and result.skipped["s03"] == "操作定義がない"


def test_bad_actions_file(sample, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: other\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="schema"):
        update_marks(sample, bad)


def test_draft_then_update_marks_from_the_cli(fake_llm, draft_config, dummy_source, good_answer, tmp_path, capsys):
    fake_llm.reply = lambda body: json.dumps(good_answer, ensure_ascii=False)
    out = tmp_path / "reels" / "dummy-tool"
    assert erkit(["draft", "dummy-tool", "--source", str(dummy_source), "--llm-config", str(draft_config),
                  "--out", str(out)]) == 0
    md = out / "dummy-tool.storyboard.md"
    # 人が s02 の説明図を HTML で書き、capture に tool: html と src を足す
    (out / "diagrams").mkdir()
    (out / "diagrams" / "s02.html").write_text('<div data-mark="file_button">ファイルを選ぶ</div>'
                                               '<p data-mark="row_limit">5000 行</p>', encoding="utf-8")
    text = md.read_text(encoding="utf-8")
    text = text.replace("capture:\n  prompt: 左の欄とファイルを選ぶボタンを描く",
                        "capture:\n  prompt: 左の欄とファイルを選ぶボタンを描く\n  tool: html\n  src: diagrams/s02.html")
    md.write_text(text, encoding="utf-8")
    capsys.readouterr()
    posts_before = len(fake_llm.requests)
    assert erkit(["draft", "dummy-tool", "--update-marks", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "s02: mark を入れました: file_button, row_limit" in printed and f"OK {md}" in printed
    assert "s01: そのまま（説明図の HTML がまだない" in printed
    assert len(fake_llm.requests) == posts_before  # LLM は使わない
    assert sb.load_storyboard(md)["scenes"][1]["recipe_params"] == {"mark": ["file_button", "row_limit"]}
    record = json.loads((out / "draft.json").read_text(encoding="utf-8"))
    assert record["marks_updates"][0]["updated"] == {"s02": ["file_button", "row_limit"]}
