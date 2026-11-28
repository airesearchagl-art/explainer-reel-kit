"""erkit make のナレーションの段: 前の出力の WAV の使い回し（reuse_run）と固定尺の枠（slot_sec）。

本物の AivisSpeech・PowerPoint は使わない（偽の音声 FakeTTS・偽の撮影と説明図）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import EXAMPLE
from narration_fakes import FakeTTS
from reel_helpers import FakeEngine
from test_make import FakeMedia, _hooks, _opts, _run_json

from explainer_reel_kit.config import KitConfig
from explainer_reel_kit.reel.make import MakeError, MakeStop, make


def _example_copy(tmp_path: Path, edit=None) -> Path:
    """例のフォルダを tmp に写し、台本を書き換える（リポジトリのファイルは変えない）。"""
    root = tmp_path / "examples"
    shutil.copytree(EXAMPLE.parent, root)
    sb_path = root / EXAMPLE.name
    if edit is not None:
        sb_path.write_text(edit(sb_path.read_text(encoding="utf-8")), encoding="utf-8")
    return sb_path


def _durations(out_dir: Path) -> dict:
    return json.loads((out_dir / "work" / "narration" / "durations.json").read_text(encoding="utf-8"))


def test_reuse_run_copies_unchanged_wavs(tmp_path):
    first = make(_opts(tmp_path), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    tts = FakeTTS()
    second = make(_opts(tmp_path, reuse_run=first.out_dir), KitConfig(), _hooks(engine=tts), log=lambda s: None)
    assert tts.spoken == []  # 台本が同じなら 1 つも合成しない
    voice = _run_json(second.out_dir)["stages"]["voice"]
    assert voice["status"] == "ok" and voice["reuse_from"] == str(first.out_dir / "work" / "narration")
    assert voice["synthesized"] == {}
    items = _durations(second.out_dir)["items"]
    assert all(i["reused_from"] == str(first.out_dir / "work" / "narration") for i in items)
    for i in items:
        assert (second.out_dir / "work" / "narration" / i["wav"]).read_bytes() == \
            (first.out_dir / "work" / "narration" / i["wav"]).read_bytes()


def test_reuse_run_resynthesizes_only_the_changed_paragraph(tmp_path):
    sb_path = _example_copy(tmp_path)
    opts = dict(storyboard=sb_path, serve=sb_path.parent / "hello-page")
    first = make(_opts(tmp_path, **opts), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    doc_text = sb_path.read_text(encoding="utf-8")
    assert doc_text.rstrip().endswith("。")  # 最後は outro のナレーションの段落
    sb_path.write_text(doc_text.rstrip() + "\n\n最後に足した段落です。\n", encoding="utf-8")
    tts = FakeTTS()
    second = make(_opts(tmp_path, reuse_run=first.out_dir, **opts), KitConfig(), _hooks(engine=tts), log=lambda s: None)
    assert [s[0] for s in tts.spoken] == ["最後に足した段落です。"]
    voice = _run_json(second.out_dir)["stages"]["voice"]
    assert list(voice["synthesized"]) == ["outro"] and voice["synthesized"]["outro"][-1] >= 2


def test_reuse_run_needs_a_previous_output(tmp_path):
    (tmp_path / "old").mkdir()
    with pytest.raises(MakeError, match="work/narration/durations.json"):
        make(_opts(tmp_path, reuse_run=tmp_path / "old"), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    assert not (tmp_path / "out").exists()  # 出力フォルダを作る前に止める


def test_resume_command_keeps_reuse_run(tmp_path):
    first = make(_opts(tmp_path), KitConfig(), _hooks(engine=FakeTTS()), log=lambda s: None)
    with pytest.raises(MakeStop):
        make(_opts(tmp_path, reuse_run=first.out_dir), KitConfig(), _hooks(FakeMedia(fail_capture=True), engine=FakeTTS()),
             log=lambda s: None)
    failed = sorted((tmp_path / "out").iterdir())[-1]
    assert f"--reuse-run {first.out_dir}" in _run_json(failed)["resume"]


def _with_slot(seconds: float):
    def edit(text: str) -> str:
        text = text.replace("schema_version: kit-1.0.0", "schema_version: kit-1.2.0", 1)
        head = "## outro\n```yaml\n"
        assert head in text
        return text.replace(head, head + f"slot_sec: {seconds}\n", 1)
    return edit


def test_slot_sec_sets_the_slide_seconds(tmp_path):
    sb_path = _example_copy(tmp_path, _with_slot(30))
    res = make(_opts(tmp_path, storyboard=sb_path, serve=sb_path.parent / "hello-page"), KitConfig(),
               _hooks(engine=FakeTTS()), log=lambda s: None)
    outro = next(i for i in _durations(res.out_dir)["items"] if i["id"] == "outro")
    assert outro["slide_sec"] == 30.0 and outro["fit"]["slot_sec"] == 30 and outro["wav"] == "outro.wav"
    voice = _run_json(res.out_dir)["stages"]["voice"]
    assert voice["slots"]["outro"]["slot_sec"] == 30 and "source" not in voice["slots"]["outro"]


def test_slot_sec_overflow_stops_at_the_voice_stage(tmp_path):
    sb_path = _example_copy(tmp_path, _with_slot(0.5))
    with pytest.raises(MakeStop, match="固定尺の枠"):  # 声のある WAV（偽の AivisSpeech）なので詰めきれない
        make(_opts(tmp_path, storyboard=sb_path, serve=sb_path.parent / "hello-page"), KitConfig(),
             _hooks(transport=FakeEngine()), log=lambda s: None)
    out = sorted((tmp_path / "out").iterdir())[-1]
    run = _run_json(out)
    assert run["stages"]["voice"]["status"] == "failed" and "outro: 枠 0.50 秒" in run["stages"]["voice"]["error"]
    assert "--from voice" in run["resume"]
