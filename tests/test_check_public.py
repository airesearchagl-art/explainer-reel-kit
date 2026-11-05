"""公開前の点検（tools/check_public.py）。当たる例は実行時に組み立て、このファイル自体は点検に当たらない。"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_public", ROOT / "tools" / "check_public.py")
cp = importlib.util.module_from_spec(_spec)
sys.modules["check_public"] = cp
_spec.loader.exec_module(cp)

AT = "@"
# 当たる例（番号, 1 行）。語・記号を分けて書き、ここでは組み立てるだけにする
HITS = [
    ("1", "page " + "0123456789abcdef" * 2),
    ("1", "id 12345678-" + "1234-1234-1234-" + "123456789abc"),
    ("1", "https://www." + "notion" + ".so/x"),
    ("2", "mail me: someone" + AT + "example.com"),
    ("3", "out " + "G" + ":\\videos\\x"),
    ("3", "out " + "/Us" + "ers/me/x"),
    ("5", "https://" + "youtu" + ".be/abc"),
    ("5", "https://x." + "vercel" + ".app/"),
    ("6", "port " + "98" + "77"),
    ("6", "see " + "A-M" + "1-02"),
    ("7", "NOTION" + "_TOKEN=x"),
    ("7", "api" + "_key: abc"),
    ("8", "key " + "sk-" + "a" * 24),
    ("9", "施" + "主に見せる"),
]
CLEAN = [
    "https://github.com/someone/repo",
    "hash " + "0123456789abcdef" * 4,              # 64 桁（sha256）は ID に数えない
    "Co-Authored-By: Bot <" + "noreply" + AT + "example.com>",
    "x <1+someone" + AT + "users.noreply.github.com>",
    "api_key_env: MY_KEY",
    "http://127.0.0.1:8000/",
    "ratio 1:2 and time 10:30",
    "port 9876",
]


def _scan(tmp_path, lines, deny=None, allow=None, name="a.md"):
    (tmp_path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if allow:
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / cp.ALLOW_FILE).write_text(allow, encoding="utf-8")
    files = cp.list_files(tmp_path, use_git=False)
    return cp.scan(tmp_path, files, deny, cp.load_allow(tmp_path))


@pytest.mark.parametrize("rule, line", HITS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(HITS)])
def test_hits(tmp_path, rule, line):
    hits = _scan(tmp_path, [line])
    assert [h.rule.split()[0] for h in hits] == [rule], hits


@pytest.mark.parametrize("line", CLEAN)
def test_clean(tmp_path, line):
    assert _scan(tmp_path, [line]) == []


def test_big_files_and_binary(tmp_path):
    (tmp_path / "v.mp4").write_bytes(b"x")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\0\0" + ("notion" + ".so").encode())
    hits = cp.scan(tmp_path, cp.list_files(tmp_path, use_git=False), None, [])
    assert [h.path for h in hits] == ["v.mp4"]


def test_deny_words_from_env_and_file(tmp_path):
    word = "Zq" + "xwv"
    deny, sources = cp.load_deny(tmp_path, {"KIT_DENY_WORDS": word + "|Other"})
    hits = _scan(tmp_path, [f"made by {word.lower()}"], deny=deny)
    assert [h.rule for h in hits] == ["4 持ち主の語"] and word not in hits[0].text
    assert sources == ["環境変数 KIT_DENY_WORDS"]

    (tmp_path / cp.DENY_FILE_DEFAULT).write_text("# comment\n\n" + word + "\n", encoding="utf-8")
    deny2, sources2 = cp.load_deny(tmp_path, {})
    assert deny2 is not None and deny2.search(word) and sources2 == [f"ファイル {cp.DENY_FILE_DEFAULT}"]
    # 語のファイルそのものは検査しない
    assert _scan(tmp_path, ["ok"], deny=deny2) == []

    other = tmp_path / "elsewhere.txt"
    other.write_text("Wv" + "xq\n", encoding="utf-8")
    deny3, _ = cp.load_deny(tmp_path, {"KIT_DENY_WORDS_FILE": str(other)})
    assert deny3.search("wvxq")


def test_no_deny_words(tmp_path):
    assert cp.load_deny(tmp_path, {}) == (None, [])


def test_allow_list(tmp_path):
    line = "id 00000000-" + "0000-0000-0000-" + "000000000001"
    assert _scan(tmp_path, [line], name="t.py")
    assert _scan(tmp_path, [line], name="t.py", allow="# zero uuid\n*.py:0{8}-0{4}\n") == []
    assert _scan(tmp_path, [line], name="t.md", allow="*.py:0{8}-0{4}\n")  # 別のパスには効かない


def test_main_exit_codes(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("KIT_DENY_WORDS", raising=False)
    monkeypatch.delenv("KIT_DENY_WORDS_FILE", raising=False)
    (tmp_path / "ok.md").write_text("clean\n", encoding="utf-8")
    assert cp.main(["--root", str(tmp_path)]) == 0
    assert "飛ばしました" in capsys.readouterr().err
    assert cp.main(["--root", str(tmp_path), "--require-deny-words"]) == 1
    (tmp_path / "bad.md").write_text("x" + AT + "example.com\n", encoding="utf-8")
    assert cp.main(["--root", str(tmp_path)]) == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="git が要る")
def test_history(tmp_path):
    def git(*a, env=None):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, env=env)
    git("init", "-q")
    (tmp_path / "a.md").write_text("a\n", encoding="utf-8")
    git("add", "a.md")
    ok_mail = "1+someone" + AT + "users.noreply.github.com"
    git("-c", "user.name=someone", "-c", f"user.email={ok_mail}", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "first\n\nCo-authored-by: Bot <noreply" + AT + "example.com>")
    assert cp.scan_history(tmp_path) == []
    assert cp.list_files(tmp_path, use_git=True) == ["a.md"]
    (tmp_path / "a.md").write_text("b\n", encoding="utf-8")
    git("add", "a.md")
    git("-c", "user.name=someone", "-c", f"user.email={ok_mail}", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "second\n\nCo-authored-by: P <person" + AT + "example.com>")
    hits = cp.scan_history(tmp_path)
    assert len(hits) == 1 and "person" not in hits[0].text
    # HEAD から辿れない commit（別のブランチ）は --head-only では見ない
    git("checkout", "-q", "-b", "side", "HEAD~1")
    assert cp.scan_history(tmp_path, "HEAD") == []
    assert len(cp.scan_history(tmp_path)) == 1


def test_this_repository_is_clean():
    """リポジトリそのもの（追跡ファイル、無ければフォルダ全体）に当たりが無い。"""
    use_git = shutil.which("git") is not None and (ROOT / ".git").exists()
    files = cp.list_files(ROOT, use_git=use_git)
    if not use_git:
        files = [f for f in files if not any(part in f for part in (".venv", "egg-info", "__pycache__", ".pytest_cache"))]
    deny, _ = cp.load_deny(ROOT, {})
    assert cp.scan(ROOT, files, deny, cp.load_allow(ROOT)) == []
