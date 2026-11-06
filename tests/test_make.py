"""erkit make（通し生成）: 例の台本を、偽の撮影・説明図・音声・書き出しで最後まで。

本物のブラウザ・AivisSpeech・PowerPoint は使わない（ブラウザがあれば撮影と説明図だけ本物でも 1 回通す）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from conftest import EXAMPLE
from deck_helpers import scene_mark_names
from narration_fakes import FakeTTS
from reel_helpers import FakeEngine, ffprobe_sec, make_black_video, needs_ffmpeg

from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.config import KitConfig
from explainer_reel_kit.reel import cli as make_cli
from explainer_reel_kit.reel.make import JST, STAGES, Hooks, MakeError, MakeOptions, MakeStop, Maker, make
from explainer_reel_kit.reel.mux import pptx_total_sec

EXAMPLES = EXAMPLE.parent
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=JST)


def _png_with_marks(path: Path, scene: dict, size=(1920, 1080)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (230, 235, 240)).save(path)
    names = scene_mark_names(scene)
    if names:
        boxes = {n: {"x": 0.1 + 0.2 * i, "y": 0.3, "w": 0.15, "h": 0.2} for i, n in enumerate(names)}
        w, h = size
        marks = {n: {"box": b, "px": {"x": round(b["x"] * w), "y": round(b["y"] * h), "w": round(b["w"] * w),
                                     "h": round(b["h"] * h)}, "how": "test"} for n, b in boxes.items()}
        path.with_name(path.stem + ".marks.json").write_text(json.dumps({
            "format": "explainer-reel/marks@1", "scene": scene["id"], "source": scene["image"]["source"],
            "image": path.name, "image_size": {"w": w, "h": h}, "captured_at": NOW.isoformat(), "marks": marks},
            ensure_ascii=False), encoding="utf-8")


class FakeMedia:
    """撮影と説明図の代わり（台本の画像の場所に PNG と marks.json を書く）。"""

    def __init__(self, fail_capture: bool = False):
        self.calls: list[tuple] = []
        self.fail_capture = fail_capture

    def capture(self, storyboard, out_root, actions_path, only, url_map, channel, executable, headed, serve=None, log=None):
        self.calls.append(("capture", Path(out_root), Path(actions_path), serve))
        doc = sb.load_storyboard(storyboard)
        scenes = [s for s in doc["scenes"] if s["image"]["source"] == "web"]
        if self.fail_capture:
            return {"ok": 0, "failed": len(scenes),
                    "scenes": [{"id": s["id"], "status": "failed", "error": "要素が見つからない"} for s in scenes]}
        for s in scenes:
            _png_with_marks(Path(out_root) / s["image"]["ref"], s)
        return {"ok": len(scenes), "failed": 0, "scenes": []}

    def diagram(self, storyboard, out_root, only, channel, executable, log=None):
        self.calls.append(("diagram", Path(out_root)))
        doc = sb.load_storyboard(storyboard)
        scenes = [s for s in doc["scenes"] if (s.get("capture") or {}).get("tool") == "html"]
        for s in scenes:
            _png_with_marks(Path(out_root) / s["image"]["ref"], s, (2420, 1000))
        return {"ok": len(scenes), "failed": 0, "scenes": []}


def _exporter(calls=None):
    def run(pptx, out, force):
        if calls is not None:
            calls.append((pptx, out, force))
        make_black_video(out, pptx_total_sec(pptx))
        return {"status": "done"}
    return run


def _opts(tmp_path, storyboard=EXAMPLE, **kw) -> MakeOptions:
    kw.setdefault("output_root", tmp_path / "out")
    kw.setdefault("captures_root", tmp_path / "caps")
    kw.setdefault("serve", EXAMPLES / "hello-page")
    kw.setdefault("platform", "linux")
    return MakeOptions(storyboard=Path(storyboard), **kw)


def _hooks(media=None, *, engine=None, exporter=None, checks=lambda m, s: [], transport=None) -> Hooks:
    media = media or FakeMedia()
    return Hooks(capture=media.capture, diagram=media.diagram, engine=engine if transport is None else None,
                 transport=transport, exporter=exporter, checks=checks, now=lambda: NOW)


def _run_json(d: Path) -> dict:
    return json.loads((d / "run.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 例の台本を最後まで

@needs_ffmpeg
def test_example_storyboard_end_to_end(tmp_path):
    media, tts, calls = FakeMedia(), FakeTTS(), []
    res = make(_opts(tmp_path, platform="win32"), KitConfig(), _hooks(media, engine=tts, exporter=_exporter(calls)),
               log=lambda s: None)
    out = tmp_path / "out" / "20261106_hello-kit"
    assert res.status == "done" and res.out_dir == out
    mp4, pptx = out / "hello_kit.mp4", out / "hello_kit.pptx"
    assert mp4.is_file() and pptx.is_file() and (out / "work" / "check" / "overlay.png").is_file()
    assert abs(ffprobe_sec(mp4, "v:0") - ffprobe_sec(mp4, "a:0")) <= 0.2
    # 撮影は撮影素材のフォルダ（日付なし）、説明図はこの実行の work/diagram
    cap_root = tmp_path / "caps" / "web" / "hello-kit"
    assert ("capture", cap_root, EXAMPLES / "hello-kit.actions.yaml", EXAMPLES / "hello-page") in media.calls
    assert ("diagram", out / "work" / "diagram") in media.calls
    assert (out / "work" / "assets" / "captures" / "hello-kit" / "s03_page.png").is_file()
    assert calls == [(pptx, out / "work" / "hello_kit.silent.mp4", True)]
    run = _run_json(out)
    assert run["format"] == "explainer-reel-kit/run@1" and run["status"] == "done"
    assert run["confidentiality"] == "general" and run["network_checks"] is None
    assert [n for n in STAGES if run["stages"][n]["status"] == "ok"] == list(STAGES)
    assert run["stages"]["assets"]["placeholders"] == 0 and run["stages"]["assets"]["unresolved_marks"] == 0
    assert run["speaker"] == 808373280 and run["credit"] is None
    assert run["files"] == {"pptx": str(pptx), "mp4": str(mp4)}
    assert run["storyboard"]["sha256"] and run["resume"] is None


def test_example_storyboard_non_windows_stops_after_deck(tmp_path, capsys):
    res = make(_opts(tmp_path), KitConfig(), _hooks(engine=FakeTTS()))
    assert res.status == "needs_export"
    run = _run_json(res.out_dir)
    assert run["stages"]["export"]["status"] == "skipped" and run["stages"]["mux"]["status"] == "skipped"
    assert run["status"] == "needs_export" and (res.out_dir / "hello_kit.pptx").is_file()
    out = capsys.readouterr().out
    assert "Export-PptxToVideo.ps1" in out and "--from export" in out and "--serve" in out


def test_with_real_browser_for_capture_and_diagram(tmp_path, browser_opts):
    """ブラウザがあるときだけ: 撮影と説明図は本物、音声は偽、Windows 以外の終わり方。"""
    opts = _opts(tmp_path, channel=browser_opts["channel"])
    res = make(opts, KitConfig(), Hooks(engine=FakeTTS(), checks=lambda m, s: [], now=lambda: NOW), log=lambda s: None)
    run = _run_json(res.out_dir)
    assert res.status == "needs_export" and run["stages"]["capture"]["ok"] == 1 and run["stages"]["diagram"]["ok"] == 4
    assert run["stages"]["assets"]["placeholders"] == 0 and run["stages"]["assets"]["unresolved_marks"] == 0


# ------------------------------------------------------------------ 出力の名前

def test_output_folder_names_are_unique_and_take_a_label(tmp_path):
    a = make(_opts(tmp_path), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    b = make(_opts(tmp_path), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    c = make(_opts(tmp_path, label="試作 1"), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    assert [p.name for p in (a.out_dir, b.out_dir, c.out_dir)] == ["20261106_hello-kit", "20261106_hello-kit-2",
                                                                    "20261106_hello-kit_試作-1"]


def test_output_root_from_config(tmp_path):
    cfg = KitConfig(output_root=tmp_path / "from-config", captures_root=tmp_path / "caps-config")
    media = FakeMedia()
    opts = MakeOptions(storyboard=EXAMPLE, serve=EXAMPLES / "hello-page", platform="linux")
    res = make(opts, cfg, _hooks(media, engine=FakeTTS()), log=lambda s: None)
    assert res.out_dir.parent == tmp_path / "from-config"
    assert media.calls[0][1] == tmp_path / "caps-config" / "web" / "hello-kit"


def test_out_dir_must_be_empty(tmp_path):
    d = tmp_path / "used"
    d.mkdir()
    (d / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(MakeError, match="空ではありません"):
        make(_opts(tmp_path, out_dir=d), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)


# ------------------------------------------------------------------ --dry-run

def test_dry_run_creates_nothing(tmp_path, capsys):
    media = FakeMedia()
    res = make(_opts(tmp_path, dry_run=True), KitConfig(), _hooks(media, engine=FakeTTS()))
    assert res.status == "dry_run" and media.calls == []
    assert not (tmp_path / "out").exists() and not (tmp_path / "caps").exists()
    out = capsys.readouterr().out
    for name in STAGES:
        assert f"{name}（" in out
    assert "省略: Windows 以外" in out and "hello_kit.pptx" in out


def test_dry_run_from_stage(tmp_path, capsys):
    make(_opts(tmp_path, dry_run=True, from_stage="deck"), KitConfig(), _hooks(engine=FakeTTS()))
    out = capsys.readouterr().out
    assert "1. deck（" in out and "capture（" not in out


# ------------------------------------------------------------------ --from

def test_failed_stage_records_resume_and_from_continues(tmp_path):
    media = FakeMedia(fail_capture=True)
    with pytest.raises(MakeStop, match="capture"):
        make(_opts(tmp_path), KitConfig(), _hooks(media, engine=FakeTTS()), log=lambda s: None)
    out = tmp_path / "out" / "20261106_hello-kit"
    run = _run_json(out)
    assert run["status"] == "failed" and run["stages"]["capture"]["status"] == "failed"
    assert "要素が見つからない" in run["stages"]["capture"]["error"]
    assert "--from capture" in run["resume"] and str(out) in run["resume"]
    assert "voice" not in run["stages"]

    # 直して、その段から（同じフォルダ。--out-dir を省略すると、この台本の最後の実行を探す）
    tts = FakeTTS()
    res = make(_opts(tmp_path, from_stage="capture"), KitConfig(), _hooks(FakeMedia(), engine=tts), log=lambda s: None)
    assert res.out_dir == out and res.status == "needs_export"
    run = _run_json(out)
    assert run["stages"]["capture"]["status"] == "ok" and run["resumed"][0]["from"] == "capture"
    assert tts.spoken


def test_from_skips_earlier_stages(tmp_path):
    first = make(_opts(tmp_path), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    media, tts = FakeMedia(), FakeTTS()
    make(_opts(tmp_path, from_stage="deck", out_dir=first.out_dir), KitConfig(), _hooks(media, engine=tts),
         log=lambda s: None)
    assert media.calls == [] and tts.spoken == []
    run = _run_json(first.out_dir)
    assert run["resumed"][-1]["from"] == "deck" and run["stages"]["deck"]["status"] == "ok"


def test_from_needs_a_previous_run(tmp_path):
    with pytest.raises(MakeError, match="再開できる前回の実行がありません"):
        make(_opts(tmp_path, from_stage="voice"), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)


def test_from_refuses_when_an_earlier_stage_did_not_finish(tmp_path):
    with pytest.raises(MakeStop):
        make(_opts(tmp_path), KitConfig(), _hooks(FakeMedia(fail_capture=True), engine=FakeTTS()), log=lambda s: None)
    with pytest.raises(MakeError, match="--from capture を使って"):
        make(_opts(tmp_path, from_stage="voice"), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)


def test_from_must_be_a_stage(tmp_path):
    with pytest.raises(MakeError, match="--from には"):
        Maker(_opts(tmp_path, from_stage="publish"))


# ------------------------------------------------------------------ 社外秘・--offline

def _confidential(tmp_path, **reel) -> Path:
    doc = sb.load_storyboard(EXAMPLE)
    doc["reel"]["confidentiality"] = "confidential"
    doc["reel"].update(reel)
    path = tmp_path / "secret.storyboard.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def confidential(tmp_path):
    return _confidential(tmp_path)


def test_confidential_with_local_settings_runs_and_records(tmp_path, confidential):
    res = make(_opts(tmp_path, storyboard=confidential), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    run = _run_json(res.out_dir)
    assert run["confidentiality"] == "confidential"
    items = {c["item"]: c for c in run["network_checks"]}
    assert all(c["ok"] for c in items.values())
    assert items["音声合成エンジン（aivisspeech）"]["value"] == "http://127.0.0.1:10101"
    assert items["撮影の URL（s03）"]["value"].startswith("http://127.0.0.1:")
    assert items["LLM"]["value"].startswith("使わない")


@pytest.mark.parametrize("opt, bad", [
    ({"engine_url": "http://192.168.1.10:10101"}, "音声合成エンジン"),
    ({"serve": None, "url_map": [("http://127.0.0.1:8000/", "https://tool.example.com/")]}, "撮影の URL（s03）"),
])
def test_confidential_stops_before_creating_anything(tmp_path, confidential, opt, bad, capsys):
    media, tts = FakeMedia(), FakeTTS()
    with pytest.raises(MakeStop, match="この PC の外"):
        make(_opts(tmp_path, storyboard=confidential, **opt), KitConfig(), _hooks(media, engine=tts))
    assert media.calls == [] and tts.spoken == []
    assert not (tmp_path / "out").exists() and not (tmp_path / "caps").exists()
    out = capsys.readouterr().out
    assert bad in out and "reel.confidentiality を general" in out


def test_confidential_engine_url_from_config_is_checked(tmp_path, confidential):
    with pytest.raises(MakeStop):
        make(_opts(tmp_path, storyboard=confidential), KitConfig(voice_url="http://tts.example.com"),
             _hooks(engine=FakeTTS()), log=lambda s: None)


def test_unwritten_confidentiality_is_confidential(tmp_path):
    doc = sb.load_storyboard(EXAMPLE)
    del doc["reel"]["confidentiality"]
    path = tmp_path / "unwritten.storyboard.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(MakeStop):
        make(_opts(tmp_path, storyboard=path, engine_url="http://10.0.0.5:10101"), KitConfig(),
             _hooks(engine=FakeTTS()), log=lambda s: None)


def test_dry_run_also_checks_confidential(tmp_path, confidential):
    with pytest.raises(MakeStop):
        make(_opts(tmp_path, storyboard=confidential, dry_run=True, engine_url="http://10.0.0.5:10101"), KitConfig(),
             _hooks(engine=FakeTTS()), log=lambda s: None)


def test_offline_applies_to_general_storyboards(tmp_path):
    with pytest.raises(MakeStop, match="--offline"):
        make(_opts(tmp_path, offline=True, engine_url="http://10.0.0.5:10101"), KitConfig(),
             _hooks(engine=FakeTTS()), log=lambda s: None)
    res = make(_opts(tmp_path, offline=True), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    run = _run_json(res.out_dir)
    assert run["offline"] is True and run["confidentiality"] == "general" and run["network_checks"]


def test_general_storyboard_may_use_a_remote_engine(tmp_path):
    res = make(_opts(tmp_path, engine_url="http://10.0.0.5:10101"), KitConfig(), _hooks(engine=FakeTTS()),
               log=lambda s: None)
    assert _run_json(res.out_dir)["network_checks"] is None


# ------------------------------------------------------------------ 前提の確かめ（実物の確認関数）

def test_prerequisites_stop_before_anything(tmp_path, capsys):
    """既定の声がエンジンに無い・PowerPoint が無い → 何も作らずに止め、足りないものをまとめて表示する。"""
    engine = FakeEngine()
    media = FakeMedia()
    hooks = Hooks(capture=media.capture, diagram=media.diagram, transport=engine, now=lambda: NOW)
    with pytest.raises(MakeStop, match="前提が足りません"):
        make(_opts(tmp_path, speaker=12345, platform="win32"), KitConfig(), hooks)
    assert media.calls == [] and not (tmp_path / "out").exists()
    out = capsys.readouterr().out
    assert "声 12345 がエンジンにありません" in out and "PowerPoint" in out and "erkit doctor" in out


def test_prerequisites_pass_with_fake_engine(tmp_path):
    hooks = Hooks(capture=FakeMedia().capture, diagram=FakeMedia().diagram, transport=FakeEngine(), now=lambda: NOW)
    res = make(_opts(tmp_path), KitConfig(), hooks, log=lambda s: None)
    run = _run_json(res.out_dir)
    assert res.status == "needs_export" and all(v == "ok" for v in run["prereq"].values())
    assert any("Web の操作定義" in k for k in run["prereq"])


def test_missing_actions_file_is_a_prerequisite(tmp_path, capsys):
    hooks = Hooks(capture=FakeMedia().capture, diagram=FakeMedia().diagram, transport=FakeEngine(), now=lambda: NOW)
    with pytest.raises(MakeStop):
        make(_opts(tmp_path, actions=tmp_path / "none.actions.yaml"), KitConfig(), hooks)
    assert "erkit record" in capsys.readouterr().out


def test_engine_down_is_a_prerequisite(tmp_path, capsys):
    hooks = Hooks(capture=FakeMedia().capture, diagram=FakeMedia().diagram, transport=_down, now=lambda: NOW)
    with pytest.raises(MakeStop):
        make(_opts(tmp_path), KitConfig(), hooks)
    assert "AivisSpeech" in capsys.readouterr().out


def _down(method, url, headers, body, timeout):
    from explainer_reel_kit.narration.tts.aivisspeech import TransportConnectionError

    raise TransportConnectionError("connection refused")


# ------------------------------------------------------------------ 画像・注釈の不足

def test_placeholders_stop_unless_allowed(tmp_path):
    class NoDiagram(FakeMedia):
        def diagram(self, *a, **k):
            return {"ok": 0, "failed": 0, "scenes": []}

    with pytest.raises(MakeStop, match="画像の無いシーン"):
        make(_opts(tmp_path), KitConfig(), _hooks(NoDiagram(), engine=FakeTTS()), log=lambda s: None)
    res = make(_opts(tmp_path, allow_placeholders=True), KitConfig(), _hooks(NoDiagram(), engine=FakeTTS()),
               log=lambda s: None)
    run = _run_json(res.out_dir)
    assert run["stages"]["assets"]["placeholders"] == 4 and any("灰色の枠" in w for w in run["warnings"])


def test_assets_root_skips_capture(tmp_path):
    root = tmp_path / "assets"
    doc = sb.load_storyboard(EXAMPLE)
    for s in doc["scenes"]:
        _png_with_marks(root / s["image"]["ref"], s)
    media = FakeMedia()
    res = make(_opts(tmp_path, assets_root=root), KitConfig(), _hooks(media, engine=FakeTTS()), log=lambda s: None)
    run = _run_json(res.out_dir)
    assert run["stages"]["capture"]["status"] == "skipped" and "assets-root" in run["stages"]["capture"]["reason"]
    assert run["stages"]["assets"]["found"] == 5


def test_no_capture_uses_existing_captures(tmp_path):
    doc = sb.load_storyboard(EXAMPLE)
    s03 = next(s for s in doc["scenes"] if s["id"] == "s03")
    _png_with_marks(tmp_path / "caps" / "web" / "hello-kit" / s03["image"]["ref"], s03)
    media = FakeMedia()
    res = make(_opts(tmp_path, no_capture=True), KitConfig(), _hooks(media, engine=FakeTTS()), log=lambda s: None)
    assert [c[0] for c in media.calls] == ["diagram"]
    assert _run_json(res.out_dir)["stages"]["assets"]["found"] == 5


# ------------------------------------------------------------------ CLI

def test_cli_dry_run_and_errors(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "kit.yaml"
    cfg.write_text(f"output_root: {json.dumps(str(tmp_path / 'o'))}\n", encoding="utf-8")
    assert erkit(["make", str(EXAMPLE), "--dry-run", "--config", str(cfg), "--serve", str(EXAMPLES / "hello-page")]) == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert erkit(["make", str(EXAMPLE), "--from", "publish"]) == 2
    assert erkit(["make", str(tmp_path / "none.storyboard.md"), "--config", str(cfg)]) == 2
    assert erkit(["make", str(EXAMPLE), "--config", str(cfg), "--serve", str(tmp_path / "nothing")]) == 2
    assert erkit(["make", str(EXAMPLE), "--config", str(cfg), "--url-map", "no-equals"]) == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("voice: [1]\n", encoding="utf-8")
    assert erkit(["make", str(EXAMPLE), "--config", str(bad)]) == 2


def test_cli_runs_with_hooks(tmp_path, capsys):
    cfg = tmp_path / "kit.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    parser = make_cli.configure(__import__("argparse").ArgumentParser())
    args = parser.parse_args([str(EXAMPLE), "--config", str(cfg), "--output-root", str(tmp_path / "o"),
                              "--captures-root", str(tmp_path / "c"), "--serve", str(EXAMPLES / "hello-page")])
    assert make_cli.run(args, hooks=_hooks(engine=FakeTTS()), platform="linux") == 0
    args = parser.parse_args([str(EXAMPLE), "--config", str(cfg), "--output-root", str(tmp_path / "o"),
                              "--engine-url", "http://10.0.0.9:10101", "--offline"])
    assert make_cli.run(args, hooks=_hooks(engine=FakeTTS()), platform="linux") == 1
    assert "--offline" in capsys.readouterr().err
