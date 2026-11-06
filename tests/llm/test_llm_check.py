"""erkit llm check（接続・モデルの有無・応答までの時間）と、erkit doctor の任意の行、コマンドの登録。"""
from __future__ import annotations

import json
import socket

import pytest

from explainer_reel_kit import doctor
from explainer_reel_kit.cli import PLANNED
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.llm.cli import CHECK_PROMPT


def check(*args):
    return erkit(["llm", "check", *args])


def test_check_ok(fake_llm, llm_config, capsys):
    assert check("--llm-config", str(llm_config)) == 0
    out = capsys.readouterr().out
    assert fake_llm.url in out and "この PC" in out and "* test-model-7b" in out and "準備できました" in out
    posts = [r for r in fake_llm.requests if r["method"] == "POST"]
    assert len(posts) == 1 and posts[0]["body"]["messages"] == [{"role": "user", "content": CHECK_PROMPT}]


def test_check_json(fake_llm, llm_config, capsys):
    assert check("--llm-config", str(llm_config), "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["models"] == ["test-model-7b"] and data["model"] == "test-model-7b" and data["this_pc"]
    assert data["reply"] == "準備できました" and data["reply_sec"] >= 0 and data["error"] is None


def test_check_missing_task_model_is_exit_1(fake_llm, draft_config, capsys):
    fake_llm.models = ["other"]
    assert check("--llm-config", str(draft_config)) == 1
    assert "big-27b" in capsys.readouterr().err
    assert [r for r in fake_llm.requests if r["method"] == "POST"] == []


def test_check_several_models_without_a_choice(fake_llm, llm_config, capsys):
    fake_llm.models = ["a", "b"]
    assert check("--llm-config", str(llm_config)) == 2
    assert "--model" in capsys.readouterr().err
    assert check("--llm-config", str(llm_config), "--model", "b") == 0


def test_check_connection_refused_is_exit_1(tmp_path, capsys):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert check("--base-url", f"http://127.0.0.1:{port}/v1", "--llm-timeout", "2") == 1
    assert "エラー" in capsys.readouterr().err


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://8.8.8.8:1234/v1"])
def test_check_refuses_outside_hosts(url, capsys, no_socket):
    assert check("--base-url", url) == 1
    assert no_socket == []


def test_check_lan_is_allowed_with_a_note(draft_config, capsys, monkeypatch):
    from explainer_reel_kit.llm import client as client_module

    monkeypatch.setattr(client_module.LLMClient, "list_models", lambda self: ["m"])
    monkeypatch.setattr(client_module.LLMClient, "chat", lambda self, *a, **k: client_module.ChatResult(
        content="準備できました", elapsed_sec=0.1, usage=None, finish_reason="stop"))
    assert check("--llm-config", str(draft_config), "--profile", "lan", "--task", "none") == 0
    assert "社外秘の台本" in capsys.readouterr().err


def test_bad_config_is_exit_2(tmp_path, capsys):
    bad = tmp_path / "llm.yaml"
    bad.write_text("version: 1\nprofiles:\n  cc:\n    route: cloud\n    base_url: https://api.example.com/v1\n",
                   encoding="utf-8")
    assert check("--llm-config", str(bad)) == 2
    assert "cloud" in capsys.readouterr().err or "local だけ" in capsys.readouterr().err


def test_draft_is_no_longer_planned_but_new_is():
    assert "draft" not in PLANNED and "new" in PLANNED
    assert erkit(["draft", "--help"]) == 0
    assert erkit(["llm", "--help"]) == 0


# ------------------------------------------------------------------ erkit doctor の任意の行

def _doctor(tmp_path, *extra):
    from reel_helpers import FakeEngine

    cfg = tmp_path / "kit.yaml"
    cfg.write_text(f"output_root: {json.dumps(str(tmp_path / 'out'))}\n", encoding="utf-8")
    return doctor.main(["--config", str(cfg), "--skip-browser", *extra], transport=FakeEngine(), platform="linux")


def test_doctor_llm_row_found(fake_llm, llm_config, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "check_ffmpeg", lambda: doctor.CheckResult("ffmpeg", "ffmpeg", doctor.OK, "fake"))
    code = _doctor(tmp_path, "--llm-config", str(llm_config))
    out = capsys.readouterr().out
    assert "OK   手元の LLM（任意）: fake" in out and "モデル 1 個" in out
    assert code == 0 and "そろっています" in out
    assert [r for r in fake_llm.requests if r["method"] == "POST"] == []  # モデルの一覧だけ


def test_doctor_llm_missing_does_not_change_the_verdict(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "check_ffmpeg", lambda: doctor.CheckResult("ffmpeg", "ffmpeg", doctor.OK, "fake"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "llm.yaml"
    config.write_text(f"version: 1\nprofiles:\n  xx:\n    base_url: http://127.0.0.1:{port}/v1\n", encoding="utf-8")
    code = _doctor(tmp_path, "--llm-config", str(config))
    out = capsys.readouterr().out
    assert "--   手元の LLM（任意）: 使えない" in out and "erkit llm check" in out
    assert code == 0 and "そろっています" in out


def test_doctor_skip_llm_and_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "check_ffmpeg", lambda: doctor.CheckResult("ffmpeg", "ffmpeg", doctor.OK, "fake"))
    assert _doctor(tmp_path, "--skip-llm", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and "llm" not in [c["key"] for c in data["checks"]]


def test_make_does_not_check_the_llm():
    """erkit make が使う run_checks には LLM の行を入れない（任意の段なので、通し生成を止めない）。"""
    import inspect

    assert "check_llm" not in inspect.getsource(doctor.run_checks)
