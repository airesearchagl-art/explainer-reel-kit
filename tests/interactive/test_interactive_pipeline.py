"""erkit make から呼ぶ入口（interactive.pipeline）: ナレーション → .pptx（python-pptx）→ render_storyboard → mux →
verify_storyboard。PowerPoint を使わずに MP4 まで作れること、字幕の SRT と焼き込みが同じフレームで切り替わること、
描画はネットワークを使わず、静止画は台本のフォルダと出力フォルダの中だけを読むこと。

ナレーションは偽の音声合成エンジン（文ごとに音と無音）。ffmpeg が無ければ飛ばす。尺は短い（20 秒ほど）。
"""
from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest
from interactive_helpers import SentenceEngine
from PIL import Image, ImageDraw
from reel_helpers import needs_ffmpeg

from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.deck.builder import build_deck
from explainer_reel_kit.interactive import engine as ie
from explainer_reel_kit.interactive.engine import LayoutError
from explainer_reel_kit.interactive.pipeline import (InteractiveError, InteractivePaths, precheck_scenes,
                                                     render_storyboard, verify_storyboard)
from explainer_reel_kit.interactive.subtitles import parse_srt, srt_frame
from explainer_reel_kit.narration.adapter import slide_ids, storyboard_to_narration_input
from explainer_reel_kit.narration.synth import parse_input, run_synth
from explainer_reel_kit.narration.tts import get_engine
from explainer_reel_kit.reel.mux import mux

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "interactive"
STORYBOARD = FIXTURES / "window-condensation.storyboard.json"
QUIET = lambda s: None  # noqa: E731


def _png(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1600, 900), "#f4f6f8")
    d = ImageDraw.Draw(im)
    d.rectangle((100, 100, 1500, 800), outline="#1c2b3a", width=3)
    d.text((140, 140), label, fill="#1c2b3a")
    im.save(path)


def _reel_folder(tmp_path: Path, with_spec: bool = True) -> Path:
    """台本のフォルダ（台本・画像・scenes/<reel id>/scenes.yaml）。s02 は scenes.yaml、s03 も scenes.yaml。"""
    d = tmp_path / "reel"
    d.mkdir(parents=True)
    story = d / STORYBOARD.name
    shutil.copy(STORYBOARD, story)
    _png(d / "assets" / "s02.png", "s02")
    _png(d / "assets" / "s03.png", "s03")
    if with_spec:
        sd = d / "scenes" / "window-condensation"
        sd.mkdir(parents=True)
        shutil.copy(FIXTURES / "window-condensation" / "scenes.yaml", sd / "scenes.yaml")
        shutil.copy(FIXTURES / "window-condensation" / "verify.yaml", sd / "verify.yaml")
    return story


def _voice_and_deck(story: Path, out: Path) -> tuple[dict, InteractivePaths]:
    """erkit make の voice・assets・deck の段と同じ置き場に、ナレーションと .pptx を作る。"""
    doc = sb.load_storyboard(story)
    paths = InteractivePaths(out, doc["reel"]["output_name"])
    paths.work.mkdir(parents=True)
    ni = storyboard_to_narration_input(doc)
    paths.narration_input.write_text(json.dumps(ni, ensure_ascii=False), encoding="utf-8")
    eng = get_engine("aivisspeech", "http://127.0.0.1:10101", transport=SentenceEngine())
    run_synth(parse_input(ni), paths.narration_dir, eng, log=QUIET)
    for ref in ("assets/s02.png", "assets/s03.png"):   # assets の段の複製（work/assets/<image.ref>）
        (paths.assets / ref).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(story.parent / ref, paths.assets / ref)
    build_deck(story, paths.pptx, durations=paths.durations, assets_root=paths.assets)
    return doc, paths


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg が要ります")
    tmp = tmp_path_factory.mktemp("pipeline")
    story = _reel_folder(tmp)
    out = tmp / "out"
    doc, paths = _voice_and_deck(story, out)
    pre = precheck_scenes(story, doc, log=QUIET)
    # 描画の間はネットワークを使えないようにする（使えば失敗する）
    real = socket.socket

    def no_network(*a, **kw):
        raise AssertionError("interactive の描画がネットワークを使おうとしました")

    socket.socket = no_network
    try:
        info = render_storyboard(story, doc, out, credit="テストの声", jobs=1, log=QUIET)
    finally:
        socket.socket = real
    res = mux(paths.silent_mp4, paths.pptx, slide_ids(doc), paths.durations, paths.final_mp4, overwrite=True)
    ver = verify_storyboard(out, paths.stem, Path(info["scenes_dir"]), storyboard=story, log=QUIET)
    return {"story": story, "doc": doc, "paths": paths, "pre": pre, "info": info, "mux": res, "verify": ver}


@needs_ffmpeg
def test_mp4_is_made_without_powerpoint_and_verify_passes(built):
    paths, info, ver = built["paths"], built["info"], built["verify"]
    assert built["pre"]["status"] == "ok"
    assert paths.silent_mp4.is_file() and paths.final_mp4.is_file()
    assert ver["ok"] and ver["status"] == "ok" and ver["failed"] == [], ver
    assert Path(ver["report"]).is_file() and Path(ver["result"]).is_file()
    assert info["scenes_dir"] == str((built["story"].parent / "scenes" / "window-condensation").resolve())
    assert info["render"]["scenes"]["sources"]["s02"] == "scenes.yaml"
    assert info["render"]["scenes"]["sources"]["intro"] == "default"
    assert info["network"].startswith("使わない")
    for key in ("timeline", "pauses", "srt", "silent_mp4"):
        assert Path(info[key]).is_file(), key


@needs_ffmpeg
def test_scene_boundaries_follow_the_slide_times_like_slides(built):
    """場面の境界は .pptx のスライドの時刻（slides と同じ）。音声は mux と同じ位置。"""
    from explainer_reel_kit.reel.mux import read_slide_timings

    paths, doc = built["paths"], built["doc"]
    tl = json.loads(paths.render_timeline.read_text(encoding="utf-8"))
    timings = read_slide_timings(paths.pptx, slide_ids(doc))
    import math

    assert [s["id"] for s in tl["scenes"]] == [t.id for t in timings]
    assert [s["start_frame"] for s in tl["scenes"]] == [math.ceil(t.start_ms * 30 / 1000 - 1e-6) for t in timings]
    durations = json.loads(paths.durations.read_text(encoding="utf-8"))
    pre = durations["pre_pause_sec"]
    first = {e["scene"]: e["start_sec"] for e in reversed(tl["sentences"])}
    for t in timings:
        assert first[t.id] == pytest.approx((t.start_ms + t.transition_ms) / 1000 + pre, abs=1e-3), t.id
    assert tl["meta"]["credit"] == "テストの声"


@needs_ffmpeg
def test_srt_and_burned_subtitles_switch_on_the_same_frames(built):
    paths = built["paths"]
    tl = json.loads(paths.render_timeline.read_text(encoding="utf-8"))
    srt = parse_srt(paths.srt)
    assert paths.srt == paths.final_mp4.with_suffix(".srt")
    assert [(srt_frame(s["start_ms"]), srt_frame(s["end_ms"])) for s in srt] == \
        [(c["start_frame"], c["end_frame"]) for c in tl["cues"]]
    assert all(len(c["lines"]) == 1 or c["lines"][0][-1] in "、。" for c in tl["cues"])
    ver = json.loads((paths.checks / "verify.json").read_text(encoding="utf-8"))
    so = ver["subtitles"]["srt_output"]
    assert so["ok"] and so["frames_equal_cues"] and ver["subtitles"]["mismatched_frames"] == 0
    # 文の時刻は WAV から測る（ナレーションの段の記録 chunk_frames・chunk_sentences を使う）
    assert {e["timing"] for e in tl["sentences"]} == {"measured"}
    assert (paths.checks / "resync.md").is_file() and paths.pauses.is_file()


@needs_ffmpeg
def test_existing_silent_mp4_needs_force(built):
    with pytest.raises(InteractiveError, match="--force"):
        render_storyboard(built["story"], built["doc"], built["paths"].out_dir, jobs=1, log=QUIET)


def test_scenes_outside_the_storyboard_folder_are_refused(tmp_path):
    story = _reel_folder(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(InteractiveError) as e:
        render_storyboard(story, sb.load_storyboard(story), tmp_path / "out", scenes_dir=other, log=QUIET)
    assert e.value.exit_code == 2


def test_images_are_read_only_from_allowed_folders(tmp_path):
    inside = tmp_path / "reel" / "a.png"
    outside = tmp_path / "elsewhere" / "b.png"
    _png(inside, "a")
    _png(outside, "b")
    try:
        ie.set_asset_roots([tmp_path / "reel"])
        assert ie.asset_size(str(inside)) == (1600, 900)
        with pytest.raises(LayoutError, match="台本のフォルダか出力フォルダの中"):
            ie.asset_size(str(outside))
        ie.set_asset_dirs([tmp_path / "reel"])
        with pytest.raises(LayoutError, match="台本のフォルダか出力フォルダの中"):
            ie.asset_size("../elsewhere/b.png")
        with pytest.raises(LayoutError, match="URL"):
            ie.asset_size("https://example.com/a.png")
    finally:
        ie.set_asset_roots([])
        ie.set_asset_dirs([])
