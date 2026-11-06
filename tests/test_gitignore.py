"""利用者の設定（config/kit.yaml・config/llm.yaml）は git に入らない。ひな形（*.example.yaml）は入る。"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from conftest import ROOT


def _ignored(path: str) -> bool:
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", path], capture_output=True)
    if r.returncode not in (0, 1):
        pytest.skip(f"git check-ignore が使えません: {r.stderr.decode(errors='replace').strip()}")
    return r.returncode == 0


@pytest.fixture(autouse=True)
def _need_git():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("git のリポジトリではありません")


@pytest.mark.parametrize("path", ["config/kit.yaml", "config/llm.yaml", "config/other.yaml"])
def test_user_config_is_ignored(path):
    assert _ignored(path)


def test_example_config_is_tracked():
    assert not _ignored("config/kit.example.yaml")
    assert (ROOT / "config" / "kit.example.yaml").is_file()


@pytest.mark.parametrize("path", ["output/x.mp4", "a/assets/s01.png", "a/assets/s01.marks.json", "x.pptx",
                                  "capture-web-result.json", "diagram-result.json"])
def test_outputs_are_ignored(path):
    assert _ignored(path)
