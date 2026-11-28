"""erkit make の interactive で、scenes.yaml を合成の前に確かめる（interactive.pipeline.precheck_scenes）と、
映像の作り方の優先順位・場面コードの置き場・動きの既定の長さ。

- 誤りは出力フォルダを作る前・ナレーションの合成の前に、InteractiveError（exit_code 2）で止まる
- scenes/ の直下に scenes.yaml だけを置いても見つける。台本のフォルダの scenes/ の外は読み込まない
- 仮の中間データの文の分け方は、合成の後の中間データ（sync.measure）と同じ（sentence: の番号が変わらない）
- 動きの長さは説明動画の既定（登場 0.4 秒・強調 0.3 秒・数値 0.8 秒）。見本帳の値は Motion.book に残る
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from explainer_reel_kit.interactive import motion as mo
from explainer_reel_kit.interactive import precheck
from explainer_reel_kit.interactive.pipeline import (InteractiveError, find_scenes_dir, narration_texts,
                                                     precheck_scenes, resolve_render_mode, scenes_dir_for)
from explainer_reel_kit.narration.adapter import slide_ids

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "interactive"
STORYBOARD = FIXTURES / "window-condensation.storyboard.json"
EXAMPLE_SPEC = FIXTURES / "window-condensation" / "scenes.yaml"
QUIET = lambda s: None  # noqa: E731


def _doc() -> dict:
    return json.loads(STORYBOARD.read_text(encoding="utf-8"))


def _copy_example(tmp_path: Path, spec_text: str | None = None, flat: bool = False) -> Path:
    """ダミーの台本と scenes.yaml を tmp_path に写す（spec_text で scenes.yaml を差し替える）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    sb = tmp_path / STORYBOARD.name
    shutil.copy(STORYBOARD, sb)
    d = tmp_path / "scenes" if flat else tmp_path / "scenes" / "window-condensation"
    d.mkdir(parents=True)
    (d / "scenes.yaml").write_text(spec_text if spec_text is not None else EXAMPLE_SPEC.read_text(encoding="utf-8"),
                                   encoding="utf-8")
    return sb


# ---------------------------------------------------------------- 合成の前に確かめる


def test_example_passes_the_check_before_synthesis(tmp_path):
    sb = _copy_example(tmp_path)
    info = precheck_scenes(sb, _doc(), None, log=QUIET)
    assert info["status"] == "ok" and info["timing"] == "provisional"
    assert info["scenes"] == ["s02", "s03"] and info["shadowed_by_python"] == [] and info["parts"] == 7
    assert info["scenes_dir"] == str((tmp_path / "scenes" / "window-condensation").resolve())


def test_without_scenes_yaml_the_check_is_skipped(tmp_path):
    sb = tmp_path / STORYBOARD.name
    shutil.copy(STORYBOARD, sb)
    info = precheck_scenes(sb, _doc(), None, log=QUIET)
    assert info["status"] == "skipped" and info["scenes_dir"] is None


@pytest.mark.parametrize("old, new, message", [
    ("at: 露点は", "at: 霜点は", "語句「霜点は」は場面 s02 の文 6 にありません"),
    ("type: callout", "type: banner", "知らない型"),
    ("sentence: 7", "sentence: 70", "文 70 はありません"),
    ("  s03:", "  s99:", "中間データに無い場面 id"),
])
def test_spec_errors_stop_with_exit_code_2(tmp_path, old, new, message):
    text = EXAMPLE_SPEC.read_text(encoding="utf-8")
    assert old in text
    sb = _copy_example(tmp_path, text.replace(old, new, 1))
    with pytest.raises(InteractiveError) as e:
        precheck_scenes(sb, _doc(), None, log=QUIET)
    assert e.value.exit_code == 2 and e.value.stage == "scenes"
    assert message in str(e.value) and "合成の前に止めました" in str(e.value)


def test_broken_python_scene_code_stops_with_exit_code_1(tmp_path):
    sb = _copy_example(tmp_path)
    (tmp_path / "scenes" / "window-condensation" / "s02.py").write_text("def scene(f, t, T):\n  return (\n",
                                                                        encoding="utf-8")
    with pytest.raises(InteractiveError) as e:
        precheck_scenes(sb, _doc(), None, log=QUIET)
    assert e.value.exit_code == 1 and "s02.py" in str(e.value)


def test_find_scenes_dir_accepts_a_flat_scenes_yaml(tmp_path):
    sb = _copy_example(tmp_path, flat=True)
    assert find_scenes_dir(sb, "window-condensation") == (tmp_path / "scenes").resolve()
    info = precheck_scenes(sb, _doc(), None, log=QUIET)
    assert info["status"] == "ok" and info["scenes_dir"] == str((tmp_path / "scenes").resolve())


def test_scene_code_is_read_only_from_the_storyboard_folder(tmp_path):
    sb = _copy_example(tmp_path / "reel")
    other = tmp_path / "elsewhere"
    shutil.copytree(tmp_path / "reel" / "scenes" / "window-condensation", other)
    with pytest.raises(InteractiveError, match="台本のフォルダの scenes/ の下だけ") as e:
        precheck_scenes(sb, _doc(), other, log=QUIET)
    assert e.value.exit_code == 2
    inside = tmp_path / "reel" / "scenes" / "window-condensation"
    assert scenes_dir_for(sb, _doc(), inside) == inside.resolve()


def test_provisional_sentences_match_the_synthesized_split():
    """仮の中間データの文は、合成の後の中間データ（sync.measure）と同じ分け方・同じ id。"""
    from explainer_reel_kit.interactive.sync import measure

    doc = _doc()
    ids, texts = slide_ids(doc), narration_texts(doc)
    tl = precheck.provisional_timeline(doc, ids, texts)
    assert [s["id"] for s in tl["scenes"]] == ids
    for sid in ids:
        want = [s for p in measure(texts[sid], {"audio_sec": 10.0}, Path("-"), runs=[])["sentences"] for s in p]
        got = [s["spoken"] for s in tl["sentences"] if s["scene"] == sid]
        assert got == want, sid
        assert [s["id"] for s in tl["sentences"] if s["scene"] == sid] == [f"{sid}-{n}" for n in
                                                                            range(1, len(want) + 1)]
    ends = [s["end_frame"] for s in tl["scenes"]]
    assert ends == sorted(ends) and tl["total_frames"] == ends[-1]


# ---------------------------------------------------------------- 映像の作り方の優先順位


def test_render_mode_priority_command_over_storyboard_over_default():
    doc = _doc()
    assert resolve_render_mode(None, doc) == ("slides", "default")
    doc["reel"]["render_mode"] = "interactive"
    assert resolve_render_mode(None, doc) == ("interactive", "storyboard")
    assert resolve_render_mode("slides", doc) == ("slides", "command")
    with pytest.raises(InteractiveError) as e:
        resolve_render_mode("video", doc)
    assert e.value.exit_code == 2
    doc["reel"]["render_mode"] = "video"
    with pytest.raises(InteractiveError):
        resolve_render_mode(None, doc)


# ---------------------------------------------------------------- 説明動画の既定の長さ


def test_motion_defaults_are_for_explainer_videos_and_keep_the_sample_book_values():
    assert mo.VIDEO_DEFAULTS == {"enter": 0.4, "emphasis": 0.3, "value": 0.8}
    for name in ("fade-in", "fade", "stagger", "stagger-T03", "slidein", "clipreveal", "wipe"):
        assert mo.get(name).duration == 0.4 and mo.get(name).basis == "video", name
    for name in ("fill", "underline", "roomhighlight", "marker"):
        assert mo.get(name).duration == 0.3 and mo.get(name).basis == "video", name
    c = mo.get("counter")
    assert (c.duration, c.delay, c.basis) == (0.8, 0.0, "video")
    # 見本帳の値（CSS の例）は分けて残る
    assert mo.get("fade-in").book["duration"] == 1.7 and mo.get("stagger").book["duration"] == 0.5
    assert mo.get("roomhighlight").book["duration"] is None                 # 見本帳に長さが無い
    assert (c.book["duration"], c.book["delay"]) == (1.6, 0.2) and c.book_motion().end_sec() == pytest.approx(1.8)
    co = mo.get("callout")                                                 # 3 段の比を保って半分
    assert co.end_sec() == pytest.approx(0.55) and co.book_motion().end_sec() == pytest.approx(1.1)
    # 見本帳のままのもの: 理由が書いてある
    kept = {m.id for m in mo.MOTIONS.values() if m.basis == "book"}
    assert kept == {"typewriter", "hotspot", "fadethrough", "beforeafter"}
    assert all(mo.MOTIONS[k].why and mo.MOTIONS[k].duration == mo.MOTIONS[k].book["duration"] for k in kept)
    # イージングは見本帳のまま・speed はそのまま
    assert mo.get("stagger").easing == (0.2, 0.8, 0.2, 1.0) and mo.get("stagger").step == 0.08
    assert mo.get("fade-in").progress(10.2, 10.0, speed=2.0) == 1.0
    rows = {r["id"]: r for r in mo.timing_rows()}
    assert rows["fade-in"]["end"] == 0.4 and rows["fade-in"]["book_end"] == 1.7 and rows["hotspot"]["basis"] == "book"


def test_readme_table_lists_both_the_default_and_the_sample_book_value():
    readme = (Path(mo.__file__).parent / "README.md").read_text(encoding="utf-8")
    sec = readme.split("| scenes.yaml の値 |", 1)[1].split("\n\n", 1)[0]
    assert "既定の長さ（説明動画）" in sec and "見本帳の値" in sec
    for m in mo.MOTIONS.values():
        line = next(x for x in sec.splitlines() if x.startswith(f"| `{m.id}` |"))
        cells = [c.strip() for c in line.split("|")[1:-1]]
        assert cells[2].split("（")[0] == f"{m.end_sec():g}", m.id
        book = m.book_motion().end_sec() if m.book.get("duration") is not None else None
        assert cells[3] == ("（無し）" if book is None else f"{book:g}"), m.id
