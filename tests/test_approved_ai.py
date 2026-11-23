"""社内で認められた AI の許可リスト（config/approved_ai.yaml）の読み込み・検証、erkit doctor の表示、決まりの文書。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from explainer_reel_kit import approved_ai as aa
from explainer_reel_kit import doctor

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config" / "approved_ai.example.yaml"

COPILOT = {"id": "github-copilot", "name": "GitHub Copilot（エージェント）", "kind": "agent",
           "approved_on": "2026-01-15", "basis": "生成 AI 利用規程（例）", "allows": ["confidential"],
           "notes": "決まりは .github/copilot-instructions.md"}
M365 = {"id": "m365-copilot", "name": "Microsoft 365 Copilot（チャット）", "kind": "chat",
        "approved_on": "2026-01-15", "basis": "生成 AI 利用規程（例）", "allows": ["confidential"]}


def write(tmp_path: Path, data, name="approved_ai.yaml") -> Path:
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# ------------------------------------------------------------------ 読み込み

def test_missing_file_is_empty(tmp_path):
    lst = aa.load(tmp_path / "none.yaml")
    assert lst.entries == {} and not lst.exists and not lst.agent_allowed("github-copilot")


@pytest.mark.parametrize("text", ["", "version: 1\n", "version: 1\napproved: []\n", "# コメントだけ\n"])
def test_empty_list_is_valid_and_allows_nobody(tmp_path, text):
    lst = aa.load(write(tmp_path, text))
    assert lst.entries == {} and lst.exists and not lst.agent_allowed("github-copilot")


def test_example_is_valid_and_empty():
    """ひな形は有効な項目が空（例はコメントだけ）。写したままなら今までと同じ決まり。"""
    lst = aa.load(EXAMPLE)
    assert lst.entries == {}
    text = EXAMPLE.read_text(encoding="utf-8")
    assert "#   - id: github-copilot" in text and "#   - id: m365-copilot" in text
    # 例のコメントを外すと、正しい 2 項目になる
    lines = text.splitlines()
    start = lines.index("# approved:")
    end = lines.index("version: 1")
    data = yaml.safe_load("version: 1\n" + "\n".join(line[2:] for line in lines[start:end]))
    assert [i["id"] for i in data["approved"]] == ["github-copilot", "m365-copilot"]
    assert aa.validate(data) == []


def test_valid_list(tmp_path):
    lst = aa.load(write(tmp_path, {"version": 1, "approved": [COPILOT, M365]}))
    assert lst.ids() == ["github-copilot", "m365-copilot"]
    copilot = lst.get("github-copilot")
    assert copilot.kind == "agent" and copilot.approved_on == "2026-01-15" and copilot.allows_confidential()
    assert lst.agent_allowed("github-copilot")
    assert not lst.agent_allowed("m365-copilot")  # chat はエージェントとしては扱えない
    assert not lst.agent_allowed("claude-code")


def test_yaml_dates_are_read(tmp_path):
    text = ("version: 1\napproved:\n  - id: github-copilot\n    name: GitHub Copilot\n    kind: agent\n"
            "    approved_on: 2026-01-15\n    basis: 規程（例）\n    allows: [confidential]\n")
    assert aa.load(write(tmp_path, text)).get("github-copilot").approved_on == "2026-01-15"


@pytest.mark.parametrize("item, message", [
    (dict(COPILOT, kind="bot"), "kind は chat / agent"),
    (dict(COPILOT, kind=None), "kind は chat / agent"),
    (dict(COPILOT, approved_on="2026/01/15"), "approved_on は YYYY-MM-DD"),
    (dict(COPILOT, approved_on="2026-13-40"), "日付になっていません"),
    (dict(COPILOT, approved_on="未定"), "approved_on は YYYY-MM-DD"),
    (dict(COPILOT, id="GitHub Copilot"), "id は英小文字"),
    (dict(COPILOT, allows=["general"]), "allows は"),
    (dict(COPILOT, allows=[]), "allows は"),
    (dict(COPILOT, basis=""), "basis を書いて"),
    (dict(COPILOT, name="  "), "name を書いて"),
    (dict(COPILOT, notes=3), "notes は文字列"),
    (dict(COPILOT, confidentiality="general"), "知らない項目 confidentiality"),
])
def test_invalid_items(tmp_path, item, message):
    with pytest.raises(aa.ApprovedAIError) as info:
        aa.load(write(tmp_path, {"version": 1, "approved": [item]}))
    assert any(message in p for p in info.value.problems), info.value.problems


def test_duplicate_id(tmp_path):
    with pytest.raises(aa.ApprovedAIError) as info:
        aa.load(write(tmp_path, {"version": 1, "approved": [COPILOT, dict(COPILOT, name="もう 1 つ")]}))
    assert info.value.problems == ["approved[1]（github-copilot）: id が重複しています"]


@pytest.mark.parametrize("text, message", [
    ("- id: x\n", "最上位は"),
    ("version: 2\napproved: []\n", "version は 1"),
    ("version: 1\napproved: github-copilot\n", "approved は項目のリスト"),
    ("version: 1\napproved: [x]\n", "オブジェクト"),
    ("version: 1\nallowed: []\n", "知らない項目 allowed"),
    ("version: 1\napproved: [\n", "読めません"),
])
def test_invalid_files(tmp_path, text, message):
    with pytest.raises(aa.ApprovedAIError) as info:
        aa.load(write(tmp_path, text))
    assert any(message in p for p in info.value.problems), info.value.problems


def test_search_order(tmp_path):
    env_file = write(tmp_path, {"version": 1, "approved": [COPILOT]}, "env.yaml")
    work = tmp_path / "work"
    (work / "config").mkdir(parents=True)
    write(work / "config", {"version": 1, "approved": [M365]})
    assert aa.load(env={"ERKIT_APPROVED_AI": str(env_file)}, cwd=work).ids() == ["github-copilot"]
    assert aa.load(env={}, cwd=work).ids() == ["m365-copilot"]
    assert aa.load(env_file, env={}, cwd=work).ids() == ["github-copilot"]
    assert aa.find_config(None, {}, tmp_path / "empty") == aa.KIT_ROOT / "config" / "approved_ai.yaml"


# ------------------------------------------------------------------ erkit doctor

def _doctor(tmp_path, capsys, monkeypatch, *extra):
    from reel_helpers import FakeEngine

    monkeypatch.setattr(doctor, "check_ffmpeg", lambda: doctor.CheckResult("ffmpeg", "ffmpeg", doctor.OK, "fake"))
    cfg = tmp_path / "kit.yaml"
    cfg.write_text(f"output_root: {json.dumps(str(tmp_path / 'out'))}\n", encoding="utf-8")
    code = doctor.main(["--config", str(cfg), "--skip-browser", "--skip-llm", *extra], transport=FakeEngine(),
                       platform="linux")
    return code, capsys.readouterr().out


def test_doctor_shows_listed_ai(tmp_path, capsys, monkeypatch):
    path = write(tmp_path, {"version": 1, "approved": [COPILOT, M365]})
    code, out = _doctor(tmp_path, capsys, monkeypatch, "--approved-ai", str(path))
    assert code == 0 and "そろっています" in out
    line = next(l for l in out.splitlines() if "社内で認められた AI（許可リスト）" in l)
    assert line.startswith("OK") and "2 件" in line
    assert "GitHub Copilot（エージェント）（github-copilot、agent）" in line and "m365-copilot、chat" in line


@pytest.mark.parametrize("text", [None, "version: 1\napproved: []\n"])
def test_doctor_empty_or_missing_is_ok(tmp_path, capsys, monkeypatch, text):
    path = tmp_path / "approved_ai.yaml" if text is None else write(tmp_path, text)
    code, out = _doctor(tmp_path, capsys, monkeypatch, "--approved-ai", str(path))
    line = next(l for l in out.splitlines() if "社内で認められた AI" in l)
    assert code == 0 and line.startswith("OK") and "この PC の中で動く AI だけ" in line
    assert ("ファイル無し" in line) == (text is None)


def test_doctor_invalid_list_fails(tmp_path, capsys, monkeypatch):
    path = write(tmp_path, {"version": 1, "approved": [dict(COPILOT, kind="bot"), dict(M365, approved_on="昨日")]})
    code, out = _doctor(tmp_path, capsys, monkeypatch, "--approved-ai", str(path))
    assert code == 1 and "足りないもの 1 件" in out
    line = next(l for l in out.splitlines() if "社内で認められた AI" in l)
    assert line.startswith("NG") and "kind は chat / agent" in line and "approved_on は YYYY-MM-DD" in line
    assert "書くのは人だけ" in out


def test_doctor_json_has_the_row(tmp_path, capsys, monkeypatch):
    path = write(tmp_path, {"version": 1, "approved": [COPILOT]})
    code, out = _doctor(tmp_path, capsys, monkeypatch, "--approved-ai", str(path), "--json")
    row = next(c for c in json.loads(out)["checks"] if c["key"] == "approved_ai")
    assert code == 0 and row["status"] == "ok" and "github-copilot" in row["detail"]


def test_make_does_not_read_the_list():
    """erkit make の確認（run_checks）には入れない。区分の確かめは許可リストで変わらない。"""
    import inspect

    assert "approved" not in inspect.getsource(doctor.run_checks)
    for module in ("capture", "diagram", "narration", "reel", "deck"):
        for path in (ROOT / "src" / "explainer_reel_kit" / module).rglob("*.py"):
            assert "approved_ai" not in path.read_text(encoding="utf-8"), path


# ------------------------------------------------------------------ 決まりの文書

def test_gitignore_keeps_reels_and_the_list_out():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [l.strip() for l in text.splitlines()]
    assert "reels/" in lines and "config/*.yaml" in lines and "!config/*.example.yaml" in lines
    comment = text[:text.index("\nreels/")]
    assert "公開のキットに台本を入れない" in comment and "非公開リポジトリ" in comment


def test_install_copies_every_example():
    text = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert '-Filter "*.example.yaml"' in text


def test_agents_and_copilot_rules_agree():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    copilot = (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    # 同じ許可リスト・同じ条件・同じ id
    for text in (agents, copilot):
        assert "config/approved_ai.yaml" in text and "`kind`" in text and "`allows`" in text
        assert "`agent`" in text and "`confidential`" in text and "github-copilot" in text
        assert "書き換えない" in text or "書き換えません" in text
        assert "人だけ" in text
    assert "資料を受け取らずに止まります" in agents and "止まって" in copilot
    assert "AGENTS.md" in copilot and "あなたの id は `github-copilot`" in copilot
    assert "公開のリポジトリへ push しない" in copilot and "公開のリポジトリ" in agents
    # ひな形のままなら Copilot は載っていない（= 止まる）
    assert not aa.load(EXAMPLE).agent_allowed("github-copilot")


def test_copilot_guide_covers_the_steps():
    text = (ROOT / "docs" / "guide" / "copilot.md").read_text(encoding="utf-8")
    for phrase in ("非公開", "フォーク", "Import repository", "git remote set-url --push upstream no-push",
                   "git fetch upstream", "install.ps1 -SkipBrowser", "段 1", "段 2", "Agent", "approved_ai.yaml",
                   "何が PC の外に出るか", "ffmpeg", "AivisSpeech", "PowerPoint", "ライセンス"):
        assert phrase in text, phrase
    # 外に出るのは「Copilot が読んだもの」（自分で開いたファイル・ターミナルの出力も）。資料は確かめるまでワークスペースに置かない
    assert "人が Copilot に見せたものだけ" not in text
    for phrase in ("Copilot が読んだもの", "Copilot が自分で開いたファイル", "ターミナルの出力",
                   "ワークスペースの中に置きません"):
        assert phrase in text, phrase
    rules = (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "ワークスペースの中にあるファイルでも" in rules and "許可リストを確かめるまで開かない" in rules
    readme = (ROOT / "docs" / "guide" / "README.md").read_text(encoding="utf-8")
    assert "[copilot.md](copilot.md)" in readme
