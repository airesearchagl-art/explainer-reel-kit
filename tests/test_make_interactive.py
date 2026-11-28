"""erkit make --render-mode interactive: サンプル samples/u-value を、PowerPoint の無い環境で MP4 まで（検証つき）。

本物のブラウザ・AivisSpeech・PowerPoint は使わない（撮影・説明図は偽の画像、音声は文ごとに音と無音を返す偽のエンジン）。
PowerPoint の書き出し（export/ の PowerShell）は、interactive では一度も呼ばれないこと（呼べば失敗するように差し替える）、
映像の作り方の優先順位（コマンド ＞ 台本 ＞ 既定）、区分の関所が interactive でも効くこと、scenes.yaml の誤りは
出力フォルダを作る前に終了コード 2 になることを確かめる。
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import socket
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from conftest import EXAMPLE, ROOT
from deck_helpers import scene_mark_names
from interactive_helpers import SentenceEngine
from narration_fakes import FakeTTS
from reel_helpers import HAS_FFMPEG, ffprobe_sec, make_black_video, needs_ffmpeg

from explainer_reel_kit import doctor
from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.config import KitConfig
from explainer_reel_kit.interactive.subtitles import parse_srt
from explainer_reel_kit.reel import cli as make_cli
from explainer_reel_kit.reel.make import (INTERACTIVE_STAGES, JST, STAGES, Hooks, MakeError, MakeOptions, MakeStop,
                                          Maker, make)
from explainer_reel_kit.reel.mux import pptx_total_sec

make_mod = importlib.import_module("explainer_reel_kit.reel.make")   # reel.make は関数の名前でもある
SAMPLE = ROOT / "samples" / "u-value"
STORYBOARD = SAMPLE / "u-value.storyboard.md"
NOW = datetime(2026, 11, 27, 9, 0, tzinfo=JST)
QUIET = lambda s: None  # noqa: E731


# ------------------------------------------------------------------ 偽の撮影・説明図・書き出し

def _png_with_marks(path: Path, scene: dict, size=(1600, 900)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (230, 235, 240)).save(path)
    names = scene_mark_names(scene)
    w, h = size
    marks = {}
    for i, n in enumerate(names):
        b = {"x": 0.1 + 0.2 * i, "y": 0.3, "w": 0.15, "h": 0.2}
        marks[n] = {"box": b, "px": {"x": round(b["x"] * w), "y": round(b["y"] * h), "w": round(b["w"] * w),
                                     "h": round(b["h"] * h)}, "how": "test"}
    path.with_name(path.stem + ".marks.json").write_text(json.dumps({
        "format": "explainer-reel/marks@1", "scene": scene["id"], "source": scene["image"]["source"],
        "image": path.name, "image_size": {"w": w, "h": h}, "captured_at": NOW.isoformat(), "marks": marks},
        ensure_ascii=False), encoding="utf-8")


class FakeMedia:
    """撮影と説明図の代わり（台本の画像の場所に PNG と marks.json を書く）。"""

    def __init__(self):
        self.calls: list[str] = []

    def capture(self, storyboard, out_root, actions_path, only, url_map, channel, executable, headed, serve=None,
                log=None):
        self.calls.append("capture")
        doc = sb.load_storyboard(storyboard)
        for s in doc["scenes"]:
            if s["image"]["source"] == "web":
                _png_with_marks(Path(out_root) / s["image"]["ref"], s)
        return {"ok": 3, "failed": 0, "scenes": []}

    def diagram(self, storyboard, out_root, only, channel, executable, log=None):
        self.calls.append("diagram")
        doc = sb.load_storyboard(storyboard)
        for s in doc["scenes"]:
            if (s.get("capture") or {}).get("tool") == "html":
                _png_with_marks(Path(out_root) / s["image"]["ref"], s, (2420, 1000))
        return {"ok": 2, "failed": 0, "scenes": []}


def _no_powerpoint(*a, **k):
    raise AssertionError("PowerPoint の書き出し（export/ の PowerShell）が呼ばれました")


@pytest.fixture
def no_powerpoint(monkeypatch):
    """PowerPoint を呼べば失敗する: 書き出しのスクリプトと PowerPoint の確かめを差し替える。"""
    monkeypatch.setattr(make_mod, "powershell_exporter", _no_powerpoint)
    monkeypatch.setattr(doctor, "check_powerpoint", _no_powerpoint)


def _exporter(calls):
    def run(pptx, out, force):
        calls.append(pptx)
        make_black_video(out, pptx_total_sec(pptx))
        return {"status": "done"}
    return run


def _opts(tmp_path, storyboard=STORYBOARD, **kw) -> MakeOptions:
    kw.setdefault("output_root", tmp_path / "out")
    kw.setdefault("captures_root", tmp_path / "caps")
    kw.setdefault("serve", SAMPLE / "app")
    kw.setdefault("platform", "linux")
    return MakeOptions(storyboard=Path(storyboard), **kw)


def _hooks(media=None, *, transport=None, engine=None, exporter=None, checks=lambda m, s: []) -> Hooks:
    media = media or FakeMedia()
    return Hooks(capture=media.capture, diagram=media.diagram, transport=transport, engine=engine,
                 exporter=exporter, checks=checks, now=lambda: NOW)


def _run_json(d: Path) -> dict:
    return json.loads((d / "run.json").read_text(encoding="utf-8"))


def _copy_sample(tmp_path: Path, name: str = "reel") -> Path:
    """サンプルのフォルダを写す（台本・説明図の HTML・計算ページ・scenes/）。写した台本を返す。"""
    d = tmp_path / name
    shutil.copytree(SAMPLE, d)
    return d / STORYBOARD.name


def _edit_front(story: Path, old: str, new: str) -> None:
    text = story.read_text(encoding="utf-8")
    assert old in text
    story.write_text(text.replace(old, new, 1), encoding="utf-8")


# ------------------------------------------------------------------ samples/u-value を interactive で MP4 まで

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """PowerPoint の無い環境（linux）で、samples/u-value を interactive で MP4 まで。ネットワークも使えなくする。"""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg が要ります")
    tmp = tmp_path_factory.mktemp("u-value-interactive")
    mp = pytest.MonkeyPatch()
    mp.setattr(make_mod, "powershell_exporter", _no_powerpoint)
    mp.setattr(doctor, "check_powerpoint", _no_powerpoint)
    real = socket.socket

    def no_network(*a, **kw):
        raise AssertionError("erkit make（interactive）がネットワークを使おうとしました")

    exporter_calls: list = []
    logs: list[str] = []
    socket.socket = no_network
    try:
        res = make(_opts(tmp, render_mode="interactive"), KitConfig(),
                   _hooks(transport=SentenceEngine(), exporter=_exporter(exporter_calls)), log=logs.append)
    finally:
        socket.socket = real
        mp.undo()
    return {"res": res, "out": res.out_dir, "run": _run_json(res.out_dir), "exporter_calls": exporter_calls,
            "log": "\n".join(logs)}


@needs_ffmpeg
def test_sample_makes_mp4_without_powerpoint_and_verify_passes(built):
    out, run = built["out"], built["run"]
    assert built["res"].status == "done" and run["status"] == "done"
    mp4, srt, pptx = out / "u_value.mp4", out / "u_value.srt", out / "u_value.pptx"
    assert mp4.is_file() and srt.is_file() and pptx.is_file()
    assert abs(ffprobe_sec(mp4, "v:0") - ffprobe_sec(mp4, "a:0")) <= 0.2
    # PowerPoint の書き出しは一度も呼ばれない（Hooks の exporter も、export/ の PowerShell も）
    assert built["exporter_calls"] == []
    assert [n for n in INTERACTIVE_STAGES if run["stages"][n]["status"] == "ok"] == list(INTERACTIVE_STAGES)
    exp = run["stages"]["export"]
    assert exp["how"] == "interactive" and "PowerPoint を使わない" in exp["title"]
    assert exp["network"].startswith("使わない") and exp["srt"] == str(srt)
    assert exp["render"]["scenes"]["sources"]["s01"] == "scenes.yaml"
    assert exp["render"]["scenes"]["sources"]["s03"] == "default"   # 撮影の場面は撮影画像をそのまま
    ver = run["stages"]["verify"]
    assert ver["ok"] is True and ver["result_status"] == "ok" and ver["failed"] == [], ver
    assert Path(ver["report"]).name == "検証結果.md" and Path(ver["report"]).is_file()
    assert run["files"]["srt"] == str(srt) and run["files"]["mp4"] == str(mp4)
    assert run["files"]["verify_report"] == ver["report"]
    # Morph の補正は interactive ではしない。音量はそろえる
    assert run["stages"]["mux"]["drift_corrected"] is False and run["stages"]["mux"]["morph_extra_sec"] == 0
    assert run["stages"]["mux"]["loudness"]
    # 合成の前に scenes.yaml を確かめた記録
    assert run["scenes_check"]["status"] == "ok" and run["scenes_check"]["scenes"] == ["outro", "s01", "s02"]
    assert parse_srt(srt)


@needs_ffmpeg
def test_sample_default_scenes_show_provenance_heading_and_marks(built):
    """撮影の場面（既定の場面）は slides と同じく、見出し・来歴ラベル（実キャプチャ）・台本の注釈を出す。"""
    out = built["out"]
    tl = json.loads((out / "work" / "render-timeline.json").read_text(encoding="utf-8"))
    sc = {s["id"]: s for s in tl["scenes"]}
    for sid in ("s03", "s04", "s05"):
        assert sc[sid]["label"] == "実キャプチャ" and sc[sid]["heading"] and sc[sid]["annotations"], sid
    assert [a["mark"] for a in sc["s04"]["annotations"]] == ["glass_select", "u_row_lowe"]
    assert sc["s05"]["annotations"][0]["kind"] == "arrow"
    shown = {e["text"] for e in json.loads((out / "checks" / "screen_text.json").read_text(encoding="utf-8"))
             if not e["subtitle"]}
    assert {"実キャプチャ", "計算ページを開く", "ガラスの種類を選ぶ", "結果を比べる"} <= shown


@needs_ffmpeg
def test_run_json_records_render_mode_from_the_command(built):
    run = built["run"]
    assert run["render_mode"] == {"mode": "interactive", "source": "command"}
    assert "--render-mode interactive" in run["command"]
    items = {c["item"] for c in (run["network_checks"] or [])}
    assert run["network_checks"] is None or "コード描画（interactive）" in items  # general の台本は確かめない


@needs_ffmpeg
def test_done_message_lists_srt_and_verify_report(built):
    log = built["log"]
    assert "[make] 映像の作り方: interactive（--render-mode）" in log
    assert re.search(r"字幕（SRT）: .*u_value\.srt", log)
    assert re.search(r"検証（ok）: .*検証結果\.md", log)
    assert "PowerPoint で無音の MP4 に書き出す" not in log


@needs_ffmpeg
def test_resume_from_verify(built):
    res = make(_opts(built["out"].parent.parent, render_mode="interactive", from_stage="verify", out_dir=built["out"]),
               KitConfig(), _hooks(transport=SentenceEngine()), log=QUIET)
    run = _run_json(res.out_dir)
    assert res.status == "done" and run["resumed"][-1]["from"] == "verify" and run["stages"]["verify"]["ok"]


# ------------------------------------------------------------------ PowerPoint を呼ぶのは slides だけ

@needs_ffmpeg
def test_slides_uses_the_exporter(tmp_path, no_powerpoint):
    calls: list = []
    res = make(_opts(tmp_path, platform="win32"), KitConfig(), _hooks(engine=FakeTTS(), exporter=_exporter(calls)),
               log=QUIET)
    run = _run_json(res.out_dir)
    assert res.status == "done" and len(calls) == 1
    assert run["render_mode"] == {"mode": "slides", "source": "default"}
    assert list(run["stages"]) == list(STAGES) and "srt" not in run["files"]


def test_interactive_prerequisites_do_not_check_powerpoint(tmp_path, no_powerpoint):
    """前提の確かめ（実物）: interactive は PowerPoint を確かめず、コード描画と ffmpeg を確かめる。Windows でも同じ。"""
    for platform in ("linux", "win32"):
        m = Maker(_opts(tmp_path, render_mode="interactive", platform=platform),
                  hooks=Hooks(capture=FakeMedia().capture, diagram=FakeMedia().diagram, transport=SentenceEngine()))
        labels = [label for label, _ in m.default_checks(m.stages_to_run())]
        assert doctor.INTERACTIVE_NAME in labels and "ffmpeg / ffprobe" in labels
        assert not any("PowerPoint" in label and "使わない" not in label for label in labels)


def test_interactive_stages_on_non_windows_are_not_skipped(tmp_path):
    m = Maker(_opts(tmp_path, render_mode="interactive"))
    assert m.stages == INTERACTIVE_STAGES
    assert all(m.stage_needed(n)[0] for n in ("export", "mux", "verify"))
    slides = Maker(_opts(tmp_path))
    assert slides.stages == STAGES and slides.stage_needed("export")[1].startswith("Windows 以外")


def test_dry_run_shows_the_interactive_stages(tmp_path, capsys):
    res = make(_opts(tmp_path, render_mode="interactive", dry_run=True), KitConfig(), _hooks(engine=FakeTTS()))
    assert res.status == "dry_run" and not (tmp_path / "out").exists()
    out = capsys.readouterr().out
    assert "映像の作り方: interactive（--render-mode）" in out
    assert "6. export（書き出し（コード描画。PowerPoint を使わない））" in out and "8. verify（検証（interactive））" in out
    assert "u_value.srt" in out and "検証結果.md" in out and "省略" not in out
    assert "scenes.yaml を合成の前に確かめました" in out


def test_from_verify_needs_interactive(tmp_path):
    with pytest.raises(MakeError, match="interactive のときだけ"):
        Maker(_opts(tmp_path, from_stage="verify"))


# ------------------------------------------------------------------ 映像の作り方の優先順位

def test_render_mode_priority(tmp_path):
    story = _copy_sample(tmp_path)
    assert (Maker(_opts(tmp_path, storyboard=story)).render_mode,
            Maker(_opts(tmp_path, storyboard=story)).render_mode_source) == ("slides", "default")
    _edit_front(story, "schema_version: kit-1.0.0", "schema_version: kit-1.2.0\nrender_mode: interactive")
    m = Maker(_opts(tmp_path, storyboard=story))
    assert (m.render_mode, m.render_mode_source) == ("interactive", "storyboard")
    m = Maker(_opts(tmp_path, storyboard=story, render_mode="slides"))
    assert (m.render_mode, m.render_mode_source) == ("slides", "command")
    assert "--render-mode slides" in m.command("export")
    with pytest.raises(MakeError, match="--render-mode"):
        Maker(_opts(tmp_path, storyboard=story, render_mode="video"))


def test_run_json_records_render_mode_from_the_storyboard(tmp_path):
    """台本の render_mode（kit-1.2.0）: run.json の source は storyboard、続きのコマンドに --render-mode を足さない。"""
    story = _copy_sample(tmp_path)
    _edit_front(story, "schema_version: kit-1.0.0", "schema_version: kit-1.2.0\nrender_mode: interactive")
    from explainer_reel_kit.narration.tts.aivisspeech import TransportConnectionError

    def down(*a, **k):
        raise TransportConnectionError("refused")

    with pytest.raises(MakeStop, match="voice"):
        make(_opts(tmp_path, storyboard=story), KitConfig(), _hooks(transport=down), log=QUIET)
    out = tmp_path / "out" / "20261127_u-value"
    run = _run_json(out)
    assert run["render_mode"] == {"mode": "interactive", "source": "storyboard"}
    assert "--render-mode" not in run["resume"] and "--from voice" in run["resume"]
    assert run["scenes_check"]["status"] == "ok"


@needs_ffmpeg
def test_kit_1_1_0_storyboard_still_runs_on_slides(tmp_path, no_powerpoint):
    examples = tmp_path / "examples"   # 例のフォルダを写す（台本は説明図の HTML・操作定義を相対で指す）
    shutil.copytree(EXAMPLE.parent, examples)
    doc = sb.load_storyboard(EXAMPLE)
    doc["reel"]["schema_version"] = "kit-1.1.0"
    story = examples / "kit110.storyboard.json"
    story.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    calls: list = []
    res = make(_opts(tmp_path, storyboard=story, platform="win32", serve=examples / "hello-page",
                     actions=examples / "hello-kit.actions.yaml"),
               KitConfig(), _hooks(engine=FakeTTS(), exporter=_exporter(calls)), log=QUIET)
    run = _run_json(res.out_dir)
    assert res.status == "done" and calls and run["render_mode"] == {"mode": "slides", "source": "default"}


# ------------------------------------------------------------------ 区分の関所（interactive でも同じ）

@pytest.fixture
def secret(tmp_path) -> Path:
    story = _copy_sample(tmp_path, "secret")
    _edit_front(story, "confidentiality: general", "confidentiality: confidential")
    return story


def test_confidential_interactive_with_local_settings_checks_the_renderer(tmp_path, secret):
    logs: list[str] = []
    make(_opts(tmp_path, storyboard=secret, render_mode="interactive", dry_run=True), KitConfig(),
         _hooks(engine=FakeTTS()), log=logs.append)
    text = "\n".join(logs)
    assert "社外秘（confidential）の台本" in text and "コード描画（interactive）=ネットワークを使わない" in text


@pytest.mark.parametrize("opt, bad", [
    ({"engine_url": "http://192.168.1.10:10101"}, "音声合成エンジン"),
    ({"serve": None, "url_map": [("http://127.0.0.1:8000/", "https://tool.example.com/")]}, "撮影の URL（s03）"),
])
def test_confidential_interactive_stops_before_creating_anything(tmp_path, secret, opt, bad, capsys, no_powerpoint):
    media, tts = FakeMedia(), FakeTTS()
    with pytest.raises(MakeStop, match="この PC の外"):
        make(_opts(tmp_path, storyboard=secret, render_mode="interactive", **opt), KitConfig(),
             _hooks(media, engine=tts))
    assert media.calls == [] and tts.spoken == []
    assert not (tmp_path / "out").exists() and not (tmp_path / "caps").exists()
    assert bad in capsys.readouterr().out


def test_confidential_engine_url_from_config_is_checked_in_interactive(tmp_path, secret):
    with pytest.raises(MakeStop):
        make(_opts(tmp_path, storyboard=secret, render_mode="interactive"), KitConfig(voice_url="http://tts.example.com"),
             _hooks(engine=FakeTTS()), log=QUIET)


def _scenes_yaml(story: Path) -> Path:
    return story.parent / "scenes" / "u-value" / "scenes.yaml"


@pytest.mark.parametrize("src", ["https://example.com/window.png", "OUTSIDE"])
def test_images_from_outside_are_errors_before_anything(tmp_path, secret, src, capsys):
    """描画の静止画に外の URL・台本のフォルダの外のファイルを書くと、出力フォルダを作る前に誤り（終了コード 2）。"""
    if src == "OUTSIDE":
        outside = tmp_path / "elsewhere" / "a.png"
        outside.parent.mkdir()
        Image.new("RGB", (64, 64)).save(outside)
        src = str(outside)
    _scenes_yaml(secret).write_text(
        "version: 1\nscenes:\n  s03:\n    parts:\n      - type: image\n        images:\n"
        f"          - src: {json.dumps(src)}\n", encoding="utf-8")
    media, tts = FakeMedia(), FakeTTS()
    with pytest.raises(MakeError) as e:
        make(_opts(tmp_path, storyboard=secret, render_mode="interactive"), KitConfig(), _hooks(media, engine=tts))
    assert e.value.exit_code == 2 and ("URL" in str(e.value) or "台本のフォルダか出力フォルダの中" in str(e.value))
    assert media.calls == [] and tts.spoken == [] and not (tmp_path / "out").exists()


# ------------------------------------------------------------------ scenes.yaml の誤り → 出力フォルダを作る前に終了コード 2

@pytest.mark.parametrize("body, msg", [
    ("version: 1\nscenes:\n  s01:\n    parts:\n      - type: chart\n", "知らない型"),
    ("version: 1\nscenes:\n  s01:\n    parts:\n      - type: callout\n        text: x\n        at: 存在しない語句\n",
     "存在しない語句"),
    ("version: 1\nscenes:\n  s99:\n    parts:\n      - type: callout\n        text: x\n", "s99"),
])
def test_scenes_yaml_errors_exit_2_before_the_output_folder(tmp_path, body, msg, capsys):
    story = _copy_sample(tmp_path)
    _scenes_yaml(story).write_text(body, encoding="utf-8")
    cfg = tmp_path / "kit.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    parser = make_cli.configure(argparse.ArgumentParser())
    args = parser.parse_args([str(story), "--config", str(cfg), "--output-root", str(tmp_path / "o"),
                              "--captures-root", str(tmp_path / "c"), "--render-mode", "interactive"])
    tts = FakeTTS()
    assert make_cli.run(args, hooks=_hooks(engine=tts), platform="linux") == 2
    assert not (tmp_path / "o").exists() and tts.spoken == []
    assert msg in capsys.readouterr().err


def test_scenes_yaml_is_not_read_for_slides(tmp_path):
    story = _copy_sample(tmp_path)
    _scenes_yaml(story).write_text("version: 1\nscenes:\n  s01:\n    parts:\n      - type: chart\n", encoding="utf-8")
    res = make(_opts(tmp_path, storyboard=story), KitConfig(), _hooks(engine=FakeTTS()), log=QUIET)
    assert res.status == "needs_export" and "scenes_check" not in _run_json(res.out_dir)


# ------------------------------------------------------------------ CLI

def test_cli_passes_reuse_run_and_render_mode(tmp_path):
    prev = tmp_path / "prev"
    (prev / "work" / "narration").mkdir(parents=True)
    (prev / "work" / "narration" / "durations.json").write_text("{}", encoding="utf-8")
    parser = make_cli.configure(argparse.ArgumentParser())
    args = parser.parse_args([str(STORYBOARD), "--reuse-run", str(prev), "--render-mode", "interactive",
                              "--from", "verify"])
    opts = make_cli.options_from_args(args)
    assert opts.reuse_run == prev and opts.render_mode == "interactive" and opts.from_stage == "verify"
    args = parser.parse_args([str(STORYBOARD)])
    opts = make_cli.options_from_args(args)
    assert opts.reuse_run is None and opts.render_mode is None


def test_cli_errors(tmp_path, capsys):
    assert erkit(["make", str(STORYBOARD), "--render-mode", "video"]) == 2
    assert erkit(["make", str(STORYBOARD), "--reuse-run", str(tmp_path / "none"),
                  "--output-root", str(tmp_path / "o")]) == 2
    assert "durations.json" in capsys.readouterr().err
    assert erkit(["make", str(STORYBOARD), "--from", "verify", "--output-root", str(tmp_path / "o")]) == 2
    assert not (tmp_path / "o").exists()


def test_cli_help_mentions_render_mode(capsys):
    assert erkit(["make", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--render-mode" in out and "--reuse-run" in out and "interactive" in out


# ------------------------------------------------------------------ erkit doctor

def _doctor(tmp_path, monkeypatch, platform, *, ffmpeg_ok=True, powerpoint=None):
    from reel_helpers import FakeEngine

    monkeypatch.setattr(doctor, "check_ffmpeg", lambda *a, **k: doctor.CheckResult(
        "ffmpeg", "ffmpeg / ffprobe", doctor.OK if ffmpeg_ok else doctor.FAIL, "x"))
    if powerpoint is not None:
        real = doctor.check_powerpoint
        monkeypatch.setattr(doctor, "check_powerpoint", lambda p=None: real(p, registered=lambda: powerpoint))
    cfg = tmp_path / "kit.yaml"
    cfg.write_text(f"output_root: {json.dumps(str(tmp_path / 'out'))}\n", encoding="utf-8")
    return cfg, FakeEngine()


def test_doctor_shows_interactive_on_linux(tmp_path, capsys, monkeypatch):
    cfg, eng = _doctor(tmp_path, monkeypatch, "linux")
    code = doctor.main(["--config", str(cfg), "--skip-browser", "--skip-llm"], transport=eng, platform="linux")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "OK   コード描画（interactive。PowerPoint を使わない）: Pillow" in out
    assert "NotoSansJP-Regular.otf / NotoSansJP-Bold.otf" in out
    assert "--   PowerPoint（書き出し）: Windows でだけ使う" in out and "erkit make --render-mode interactive）" in out
    assert "そろっています" in out
    assert "PowerPoint が無くても、interactive（erkit make --render-mode interactive）なら MP4 まで作れます" in out


def test_doctor_windows_without_powerpoint_points_to_interactive(tmp_path, capsys, monkeypatch):
    cfg, eng = _doctor(tmp_path, monkeypatch, "win32", powerpoint=False)
    code = doctor.main(["--config", str(cfg), "--skip-browser", "--skip-llm", "--json"], transport=eng, platform="win32")
    data = json.loads(capsys.readouterr().out)
    assert code == 1 and data["routes"] == {"slides": False, "interactive": True}
    doctor.main(["--config", str(cfg), "--skip-browser", "--skip-llm"], transport=eng, platform="win32")
    out = capsys.readouterr().out
    assert "NG   PowerPoint（書き出し）" in out and "足りないもの 1 件" in out
    assert "PowerPoint が無くても、interactive（erkit make --render-mode interactive）なら MP4 まで作れます" in out


def test_doctor_windows_with_powerpoint_has_both_routes(tmp_path, capsys, monkeypatch):
    cfg, eng = _doctor(tmp_path, monkeypatch, "win32", powerpoint=True)
    assert doctor.main(["--config", str(cfg), "--skip-browser", "--skip-llm", "--json"], transport=eng,
                       platform="win32") == 0
    assert json.loads(capsys.readouterr().out)["routes"] == {"slides": True, "interactive": True}


def test_check_interactive(monkeypatch):
    from explainer_reel_kit.interactive import engine as ie

    ok = doctor.check_interactive()
    assert ok.status == doctor.OK and "erkit make --render-mode interactive" in ok.detail
    no_ff = doctor.check_interactive(doctor.CheckResult("ffmpeg", "ffmpeg", doctor.FAIL))
    assert no_ff.status == doctor.WARN and "ffmpeg" in no_ff.detail and "winget" in no_ff.hint
    monkeypatch.setattr(ie, "FONT_FILES", {"R": "NotoSansJP-Regular.otf", "B": "missing.otf"})
    bad = doctor.check_interactive()
    assert bad.status == doctor.FAIL and "missing.otf" in bad.detail and "pip install" in bad.hint


def test_doctor_without_ffmpeg_says_interactive_is_not_ready(tmp_path, capsys, monkeypatch):
    cfg, eng = _doctor(tmp_path, monkeypatch, "linux", ffmpeg_ok=False)
    assert doctor.main(["--config", str(cfg), "--skip-browser", "--skip-llm"], transport=eng, platform="linux") == 1
    out = capsys.readouterr().out
    assert "注意 コード描画（interactive。PowerPoint を使わない）" in out and "足りないもの 1 件" in out
    assert "この PC では .pptx までです" in out
