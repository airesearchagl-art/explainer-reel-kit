"""音声の合成（mux）と、通し生成の後半（スライド → 書き出し → 合成）。

書き出しは PowerPoint の代わりに ffmpeg で黒い無音の MP4 を作る。ナレーションは偽の AivisSpeech（音が鳴る WAV）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pptx import Presentation

from deck_helpers import SAMPLES, WEB_MARK_BOXES, scene_mark_names, variant, write_marks
from reel_helpers import CREDIT_VOICE_ID, FakeEngine, ffprobe_sec, make_black_video, needs_ffmpeg, silence_ends

from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.config import KitConfig, VoiceCredit
from explainer_reel_kit.narration.adapter import slide_ids
from explainer_reel_kit.reel.make import Hooks, MakeError, MakeOptions, MakeStop, Maker
from explainer_reel_kit.reel.mux import (
    MAX_MORPH_EXTRA_SEC,
    MuxError,
    Segment,
    build_ffmpeg_command,
    count_morphs,
    expected_total_sec,
    morph_drift,
    plan_segments,
    pptx_total_sec,
    read_slide_timings,
)

WEB = SAMPLES["web"]
RECIPES = SAMPLES["recipes"]


def _fake_exporter(extra_sec: float = 0.0, calls: list | None = None):
    """PowerPoint の代わりに、.pptx の合計秒数（＋extra）の黒い無音 MP4 を作る。"""

    def run(pptx: Path, out: Path, force: bool):
        make_black_video(out, pptx_total_sec(pptx) + extra_sec)
        if calls is not None:
            calls.append((pptx, out, force))
        return {"status": "done"}

    return run


@dataclass
class Built:
    maker: Maker
    status: str

    @property
    def out(self) -> Path:
        return self.maker.out_dir

    @property
    def pptx(self) -> Path:
        return self.out / f"{self.maker.stem}.pptx"

    @property
    def durations(self) -> Path:
        return self.out / "work" / "narration" / "durations.json"

    @property
    def narration_dir(self) -> Path:
        return self.durations.parent

    @property
    def silent_mp4(self) -> Path:
        return self.out / "work" / f"{self.maker.stem}.silent.mp4"

    @property
    def final_mp4(self) -> Path:
        return self.out / f"{self.maker.stem}.mp4"

    @property
    def run(self) -> dict:
        return json.loads((self.out / "run.json").read_text(encoding="utf-8"))

    @property
    def warnings(self) -> list[str]:
        return self.run["warnings"]


def _build(tmp_path, storyboard=WEB, *, platform="linux", exporter=None, captures_root=None,
           allow_placeholders=True, cfg=None, transport=None):
    opts = MakeOptions(storyboard=Path(storyboard), out_dir=tmp_path / "out", output_root=tmp_path,
                       captures_root=captures_root or tmp_path / "no-captures",
                       allow_placeholders=allow_placeholders, platform=platform, no_capture=True)
    m = Maker(opts, cfg or KitConfig(), Hooks(transport=transport or FakeEngine(), exporter=exporter,
                                              checks=lambda maker, stages: []), log=lambda s: None)
    res = m.execute()
    return Built(m, res.status)


def _doc(path=WEB):
    return sb.load_storyboard(path)


# ------------------------------------------------------------------ 通し（Windows 以外）

def test_non_windows_stops_after_deck_with_steps(tmp_path):
    res = _build(tmp_path)
    assert res.status == "needs_export"
    assert (res.out / "work" / "narration-input.json").is_file() and res.durations.is_file() and res.pptx.is_file()
    assert not res.silent_mp4.exists() and not res.final_mp4.exists()
    steps = res.run["next_steps"]
    assert any("Export-PptxToVideo.ps1" in s for s in steps) and any("--from export" in s for s in steps)
    assert res.run["stages"]["export"]["status"] == "skipped"
    # 自動切替はナレーションの slide_sec どおり
    by_id = {it["id"]: it["slide_sec"] for it in json.loads(res.durations.read_text(encoding="utf-8"))["items"]}
    timings = read_slide_timings(res.pptx, slide_ids(_doc()))
    assert [t.adv_ms for t in timings] == [int(round(by_id[i] * 1000)) for i in slide_ids(_doc())]


@pytest.mark.parametrize("key", ["web", "generated"])
def test_no_credit_by_default(tmp_path, key):
    res = _build(tmp_path, SAMPLES[key])
    assert res.run["credit"] is None and res.run["speaker"] == 808373280
    assert not [w for w in res.warnings if "クレジット" in w]


def test_default_speaker_is_used_for_synthesis(tmp_path):
    engine = FakeEngine()
    res = _build(tmp_path, transport=engine)
    assert res.run["speaker"] == 808373280 and set(engine.speaker_ids) == {808373280}


def test_credit_voice_puts_credit_on_outro_automatically(tmp_path):
    def edit(doc):
        doc["reel"]["voice"] = {"speaker": CREDIT_VOICE_ID}
    cfg = KitConfig(credits=[VoiceCredit("テストの声", "テストの声のクレジット", (CREDIT_VOICE_ID,))])
    engine = FakeEngine()
    res = _build(tmp_path, variant("web", tmp_path, edit), cfg=cfg, transport=engine)
    assert res.run["credit"] == "テストの声のクレジット" and set(engine.speaker_ids) == {CREDIT_VOICE_ID}
    assert res.run["stages"]["deck"]["credit"] == "テストの声のクレジット"
    outro = Presentation(str(res.pptx)).slides[-1]
    assert any(sh.has_text_frame and sh.text_frame.text == "ナレーション音声: テストの声のクレジット" for sh in outro.shapes)


def test_narration_failure_stops_and_is_recorded(tmp_path):
    def edit(doc):
        doc["reel"]["voice"] = {"speaker": 99999}
    with pytest.raises(MakeStop, match="voice"):
        _build(tmp_path, variant("web", tmp_path, edit))
    out = tmp_path / "out"
    assert not list(out.glob("*.pptx"))
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed" and run["stages"]["voice"]["status"] == "failed"
    assert "--from voice" in run["resume"]


def test_speaker_name_is_rejected_before_anything(tmp_path):
    def edit(doc):
        doc["reel"]["voice"] = {"speaker": "ほのか"}
    with pytest.raises(MakeError, match="erkit voice list"):
        _build(tmp_path, variant("web", tmp_path, edit))
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------ タイミングと ffmpeg コマンド

def test_morph_transition_adds_time(tmp_path):
    res = _build(tmp_path, RECIPES)
    doc = _doc(RECIPES)
    ids = slide_ids(doc)
    t1 = read_slide_timings(res.pptx, ids)
    t2 = read_slide_timings(res.pptx, ids, transition_before_timer=False)
    morph = [i for i, s in enumerate(doc["scenes"], 1) if s["recipe"] == "morph_transition"][0]
    assert t1[morph].transition_ms == 1000 and all(t.transition_ms == 0 for i, t in enumerate(t1) if i != morph)
    assert expected_total_sec(t1) == pytest.approx(expected_total_sec(t2, False) + 1.0)
    assert t1[morph + 1].start_ms == t2[morph + 1].start_ms + 1000


def test_slide_count_mismatch_is_an_error(tmp_path):
    res = _build(tmp_path)
    with pytest.raises(MuxError, match="一致しません"):
        read_slide_timings(res.pptx, ["intro", "outro"])


def test_ffmpeg_command_copies_video_and_concats_audio(tmp_path):
    segs = [Segment("intro", tmp_path / "intro.wav", 0.3, 2.0), Segment("s01", tmp_path / "s01.wav", 3.1, 1.5)]
    cmd, warnings = build_ffmpeg_command("ffmpeg", tmp_path / "v.mp4", segs, 6.0, tmp_path / "o.mp4")
    assert warnings == []
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd.count("-i") == 3 and "-n" in cmd and "-y" not in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    # 無音 0.3 → intro → 無音 0.8 → s01 → 無音 1.4（合計 6.0）
    assert "atrim=duration=0.300" in fc and "atrim=duration=0.800" in fc and "atrim=duration=1.400" in fc
    assert "[1:a]" in fc and "[2:a]" in fc and "concat=n=5:v=0:a=1[aout]" in fc
    assert cmd[cmd.index("-map") + 1] == "0:v:0"


def test_ffmpeg_command_warns_on_overlap_and_overrun(tmp_path):
    segs = [Segment("a", tmp_path / "a.wav", 0.0, 3.0), Segment("b", tmp_path / "b.wav", 2.0, 3.0)]
    _, warnings = build_ffmpeg_command("ffmpeg", tmp_path / "v.mp4", segs, 5.0, tmp_path / "o.mp4", overwrite=True)
    assert any("重なる" in w for w in warnings) and any("映像" in w and "長く" in w for w in warnings)


def test_plan_segments_places_wav_after_pre_pause(tmp_path):
    res = _build(tmp_path)
    ids = slide_ids(_doc())
    timings = read_slide_timings(res.pptx, ids)
    durations = json.loads(res.durations.read_text(encoding="utf-8"))
    segs, warnings = plan_segments(timings, durations, res.narration_dir)
    assert [s.id for s in segs] == ids and warnings == []
    for s, t in zip(segs, timings):
        assert s.start_sec == pytest.approx((t.start_ms + t.transition_ms) / 1000 + durations["pre_pause_sec"], abs=0.002)


# ------------------------------------------------------------------ 実際に ffmpeg で合成

@needs_ffmpeg
def test_windows_flow_produces_narrated_mp4(tmp_path):
    calls = []
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(calls=calls))
    assert res.status == "done" and calls and calls[0][2] is True
    for f in (res.durations, res.pptx, res.silent_mp4, res.final_mp4):
        assert f.is_file(), f
    v, a = ffprobe_sec(res.final_mp4, "v:0"), ffprobe_sec(res.final_mp4, "a:0")
    assert abs(v - a) <= 0.2
    assert not [w for w in res.warnings if "ずれ" in w]
    timings = read_slide_timings(res.pptx, slide_ids(_doc()))
    durations = json.loads(res.durations.read_text(encoding="utf-8"))
    expected = [(t.start_ms + t.transition_ms) / 1000 + durations["pre_pause_sec"] for t in timings]
    starts = [s for s in silence_ends(res.final_mp4) if s < v - 0.05]  # 末尾の無音は除く
    assert len(starts) == len(expected)
    for got, exp in zip(starts, expected):
        assert got == pytest.approx(exp, abs=0.1)
    assert res.run["status"] == "done" and res.run["files"]["mp4"] == str(res.final_mp4)


@needs_ffmpeg
def test_video_length_mismatch_warns(tmp_path):
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(extra_sec=1.0))
    assert any("ずれています" in w and "無音 MP4" in w for w in res.warnings)
    v, a = ffprobe_sec(res.final_mp4, "v:0"), ffprobe_sec(res.final_mp4, "a:0")
    assert abs(v - a) <= 0.2


@needs_ffmpeg
def test_resume_from_export_after_needs_export(tmp_path):
    """Windows 以外で .pptx まで → Windows で --from export から MP4 まで（書き出し・合成だけを行う）。"""
    first = _build(tmp_path)
    assert first.status == "needs_export"
    engine = FakeEngine()
    opts = MakeOptions(storyboard=WEB, out_dir=first.out, output_root=tmp_path, from_stage="export", platform="win32",
                       captures_root=tmp_path / "no-captures", no_capture=True)
    m = Maker(opts, KitConfig(), Hooks(transport=engine, exporter=_fake_exporter(), checks=lambda mk, st: []),
              log=lambda s: None)
    assert m.execute().status == "done"
    assert engine.speaker_ids == []  # ナレーションは作り直さない
    run = json.loads((first.out / "run.json").read_text(encoding="utf-8"))
    assert run["stages"]["export"]["status"] == "ok" and run["stages"]["mux"]["status"] == "ok"
    assert run["stages"]["voice"]["status"] == "ok" and run["resumed"][0]["from"] == "export"
    assert Path(run["files"]["mp4"]).is_file()


# ------------------------------------------------------------------ zoom: per_mark

def _shoot_with_marks(root: Path):
    """Web 撮影の画像と marks.json を用意する（撮影の代わり）。"""
    from PIL import Image

    for s in _doc()["scenes"]:
        img = root / s["image"]["ref"]
        img.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), (220, 225, 230)).save(img)
        write_marks(img, s["id"], {n: WEB_MARK_BOXES[n] for n in scene_mark_names(s)})


def _captures(tmp_path) -> Path:
    root = tmp_path / "caps"
    _shoot_with_marks(root / "web" / _doc()["reel"]["id"])
    return root


@needs_ffmpeg
def test_split_scenes_keep_narration_on_the_scene_start(tmp_path, monkeypatch):
    import reel_helpers

    monkeypatch.setattr(reel_helpers, "SEC_PER_CHAR", 0.08)  # 分けたスライドの動きが収まる長さのナレーション
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(), captures_root=_captures(tmp_path),
                 allow_placeholders=False)
    doc = _doc()
    timings = read_slide_timings(res.pptx, slide_ids(doc))
    assert [t.id for t in timings] == slide_ids(doc)
    split = {t.id: t.parts for t in timings if t.parts > 1}
    assert split and len(Presentation(str(res.pptx)).slides) == len(slide_ids(doc)) + sum(n - 1 for n in split.values())
    durations = json.loads(res.durations.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in durations["items"]}
    for t in timings:
        assert t.adv_ms == pytest.approx(by_id[t.id]["slide_sec"] * 1000, abs=2), t.id
    v, a = ffprobe_sec(res.final_mp4, "v:0"), ffprobe_sec(res.final_mp4, "a:0")
    assert abs(v - a) <= 0.2 and v == pytest.approx(expected_total_sec(timings), abs=0.1)
    expected = [(t.start_ms + t.transition_ms) / 1000 + durations["pre_pause_sec"] for t in timings]
    starts = [s for s in silence_ends(res.final_mp4) if s < v - 0.05]
    assert len(starts) == len(expected)
    for got, exp in zip(starts, expected):
        assert got == pytest.approx(exp, abs=0.1)
    assert res.run["stages"]["deck"]["split_slides"] == split
    for sid, parts in res.run["stages"]["deck"]["split"].items():
        para = by_id[sid].get("paragraph_starts_sec")
        if para and len(para) == 2:
            assert parts[0]["adv_ms"] == round((durations["pre_pause_sec"] + para[1]) * 1000)


def test_mux_groups_split_slides_and_rejects_wrong_ids(tmp_path):
    res = _build(tmp_path, captures_root=_captures(tmp_path), allow_placeholders=False)
    ids = slide_ids(_doc())
    with pytest.raises(MuxError, match="一致しません"):
        read_slide_timings(res.pptx, ids[:-1])
    assert pptx_total_sec(res.pptx) == pytest.approx(expected_total_sec(read_slide_timings(res.pptx, ids)))


# ------------------------------------------------------------------ Morph のずれの自動補正

@pytest.mark.parametrize("video,expected,morphs,result", [
    (100.0, 100.0, 0, (0.0, False, False)),       # Morph なし
    (100.14, 100.0, 1, (0.14, True, False)),
    (100.41, 100.0, 3, (0.41 / 3, True, False)),   # Windows 実測（+0.41 秒・3 か所）
    (99.5, 100.0, 3, (0.0, False, True)),         # 差がマイナス → 補正しない
    (102.0, 100.0, 3, (0.0, False, True)),        # 1 か所あたり 0.67 秒 ＞ 0.5 秒 → 補正しない
    (None, 100.0, 3, (0.0, False, False)),        # 長さが取れない
])
def test_morph_drift(video, expected, morphs, result):
    extra, corrected, why = morph_drift(video, expected, morphs)
    assert extra == pytest.approx(result[0]) and corrected is result[1] and (why is not None) is result[2]


def test_morph_drift_limit():
    assert morph_drift(100.0 + 3 * MAX_MORPH_EXTRA_SEC, 100.0, 3)[1] is True
    assert morph_drift(100.0 + 3 * MAX_MORPH_EXTRA_SEC + 0.01, 100.0, 3)[1] is False


def test_morph_counts_per_scene(tmp_path):
    res = _build(tmp_path, captures_root=_captures(tmp_path), allow_placeholders=False)
    timings = read_slide_timings(res.pptx, slide_ids(_doc()))
    inside = [t.id for t in timings if t.morphs_inside]
    assert inside and count_morphs(timings) == len(inside)
    before = 0
    for t in timings:  # 各シーンより前にある Morph の数
        assert t.morphs_before == before
        before += t.morphs_inside


@needs_ffmpeg
def test_drift_is_corrected_so_narration_starts_on_each_scene(tmp_path):
    caps = _captures(tmp_path)
    probe = _build(tmp_path / "probe", captures_root=caps, allow_placeholders=False)
    n = count_morphs(read_slide_timings(probe.pptx, slide_ids(_doc())))
    assert n >= 1
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(extra_sec=0.14 * n), captures_root=caps,
                 allow_placeholders=False)
    assert not any("ずれています" in w for w in res.warnings)
    mux_stage = res.run["stages"]["mux"]
    assert mux_stage["drift_corrected"] is True and mux_stage["morph_count"] == n
    assert mux_stage["morph_extra_sec"] == pytest.approx(0.14, abs=0.01)
    assert any("補正しました" in line for line in mux_stage["info"])
    timings = read_slide_timings(res.pptx, slide_ids(_doc()))
    durations = json.loads(res.durations.read_text(encoding="utf-8"))
    v = ffprobe_sec(res.final_mp4, "v:0")
    starts = [s for s in silence_ends(res.final_mp4) if s < v - 0.05]
    expected = [(t.start_ms + t.transition_ms) / 1000 + durations["pre_pause_sec"] + t.morphs_before * 0.14
                for t in timings]
    assert len(starts) == len(expected)
    for got, exp in zip(starts, expected):
        assert got == pytest.approx(exp, abs=0.08)


@needs_ffmpeg
@pytest.mark.parametrize("extra,reason", [(3.0, "大きすぎる"), (-0.5, "短い")])
def test_drift_not_corrected_when_out_of_range(tmp_path, extra, reason):
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(extra_sec=extra), captures_root=_captures(tmp_path),
                 allow_placeholders=False)
    mux_stage = res.run["stages"]["mux"]
    assert mux_stage["drift_corrected"] is False and mux_stage["morph_extra_sec"] == 0
    assert any(reason in w for w in res.warnings) and any("ずれています" in w for w in res.warnings)


@needs_ffmpeg
def test_video_without_morph_keeps_old_warning(tmp_path):
    res = _build(tmp_path, platform="win32", exporter=_fake_exporter(extra_sec=0.42))  # 画像なし → 分けない・Morph なし
    mux_stage = res.run["stages"]["mux"]
    assert mux_stage["morph_count"] == 0 and mux_stage["drift_corrected"] is False
    assert any("ずれています" in w for w in res.warnings)
