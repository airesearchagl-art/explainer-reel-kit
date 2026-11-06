"""Claude Code のプラグイン（plugins/claude-code）とマーケットプレイス（.claude-plugin/marketplace.json）。

- plugin.json・marketplace.json が JSON として正しく、必須の項目がある（形式は Claude Code の公式文書の
  Plugin manifest reference・Marketplace reference に合わせる）
- プラグインの版 ＝ pyproject の版 ＝ スキル・コマンドに書いた版
- スキル（skills/<名前>/SKILL.md）とコマンド（commands/*.md）の frontmatter に必須の項目がある
- スキル・コマンドの中の `erkit …` が実在のサブコマンドと引数に合う（test_guide と同じ照合）
- スキル・コマンドが指すキットのファイル（docs/・samples/ など）が実在する
- フック（hooks）を使わない
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from explainer_reel_kit import __version__
from explainer_reel_kit.cli import main

from doc_commands import check_command, extract_commands

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "claude-code"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
MARKET = ROOT / ".claude-plugin" / "marketplace.json"
SKILLS = ["make-explainer", "storyboard", "diagram", "web-capture"]
COMMANDS = ["explainer-new", "explainer-check", "explainer-make"]
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED_MARKETS = {"claude-code-marketplace", "claude-code-plugins", "claude-plugins-official",
                    "anthropic-marketplace", "anthropic-plugins", "agent-skills", "inline", "builtin",
                    "skills-dir", "synced", "npm", "pip", "uv", "cargo", "github", "gh"}

SKILL_FILES = [PLUGIN / "skills" / s / "SKILL.md" for s in SKILLS]
COMMAND_FILES = [PLUGIN / "commands" / f"{c}.md" for c in COMMANDS]
PLUGIN_DOCS = SKILL_FILES + COMMAND_FILES + [PLUGIN / "README.md"]


def _frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: 1 行目が --- でない（frontmatter が読まれない）"
    head, body = text[4:].split("\n---\n", 1)
    data = yaml.safe_load(head)
    assert isinstance(data, dict), path
    return data, body


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib:
        return tomllib.loads(text)["project"]["version"]
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


# ---- plugin.json・marketplace.json

def test_manifest_json():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["name"] == "explainer-reel-kit"
    assert KEBAB.match(data["name"])
    for key in ("version", "description", "author", "license"):
        assert data.get(key), key
    assert data["author"].get("name")
    assert data["license"] == "MIT"
    assert data["homepage"].startswith("https://")
    for forbidden in ("hooks", "mcpServers", "commands", "skills"):  # 既定の置き場所だけを使う
        assert forbidden not in data, forbidden


def test_marketplace_json():
    data = json.loads(MARKET.read_text(encoding="utf-8"))
    for key in ("name", "owner", "plugins"):
        assert key in data, key
    assert data["owner"].get("name")
    name = data["name"]
    assert KEBAB.match(name) and name not in RESERVED_MARKETS and not name.startswith("claudeai-")
    assert data.get("description")
    (entry,) = data["plugins"]
    assert entry["name"] == "explainer-reel-kit"
    src = entry["source"]
    assert src.startswith("./") and ".." not in src and "\\" not in src
    assert (ROOT / src / ".claude-plugin" / "plugin.json") == MANIFEST
    assert "version" not in entry  # 版は plugin.json だけに書く（両方あると validate が警告）
    assert "hooks" not in entry


def test_versions_match():
    plugin_version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    assert plugin_version == _pyproject_version() == __version__
    # スキル・コマンドに書いた「このプラグインの版」も同じ
    for path in SKILL_FILES[:1] + COMMAND_FILES:
        found = re.findall(r"このプラグインの版[はが]?\s*\*\*([0-9.]+)\*\*", path.read_text(encoding="utf-8"))
        assert found, f"{path.name}: 版の確かめが無い"
        assert set(found) == {plugin_version}, path.name


def test_install_commands_in_docs_match_names():
    market = json.loads(MARKET.read_text(encoding="utf-8"))["name"]
    plugin = json.loads(MANIFEST.read_text(encoding="utf-8"))["name"]
    want_add = "/plugin marketplace add airesearchagl-art/explainer-reel-kit"
    want_install = f"/plugin install {plugin}@{market}"
    for path in (PLUGIN / "README.md", ROOT / "README.md", ROOT / "docs" / "guide" / "00-setup.md"):
        text = path.read_text(encoding="utf-8")
        assert want_add in text and want_install in text, path


# ---- スキル・コマンド

@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_frontmatter(path):
    data, body = _frontmatter(path)
    assert data.get("name") == path.parent.name
    assert KEBAB.match(data["name"]) and len(data["name"]) <= 64
    desc = data.get("description")
    assert isinstance(desc, str) and 20 <= len(desc) <= 1024
    assert "<" not in desc and ">" not in desc
    assert "hooks" not in data
    assert len(body.splitlines()) < 500


@pytest.mark.parametrize("path", COMMAND_FILES, ids=lambda p: p.stem)
def test_command_frontmatter(path):
    data, body = _frontmatter(path)
    assert isinstance(data.get("description"), str) and data["description"]
    assert "name" not in data  # コマンドのファイルでは name は使わない（ファイル名が名前）
    assert data.get("disable-model-invocation") is True  # 人が呼んだときだけ動く
    assert "hooks" not in data
    assert "$ARGUMENTS" in body


def test_no_hooks():
    assert not (PLUGIN / "hooks").exists()
    for path in PLUGIN_DOCS:
        assert "hooks.json" not in path.read_text(encoding="utf-8")


def test_skill_layout_is_complete():
    found_skills = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))
    assert found_skills == sorted(SKILLS)
    found_cmds = sorted(p.stem for p in (PLUGIN / "commands").glob("*.md"))
    assert found_cmds == sorted(COMMANDS)


PLUGIN_COMMANDS = [(p, no, a) for p in PLUGIN_DOCS for no, a in extract_commands(p)]


def test_plugin_commands_found():
    subs = {shlex.split(a)[0] for _, _, a in PLUGIN_COMMANDS}
    assert {"--version", "doctor", "check", "diagram", "capture", "record", "make"} <= subs


@pytest.mark.parametrize("item", PLUGIN_COMMANDS,
                         ids=lambda it: f"{it[0].relative_to(ROOT).as_posix()}:{it[1]}:{it[2][:30]}")
def test_plugin_command_parses(item):
    path, no, args = item
    problems = check_command(args, f"{path.relative_to(ROOT)}:{no}: erkit {args}")
    assert not problems, "\n".join(problems)


KIT_PATH = re.compile(r"`((?:docs|samples|prompts|src|config|dictionaries)/[^`\s]+|AGENTS\.md)`")


@pytest.mark.parametrize("path", PLUGIN_DOCS, ids=lambda p: p.relative_to(PLUGIN).as_posix())
def test_referenced_kit_files_exist(path):
    """スキルが「読む」と言うキットのファイルが実在する（キットのフォルダが作業のフォルダ）。"""
    for ref in KIT_PATH.findall(path.read_text(encoding="utf-8")):
        if "<" in ref or ref.startswith("reels/"):
            continue
        assert (ROOT / ref.rstrip("/")).exists(), f"{path.name}: 無いファイル {ref}"


@pytest.mark.parametrize("path", PLUGIN_DOCS, ids=lambda p: p.relative_to(PLUGIN).as_posix())
def test_relative_links_exist(path):
    for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        assert (path.parent / target.split("#", 1)[0]).exists(), f"{path.name}: リンク先が無い {target}"


def test_confidentiality_first_and_stop():
    """区分を最初に聞き、confidential なら資料を受け取らずに止まる（AGENTS.md §2 と同じ）。"""
    for path in (SKILL_FILES[0], COMMAND_FILES[0]):
        text = path.read_text(encoding="utf-8")
        assert "資料を受け取らない" in text or "資料を受け取らずに止まる" in text, path.name
        assert "クラウド" in text, path.name
    text = SKILL_FILES[0].read_text(encoding="utf-8")
    assert text.index("最初に区分を決める") < text.index("段ごとの進め方")
    assert "下げない" in text


def test_explainer_new_flow(tmp_path, capsys):
    """/explainer-new の 4 の手順どおりに作ると、erkit check が通る（警告はシーン数だけ）。"""
    root = tmp_path
    shutil.copytree(ROOT / "samples" / "_shared", root / "reels" / "_shared")
    dest = root / "reels" / "glass-choice"
    (dest / "diagrams").mkdir(parents=True)
    sb = dest / "glass-choice.storyboard.md"
    text = (ROOT / "src" / "explainer_reel_kit" / "data" / "templates" / "storyboard.md").read_text(encoding="utf-8")
    text = re.sub(r"^id: \S+", "id: glass-choice", text, count=1, flags=re.M)
    text = re.sub(r"^output_name: \S+", "output_name: glass_choice", text, count=1, flags=re.M)
    text = re.sub(r"^kind: \S+", "kind: tool_intro", text, count=1, flags=re.M)
    text = re.sub(r"^confidentiality: \S+", "confidentiality: general", text, count=1, flags=re.M)
    sb.write_text(text, encoding="utf-8")

    assert main(["check", str(sb)]) == 0
    out = capsys.readouterr().out
    assert "区分: general" in out
    assert "シーン数" in out
    assert main(["check", "--strict", str(sb)]) == 1  # ひな形のままでは警告（シーン数）が残る


def test_reels_is_ignored():
    """利用者の作業のフォルダ reels/ を git が無視する（社外秘の台本をうっかり commit しない）。"""
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "reels/" in lines
    if shutil.which("git") and (ROOT / ".git").exists():
        import subprocess
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", "reels/glass-choice/x.storyboard.md"],
                           cwd=ROOT, capture_output=True)
        assert r.returncode == 0, "reels/ の中のファイルが無視されていない"


SLASH_REF = re.compile(r"(?<![\w./@-])/explainer[\w:-]*")


def test_slash_command_refs_use_plugin_prefix():
    """文書の中の `/explainer…` は実際に打つ形（`/explainer-reel-kit:<コマンドかスキルの名前>`）で、実在するものを指す。
    （プラグインのコマンド・スキルは名前の前にプラグインの名前が付く。Skills の文書の Command-name の表）"""
    plugin = json.loads(MANIFEST.read_text(encoding="utf-8"))["name"]
    names = set(COMMANDS) | set(SKILLS)
    docs = sorted({ROOT / "AGENTS.md", ROOT / "README.md", *PLUGIN_DOCS,
                   *(ROOT / "docs" / "guide").glob("*.md"), *(ROOT / "prompts").glob("*.md")})
    seen = set()
    for path in docs:
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for ref in SLASH_REF.findall(line):
                where = f"{path.relative_to(ROOT)}:{no}: {ref}"
                if ref == f"/{plugin}":  # 「/explainer-reel-kit と打つと候補に出る」
                    continue
                assert ref.startswith(f"/{plugin}:"), f"プラグインの名前が付いていない: {where}"
                name = ref.split(":", 1)[1]
                assert name in names, f"無いコマンド・スキル: {where}"
                seen.add(name)
    assert set(COMMANDS) <= seen  # 3 つのコマンドがどれも正式な名前で案内されている
