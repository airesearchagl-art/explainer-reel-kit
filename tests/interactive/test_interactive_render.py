"""レンダラーと検証: 区間の固定、色の指定、連結・音声の結合の引数、場面コードの読み込み、
小さい中間データで描いて verify を通す（ffmpeg が無ければ飛ばす）。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from interactive_helpers import timeline_doc, write_doc
from reel_helpers import needs_ffmpeg

from explainer_reel_kit.interactive import engine
from explainer_reel_kit.interactive.render import (CHUNK, TIMESCALE, X264, Project, Renderer, concat_command,
                                               encode_command, mux_command, plan_chunks, render)
from explainer_reel_kit.interactive.scenes import SceneError, fit_box, load_scenes
from explainer_reel_kit.interactive.verify import SELECT_MAX_TERMS, Verifier, extract_args, merge_runs

# ---------------------------------------------------------------- 区間


def test_chunks_are_fixed_600_frames_regardless_of_scenes():
    assert CHUNK == 600 and CHUNK % 30 == 0
    chunks = plan_chunks(12739)
    assert chunks[0] == (0, 600) and chunks[-1] == (12600, 12739)
    assert all(b - a == 600 for a, b in chunks[:-1]) and len(chunks) == 22
    with pytest.raises(ValueError):
        plan_chunks(100, chunk=500)   # 30 の倍数でない区間は作らない


# ---------------------------------------------------------------- 色・timescale・連結・結合


def test_encode_command_states_bt709_limited():
    cmd = encode_command("ffmpeg", Path("seg.mp4"))
    s = " ".join(cmd)
    assert "out_color_matrix=bt709:out_range=limited" in s
    out_args = cmd[cmd.index("-vf"):]   # 入力（rawvideo・rgb24）より後ろ＝書き出しの指定
    for k, v in (("-colorspace", "bt709"), ("-color_primaries", "bt709"), ("-color_trc", "bt709"),
                 ("-color_range", "tv"), ("-pix_fmt", "yuv420p"), ("-video_track_timescale", str(TIMESCALE)),
                 ("-crf", "15"), ("-g", "60"), ("-c:v", "libx264")):
        assert out_args[out_args.index(k) + 1] == v
    assert cmd[cmd.index("-f") + 1] == "rawvideo" and cmd[cmd.index("-s") + 1] == "1920x1080"
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgb24" and "libx264" in X264


def test_concat_and_mux_commands():
    c = concat_command("ffmpeg", Path("concat.txt"), Path("v.mp4"))
    assert c[c.index("-f") + 1] == "concat" and c[c.index("-c") + 1] == "copy"
    assert c[c.index("-video_track_timescale") + 1] == str(TIMESCALE)
    m = mux_command("ffmpeg", Path("v.mp4"), Path("src.mp4"), Path("o.mp4"), 48000)
    assert m[m.index("-c") + 1] == "copy" and "1:a:0" in m and m[m.index("-movie_timescale") + 1] == "48000"
    assert "-movie_timescale" not in mux_command("ffmpeg", Path("v.mp4"), Path("s.mp4"), Path("o.mp4"), None)


def test_extract_args_state_bt709_and_keep_select_short():
    frames = list(range(1000, 1000 + SELECT_MAX_TERMS))
    a = extract_args(Path("x.mp4"), frames, 30)
    vf = a[a.index("-vf") + 1]
    assert "in_color_matrix=bt709:in_range=limited" in vf and vf.count("eq(n") == SELECT_MAX_TERMS <= 100
    assert "eq(n\\,0)" in vf and a[a.index("-ss") + 1] == "%.6f" % (999.5 / 30)   # 先頭の手前へシークし、n は 0 から
    assert a[a.index("-frames:v") + 1] == str(SELECT_MAX_TERMS)


def test_merge_runs_joins_touching_cues():
    assert merge_runs([{"f0": 0, "f1": 10}, {"f0": 10, "f1": 20}, {"f0": 25, "f1": 30}]) == [[0, 20], [25, 30]]


# ---------------------------------------------------------------- 場面コードの読み込み


def _scene_files(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "b.py").write_text(
        "from explainer_reel_kit.interactive.engine import TEAL\n"
        "def scene(f, t, T):\n    f.rr(100, 100, 400, 200, fill=TEAL)\n    f.text('場面 b', 120, 140, size=48)\n",
        encoding="utf-8")


def test_load_scenes_from_files_and_index(tmp_path):
    d = tmp_path / "scenes"
    _scene_files(d)
    s = load_scenes(d, ["a", "b"])
    assert s.sources == {"a": "default", "b": "b.py"} and "b" in s.funcs
    (d / "index.py").write_text("from b import scene as sb\nSCENES = {'a': sb}\nAT_WEIGHTS = {'digit': 2.0}\n",
                                encoding="utf-8")
    s = load_scenes(d, ["a", "b"])
    assert s.sources == {"a": "index.py", "b": "b.py"} and s.at_weights == {"digit": 2.0}
    (d / "index.py").write_text("SCENES = {'zz': print}\n", encoding="utf-8")
    with pytest.raises(SceneError, match="zz"):
        load_scenes(d, ["a", "b"])


def test_two_scenes_dirs_do_not_share_helper_modules(tmp_path):
    """別の台本の場面コードを続けて読んでも、同じ名前の補助モジュール（helper.py）を取り違えない。"""
    for name in ("one", "two"):
        d = tmp_path / name / "scenes"
        d.mkdir(parents=True)
        (d / "helper.py").write_text(f"LABEL = '{name}'\n", encoding="utf-8")
        (d / "index.py").write_text("import helper\ndef s(f, t, T):\n    f.text(helper.LABEL, 0, 0)\nSCENES = {'a': s}\n",
                                    encoding="utf-8")
    from explainer_reel_kit.interactive.engine import Frame

    for name in ("one", "two", "one"):
        s = load_scenes(tmp_path / name / "scenes", ["a"])
        f = Frame()
        s.funcs["a"](f, 0.0, None)
        assert f.ops[0][0][1] == name


def test_missing_scenes_dir_means_default_scenes(tmp_path):
    s = load_scenes(tmp_path / "none", ["a"])
    assert s.funcs == {} and s.sources == {"a": "default"}


def test_default_scene_fits_image_above_subtitle_band():
    assert fit_box(2420, 1000) == (0, 73, 1920, 793)
    assert fit_box(1000, 1000) == (490, 0, 940, 940)


def test_renderer_layers_and_credit_on_last_scene(tmp_path):
    d = tmp_path / "p"
    _scene_files(d / "scenes")
    write_doc(d / "data" / "render-timeline.json", timeline_doc(meta={"title": "t", "credit": "AI声優-テスト"}))
    r = Renderer(Project.from_dir(d))
    scene_ops, sub_ops = r.layers(50)
    texts = [k[1] for k, *_ in scene_ops if k[0] == "text"]
    assert "場面 b" in texts and "ナレーション音声: AI声優-テスト" in texts
    assert [k[1] for k, *_ in sub_ops] == ["冷えると、水滴になります"]
    assert r.layers(40)[1] == ()            # 字幕の無いフレーム
    assert "ナレーション音声: AI声優-テスト" not in [k[1] for k, *_ in r.layers(10)[0] if k[0] == "text"]


# ---------------------------------------------------------------- 描いて検証する（ffmpeg）


@needs_ffmpeg
def test_render_two_chunks_and_verify(tmp_path):
    """660 フレーム（区間 2 つ）を描き、尺・フレーム数・字幕の表示フレーム・切替を verify で確かめる。"""
    total = 660
    doc = timeline_doc(total=total, scenes=[("a", 0, 300), ("b", 300, total)],
                       sentences=[{"id": "a-1", "scene": "a", "spoken": "一つ目の文です。", "start_sec": 1, "end_sec": 8},
                                  {"id": "b-1", "scene": "b", "spoken": "二つ目の文です。", "start_sec": 11, "end_sec": 20}],
                       cues=[{"sentence": "a-1", "text": "一つ目の文です", "start_frame": 30, "end_frame": 240},
                             {"sentence": "b-1", "text": "二つ目の文です", "start_frame": 330, "end_frame": 600}])
    proj_dir = tmp_path / "p"
    _scene_files(proj_dir / "scenes")
    write_doc(proj_dir / "data" / "render-timeline.json", doc)
    out = tmp_path / "out" / "x.mp4"
    rec = render(Project.from_dir(proj_dir), out, jobs=1, log=lambda s: None)
    assert out.is_file() and rec["segments"] == 2 and rec["frames"] == total
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)]))
    v = probe["streams"][0]
    assert v["nb_frames"] == str(total) and v["avg_frame_rate"] == "30/1" and float(v["duration"]) == 22.0
    assert v.get("color_space") == "bt709" and v.get("color_range") == "tv"
    # 2 回目は区間を使い回す（入力が同じ）
    rec2 = render(Project.from_dir(proj_dir), out, jobs=1, log=lambda s: None)
    assert rec2["rendered_segments"] == 0
    ver = Verifier(Renderer(Project.from_dir(proj_dir)), out, tmp_path / "out" / "checks",
                   config={"screen_text": {"forbidden": ["禁止"]}}, log=lambda s: None)
    res = ver.run()
    assert res["ok"], json.dumps({k: res[k].get("ok") for k in res if isinstance(res[k], dict)})
    assert res["audio"]["ok"] is None and res["subtitles"]["mismatched_frames"] == 0
    assert (tmp_path / "out" / "checks" / "検証結果.md").is_file()
    assert (tmp_path / "out" / "checks" / "screen_text.json").is_file()


@needs_ffmpeg
def test_verify_flags_forbidden_words(tmp_path):
    proj_dir = tmp_path / "p"
    _scene_files(proj_dir / "scenes")
    write_doc(proj_dir / "data" / "render-timeline.json", timeline_doc())
    out = tmp_path / "out" / "x.mp4"
    render(Project.from_dir(proj_dir), out, jobs=1, log=lambda s: None)
    ver = Verifier(Renderer(Project.from_dir(proj_dir)), out, tmp_path / "out" / "checks",
                   config={"screen_text": {"forbidden": ["場面 B"], "forbidden_before": {"sec": 2.0, "words": ["水滴"],
                                                                                         "include_subtitles": True}}},
                   log=lambda s: None)
    ver.text()
    d = ver.load()["screen_text"]
    assert not d["ok"] and "場面 b" in d["forbidden_hits"] and "冷えると、水滴になります" in d["forbidden_before_hits"]


def test_engine_asset_dirs_are_searched_in_order(tmp_path):
    from PIL import Image

    (tmp_path / "x").mkdir()
    Image.new("RGB", (40, 20), "white").save(tmp_path / "x" / "img.png")
    engine.set_asset_dirs([tmp_path / "missing", tmp_path / "x"])
    assert engine.asset_path("img.png") == tmp_path / "x" / "img.png" and engine.asset_size("img.png") == (40, 20)
    with pytest.raises(engine.LayoutError, match="静止画がありません"):
        engine.asset_path("none.png")
    engine.set_asset_dirs([])
