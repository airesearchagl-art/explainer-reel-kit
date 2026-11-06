"""手順書・AGENTS.md・prompts・README の中のコマンドとリンクが、実在のものと合っていること。

- 文書の中の `erkit …`（コードブロックの行と、行内のコード）を抜き出し、erkit の引数の解析にそのまま通す
- 後で実装するサブコマンド（new・draft）を手順に書かない
- PowerShell で記号になる `<` `>` をコマンドに残さない（仮の文字は実際の値にする）
- サンプルのパス（samples/・examples/・src/）が実在する
- 相対リンクの先が実在する
"""
from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path

import pytest

from explainer_reel_kit.cli import main

from doc_commands import check_command, extract_commands

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted(
    [ROOT / "AGENTS.md", ROOT / "README.md"]
    + list((ROOT / "docs" / "guide").glob("*.md"))
    + list((ROOT / "prompts").glob("*.md"))
)
GUIDE_FILES = ["00-setup", "01-intake", "02-audience", "03-outline", "04-storyboard", "05-visuals",
               "06-review", "07-export", "confidentiality", "troubleshooting", "batch"]
PROMPT_FILES = ["01-intake", "02-outline", "03-storyboard", "04-diagram-html", "05-batch"]

ALL_COMMANDS = [(p, no, args) for p in DOCS for no, args in extract_commands(p)]


def _id(item) -> str:
    p, no, args = item
    return f"{p.relative_to(ROOT).as_posix()}:{no}:{args[:40]}"


def test_docs_exist():
    assert (ROOT / "AGENTS.md").is_file()
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    for name in GUIDE_FILES:
        assert (ROOT / "docs" / "guide" / f"{name}.md").is_file(), name
    for name in PROMPT_FILES:
        assert (ROOT / "prompts" / f"{name}.md").is_file(), name


def test_commands_are_found():
    """抜き出しが空振りしていない（主要なサブコマンドが手順に出てくる）。"""
    subs = {shlex.split(a)[0] for _, _, a in ALL_COMMANDS if a}
    assert {"doctor", "check", "diagram", "capture", "record", "voice", "make"} <= subs
    assert len(ALL_COMMANDS) >= 30


@pytest.mark.parametrize("item", ALL_COMMANDS, ids=_id)
def test_command_parses(item):
    path, no, args = item
    where = f"{path.relative_to(ROOT)}:{no}: erkit {args}"
    problems = check_command(args, where)
    assert not problems, "\n".join(problems)


LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_exist(path):
    text = path.read_text(encoding="utf-8")
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        rel = target.split("#", 1)[0]
        assert (path.parent / rel).exists(), f"{path.relative_to(ROOT)}: リンク先が無い {target}"


def test_agents_promises():
    """設計の 5.2・5.3 の約束が AGENTS.md に書いてある。"""
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for phrase in ("最初に区分を決める", "資料を読む前に", "資料を受け取らずに止まります",
                   "変えるのは**人だけ**", "所属先のルールに従います", "画面を捏造しない",
                   "座標を書かず", "erkit check` が通るまで直します"):
        assert phrase in text, phrase
    # 短く保つ（詳しくは手順書へ）
    assert len(text.splitlines()) <= 120


def test_prompts_ask_confidentiality_first():
    text = (ROOT / "prompts" / "01-intake.md").read_text(encoding="utf-8")
    first_q = text.index("社外秘")
    assert first_q < text.index("何を説明するか")
    assert "general に変えてよいのは私だけ" in text


def test_guide_separates_ai_and_human():
    for name in GUIDE_FILES[1:8]:
        text = (ROOT / "docs" / "guide" / f"{name}.md").read_text(encoding="utf-8")
        assert "## AI に任せること" in text, name


def test_copy_sample_flow(tmp_path, capsys):
    """04-storyboard の「自分の題材のフォルダを作る」の通りに写すと、検証と突き合わせが通り、CSS も見つかる。"""
    reels = tmp_path / "reels"
    reels.mkdir()
    shutil.copytree(ROOT / "samples" / "_shared", reels / "_shared")
    dest = reels / "glass-choice"
    shutil.copytree(ROOT / "samples" / "u-value", dest)
    sb = dest / "glass-choice.storyboard.md"
    (dest / "u-value.storyboard.md").rename(sb)
    act = dest / "glass-choice.actions.yaml"
    (dest / "u-value.actions.yaml").rename(act)
    sb.write_text(sb.read_text(encoding="utf-8").replace("id: u-value", "id: glass-choice", 1), encoding="utf-8")
    act.write_text(act.read_text(encoding="utf-8").replace("reel_id: u-value", "reel_id: glass-choice", 1),
                   encoding="utf-8")

    assert main(["check", "--strict", str(sb)]) == 0
    assert main(["capture", str(sb), "--check"]) == 0
    capsys.readouterr()
    for html in (dest / "diagrams").glob("*.html"):
        for href in re.findall(r'href="([^"]+\.css)"', html.read_text(encoding="utf-8")):
            assert (html.parent / href).resolve().is_file(), f"{html.name}: CSS が見つからない {href}"
