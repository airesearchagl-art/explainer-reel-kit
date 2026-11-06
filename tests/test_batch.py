"""まとめて進める使い方（docs/guide/batch.md・prompts/05-batch.md・プラグインの分岐）と、出典の決まり。

- まとめて進めるときも、区分で止まる文言と、MP4 の前に人が確かめる文言がある
- 答えのひな形の 1 行目が区分で、ほかの欄もそろっている
- 出典の決まり（そのセッションで確かめたものだけ・記憶で書かない・未確認として報告）が、
  手順書 04・storyboard スキル・prompts の台本の指示文にある
- 文書の中の `erkit …` と `/explainer-reel-kit:…` の照合は test_guide・test_plugin が新しい頁も含めて行う
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from doc_commands import check_command, extract_commands

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guide"
PLUGIN = ROOT / "plugins" / "claude-code"
BATCH = GUIDE / "batch.md"
BATCH_PROMPT = ROOT / "prompts" / "05-batch.md"
SKILL = PLUGIN / "skills" / "make-explainer" / "SKILL.md"
NEW_CMD = PLUGIN / "commands" / "explainer-new.md"
MAKE_CMD = PLUGIN / "commands" / "explainer-make.md"

BATCH_DOCS = [BATCH, BATCH_PROMPT, SKILL, NEW_CMD]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _batch_part(path: Path) -> str:
    """まとめて進める分岐の部分（文書全体がその使い方なら全体）。"""
    text = _read(path)
    if path == SKILL:
        return text[text.index("## 進め方を選ぶ"):text.index("## 段ごとの進め方")]
    if path == NEW_CMD:
        return text[text.index("**まとめて進めるとき**"):text.index("**段ごとのとき**")]
    return text


@pytest.mark.parametrize("path", BATCH_DOCS, ids=lambda p: p.name if p.name != "SKILL.md" else "make-explainer")
def test_batch_stops_on_confidentiality(path):
    part = _batch_part(path)
    assert "区分" in part
    assert re.search(r"confidential", part), path.name
    assert re.search(r"止ま", part), f"{path.name}: 区分で止まる文言が無い"
    assert "分からない" in part or path == NEW_CMD  # /explainer-new は 2 の区分の確かめを引き継ぐ
    if path == NEW_CMD:
        step2 = _read(NEW_CMD)
        step2 = step2[step2.index("## 2. 区分を聞く"):step2.index("## 3.")]
        assert "ひな形" in step2 and "止まる" in step2  # 貼られたひな形の区分の行も先に読む


@pytest.mark.parametrize("path", BATCH_DOCS, ids=lambda p: p.name if p.name != "SKILL.md" else "make-explainer")
def test_batch_keeps_human_check_before_mp4(path):
    part = _batch_part(path)
    assert "--dry-run" in part, f"{path.name}: dry-run までで止まることが書いていない"
    assert re.search(r"MP4", part), path.name
    assert re.search(r"(作らない|実行しない|よいと言ってから|よいと言っ|決めないで)", part), \
        f"{path.name}: MP4 の前の人の確認の文言が無い"


def test_explainer_make_never_skips_confirmation():
    text = _read(MAKE_CMD)
    assert "まとめて進めてきたときも、この確かめは省かない" in text
    assert "よいと言われるまで実行しない" in text


def test_batch_doc_promises():
    text = _read(BATCH)
    head = text[text.index("## 変わらない約束"):text.index("## 答えのひな形")]
    for phrase in ("区分を最初に決める", "ほかの欄も資料も読まずに止まります", "区分を下げるのは人だけ",
                   "MP4 を作る前に、人が確かめる"):
        assert phrase in head, phrase


def test_answer_template_fields():
    text = _read(BATCH)
    block = text[text.index("## 説明動画の答え"):]
    block = block[:block.index("```")]
    items = [ln[2:].split(":", 1)[0].strip() for ln in block.splitlines() if ln.startswith("- ")]
    assert items[0] == "区分"  # 区分がいちばん上
    for field in ("何を説明するか（1 文）", "種別", "題材の id", "見る人と、もう知っていること",
                  "見終わったらできること", "資料と根拠", "撮影", "長さ"):
        assert field in items, field


def test_report_format_sections():
    text = _read(BATCH)
    report = text[text.index("## 報告の形"):text.index("## 使い方")]
    for h in ("### 構成", "### 決めたこと", "### 根拠が弱い・未確認の数値と事実", "### 確認画像",
              "### 通したコマンドと結果", "### 次に人がすること"):
        assert h in report, h
    prompt = _read(BATCH_PROMPT)
    for h in ("### 構成", "### 決めたこと", "### 根拠が弱い・未確認の数値と事実", "### 次に人がすること"):
        assert h in prompt, h


def test_batch_is_linked():
    assert "batch.md" in _read(GUIDE / "README.md")
    assert "batch.md" in _read(ROOT / "README.md")
    assert "05-batch.md" in _read(ROOT / "prompts" / "README.md")
    assert "docs/guide/batch.md" in _read(SKILL)
    assert "batch.md" not in _read(GUIDE / "00-setup.md")  # 置き場所は 00-setup 以外


SOURCE_RULE_FILES = [GUIDE / "04-storyboard.md", PLUGIN / "skills" / "storyboard" / "SKILL.md",
                     ROOT / "prompts" / "03-storyboard.md", BATCH_PROMPT]


@pytest.mark.parametrize("path", SOURCE_RULE_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_source_rule(path):
    text = _read(path)
    assert "出典の決まり" in text, path
    assert "記憶で書かない" in text or "記憶で書きません" in text, path
    assert "未確認" in text, path
    assert re.search(r"(そのセッションで|この会話で|貼られた資料で)確かめた", text), path


@pytest.mark.parametrize("path", [BATCH, BATCH_PROMPT], ids=lambda p: p.name)
def test_new_docs_commands_parse(path):
    """新しい頁の erkit のコマンドが実在の引数に合う（test_guide と同じ照合。ここでも件数を確かめる）。"""
    found = extract_commands(path)
    assert {a.split()[0] for _, a in found} >= {"check", "diagram", "make"}
    for no, args in found:
        problems = check_command(args, f"{path.relative_to(ROOT)}:{no}: erkit {args}")
        assert not problems, "\n".join(problems)
