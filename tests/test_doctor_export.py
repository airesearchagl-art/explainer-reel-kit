"""erkit doctor・書き出しの呼び出し・設定の撮影素材のルート。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from reel_helpers import FakeEngine

from explainer_reel_kit import config as kit_config
from explainer_reel_kit import doctor
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.export import ExportError, manual_command, parse_result, powershell_exporter, script_path


# ------------------------------------------------------------------ doctor

def test_doctor_all_ok_with_fake_engine(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(doctor, "check_ffmpeg", lambda *a, **k: doctor.CheckResult("ffmpeg", "ffmpeg / ffprobe", "ok", "x"))
    cfg = tmp_path / "kit.yaml"
    cfg.write_text(f"output_root: {json.dumps(str(tmp_path / 'out'))}\n", encoding="utf-8")
    code = doctor.main(["--config", str(cfg), "--skip-browser"], transport=FakeEngine(), platform="linux")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "OK   Python" in out and "OK   音声合成エンジン" in out and "808373280 Test / ノーマル" in out
    assert "--   PowerPoint（書き出し）: Windows でだけ使う" in out and "そろっています" in out


def test_doctor_reports_missing_things_with_hints(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ERKIT_OUTPUT_ROOT", str(tmp_path / "o"))
    code = doctor.main(["--skip-browser", "--engine-url", "http://127.0.0.1:1"],
                       transport=_down, platform="win32")
    out = capsys.readouterr().out
    assert code == 1
    assert "NG   音声合成エンジン" in out and "aivis-project.com" in out
    assert "--   既定の声: エンジンにつながらない" in out
    assert "NG   PowerPoint（書き出し）" in out and "デスクトップ版" in out
    assert "キットは自動では入れません" in out


def _down(method, url, headers, body, timeout):
    from explainer_reel_kit.narration.tts.aivisspeech import TransportConnectionError

    raise TransportConnectionError("refused")


def test_doctor_default_voice_missing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ERKIT_OUTPUT_ROOT", str(tmp_path / "o"))
    cfg = tmp_path / "kit.yaml"
    cfg.write_text("voice:\n  speaker: 55\n", encoding="utf-8")
    assert doctor.main(["--config", str(cfg), "--skip-browser", "--json"], transport=FakeEngine(), platform="linux") == 1
    data = json.loads(capsys.readouterr().out)
    voice = next(c for c in data["checks"] if c["key"] == "voice")
    assert voice["status"] == "fail" and "808373280 Test / ノーマル" in voice["detail"] and "voice.speaker" in voice["hint"]
    assert data["ok"] is False


def test_doctor_config_error(tmp_path, capsys):
    bad = tmp_path / "kit.yaml"
    bad.write_text("voice: 3\n", encoding="utf-8")
    assert doctor.main(["--config", str(bad)]) == 2


def test_doctor_is_registered(capsys):
    assert erkit(["doctor", "--help"]) == 0
    assert "--skip-browser" in capsys.readouterr().out


def test_check_ffmpeg(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda exe: None)
    r = doctor.check_ffmpeg()
    assert r.status == "fail" and "winget install Gyan.FFmpeg" in r.hint
    monkeypatch.setattr(doctor.shutil, "which", lambda exe: f"/bin/{exe}")
    ok = doctor.check_ffmpeg(run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "ffmpeg version 7.0 Copyright (c) 2000-2024 the FFmpeg developers", ""))
    assert ok.status == "ok" and ok.detail == "ffmpeg version 7.0"
    bad = doctor.check_ffmpeg(run=lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    assert bad.status == "fail"


def test_check_powerpoint():
    assert doctor.check_powerpoint("linux").status == "skip"
    assert doctor.check_powerpoint("win32", registered=lambda: True).status == "ok"
    r = doctor.check_powerpoint("win32", registered=lambda: False)
    assert r.status == "fail" and "Web 版" in r.hint


def test_check_packages_and_python():
    assert doctor.check_python().status == "ok"
    assert doctor.check_packages().status == "ok"

    def importer(name):
        if name == "pptx":
            raise ImportError(name)
    r = doctor.check_packages(importer)
    assert r.status == "fail" and "python-pptx" in r.detail


def test_check_output_root(tmp_path):
    assert doctor.check_output_root(tmp_path / "new").status in ("ok", "warn")
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    assert doctor.check_output_root(f / "sub").status == "fail"


def test_check_browser_failure(monkeypatch):
    from explainer_reel_kit import browser as br

    def boom(*a, **k):
        raise br.BrowserError("Playwright のブラウザを起動できません")
    monkeypatch.setattr(br, "launch", boom)
    r = doctor.check_browser()
    assert r.status == "fail" and "--channel msedge" in r.hint


def test_check_browser_real(browser_opts):
    assert doctor.check_browser(browser_opts["channel"]).status == "ok"


# ------------------------------------------------------------------ 書き出しの呼び出し

def test_script_is_packaged_and_ascii_only():
    p = script_path()
    assert p.is_file() and p.name == "Export-PptxToVideo.ps1"
    data = p.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")  # BOM なし
    data.decode("ascii")  # Windows PowerShell 5.1 が読み違えないよう ASCII だけ


def test_parse_result_takes_the_last_json_line():
    assert parse_result('progress\n{"status": "x"}\n{"status": "done", "duration_sec": 3.2}\n') == {
        "status": "done", "duration_sec": 3.2}
    assert parse_result("no json") == {}


def test_powershell_exporter_command_and_errors(tmp_path):
    seen = []

    def runner(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '{"status": "done"}\n', "")
    exp = powershell_exporter("pwsh", runner=runner)
    info = exp(tmp_path / "a.pptx", tmp_path / "a.mp4", True)
    assert info == {"status": "done", "exit_code": 0}
    cmd = seen[0]
    assert cmd[:5] == ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert cmd[5] == str(script_path()) and cmd[-1] == "-Force"
    assert cmd[cmd.index("-InputPath") + 1] == str(tmp_path / "a.pptx")

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 4, '{"status": "failed", "error": "COM の起動に失敗"}\n', "")
    with pytest.raises(ExportError, match="終了コード 4.*PowerPoint を起動できない.*COM の起動に失敗"):
        powershell_exporter(runner=failing)(tmp_path / "a.pptx", tmp_path / "a.mp4", False)


def test_manual_command_mentions_the_packaged_script(tmp_path):
    cmd = manual_command(tmp_path / "a.pptx", tmp_path / "a.mp4")
    assert str(script_path()) in cmd and "-InputPath" in cmd and "-OutputPath" in cmd


# ------------------------------------------------------------------ 設定: 撮影素材のルート

def test_captures_root_order(tmp_path):
    cfg = kit_config.parse_config({"captures_root": str(tmp_path / "c"), "output_root": str(tmp_path / "o")})
    assert kit_config.captures_root(cfg, env={}) == tmp_path / "c"
    assert kit_config.captures_root(cfg, env={"ERKIT_CAPTURES_ROOT": str(tmp_path / "e")}) == tmp_path / "e"
    assert kit_config.captures_root(cfg, tmp_path / "x", env={"ERKIT_CAPTURES_ROOT": "y"}) == tmp_path / "x"
    assert kit_config.captures_root(kit_config.KitConfig(), env={}) == Path.home() / "ExplainerReelKit" / "captures"
    with pytest.raises(kit_config.ConfigError, match="captures_root"):
        kit_config.parse_config({"captures_root": 3})


def test_capture_default_root_reads_config(tmp_path, monkeypatch):
    from explainer_reel_kit.capture.web import capture as wc

    cfg = tmp_path / "kit.yaml"
    cfg.write_text(f"captures_root: {json.dumps(str(tmp_path / 'from-config'))}\n", encoding="utf-8")
    monkeypatch.setenv("ERKIT_CONFIG", str(cfg))
    monkeypatch.delenv("ERKIT_CAPTURES_ROOT", raising=False)
    assert wc.default_captures_root() == tmp_path / "from-config"
    monkeypatch.setenv("ERKIT_CAPTURES_ROOT", str(tmp_path / "env"))
    assert wc.default_captures_root() == tmp_path / "env"
