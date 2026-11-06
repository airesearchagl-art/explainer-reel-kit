"""erkit の入口（--version・check・convert・後で実装するサブコマンド）。"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from explainer_reel_kit import __version__
from explainer_reel_kit.cli import PLANNED, main
from conftest import COMPAT, EXAMPLE, TEMPLATE


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"erkit {__version__}"
    assert __version__ == "0.1.1"


def test_no_command_shows_help(capsys):
    assert main([]) == 2
    assert "check" in capsys.readouterr().out


def test_check_ok_shows_confidentiality(capsys):
    assert main(["check", str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK ") and "区分: general" in out


def test_check_many_and_strict(capsys):
    assert main(["check", str(EXAMPLE), *map(str, COMPAT)]) == 0
    assert main(["check", str(TEMPLATE)]) == 0          # 警告だけ
    assert main(["check", "--strict", str(TEMPLATE)]) == 1
    assert "区分: confidential" in capsys.readouterr().out


def test_check_ng(tmp_path, capsys):
    p = tmp_path / "bad.storyboard.md"
    text = EXAMPLE.read_text(encoding="utf-8").replace("recipe: fade_sequence", "recipe: spin", 1)
    p.write_text(text, encoding="utf-8")
    assert main(["check", str(p)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("NG ") and "[recipe]" in out


def test_check_missing_file(tmp_path, capsys):
    assert main(["check", str(tmp_path / "none.md")]) == 1
    assert "ファイルがありません" in capsys.readouterr().err


def test_check_quiet(capsys):
    assert main(["check", "--quiet", str(TEMPLATE)]) == 0
    assert "警告:" not in capsys.readouterr().out


def test_convert(tmp_path):
    src = tmp_path / "x.storyboard.md"
    src.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["convert", str(src)]) == 0
    doc = json.loads((tmp_path / "x.storyboard.json").read_text(encoding="utf-8"))
    assert doc["reel"]["id"] == "hello-kit" and len(doc["scenes"]) == 5
    out = tmp_path / "o.json"
    assert main(["convert", str(src), "-o", str(out)]) == 0 and out.is_file()


def test_convert_errors(tmp_path, capsys):
    assert main(["convert", str(tmp_path / "none.md")]) == 1
    bad = tmp_path / "bad.md"
    bad.write_text("no front matter", encoding="utf-8")
    assert main(["convert", str(bad)]) == 1


@pytest.mark.parametrize("cmd", sorted(PLANNED))
def test_planned_commands_exit_2(cmd, capsys):
    assert main([cmd, "anything", "--flag"]) == 2
    assert "後のパケットで実装" in capsys.readouterr().err


def test_bad_argument_exit_2():
    assert main(["check"]) == 2


def test_module_entry():
    r = subprocess.run([sys.executable, "-m", "explainer_reel_kit", "check", str(EXAMPLE)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "OK" in r.stdout
