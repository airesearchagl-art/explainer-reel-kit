"""部品と場面の指定 scenes.yaml: 部品の描画・scenes.yaml の検証・優先順位・きっかけの時刻・
動きの名前（モーション見本帳）・ダミーの例が Python の場面コードと同じ絵になること・きっかけごとの一覧。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

from explainer_reel_kit.interactive import motion as mo
from explainer_reel_kit.interactive import spec
from explainer_reel_kit.interactive.cli import main as cli_main
from explainer_reel_kit.interactive.engine import AMBER, LayoutError, texts_of
from explainer_reel_kit.interactive.parts import PART_TYPES
from explainer_reel_kit.interactive.render import Project, Renderer, input_stamp
from explainer_reel_kit.interactive.scenes import load_scenes
from explainer_reel_kit.interactive.sheet import make_cue_sheets
from explainer_reel_kit.interactive.timeline import Timeline

from interactive_helpers import timeline_doc, write_doc

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "interactive"
EXAMPLE = FIXTURES / "window-condensation"            # scenes.yaml だけ（一般的な題材の例）
PYTHON_VERSION = FIXTURES / "window-condensation-python"   # 同じ絵を Python の場面コードで書いたもの

# ---------------------------------------------------------------- 小さな中間データ

WC_SENTENCES = {   # window-condensation の s02・s03（ダミーの台本の文を短くしたもの。語句の位置だけ合わせる）
    "s02": ["空気には、目に見えない水蒸気が含まれています。", "暖かい空気ほど、多くの水蒸気を含めます。",
            "その空気が、冷たい窓ガラスに触れて、冷やされます。", "冷えた空気は、水蒸気を抱えきれなくなります。",
            "水滴ができ始めるこの温度を、露点といいます。", "この部屋では、露点はおよそ十二度。",
            "ガラスの表面がこれより冷えると、水滴がつきます。"],
    "s03": ["では、窓ガラスの表面は何度でしょうか。", "露点より低いと結露します。", "一枚のガラスでは、およそ六度。",
            "露点より低いので、結露します。", "ローイー複層ガラスでは、およそ十五点五度。", "この条件では、結露しません。"],
}


def wc_doc() -> dict:
    sents, scenes, t = [], [], 0.0
    for sid, texts in WC_SENTENCES.items():
        f0 = int(round(t * 30))
        t += 0.4
        for k, s in enumerate(texts, 1):
            sents.append({"id": f"{sid}-{k}", "scene": sid, "spoken": s, "start_sec": round(t, 3),
                          "end_sec": round(t + 2.0, 3)})
            t += 2.3
        t += 0.6
        scenes.append((sid, f0, int(round(t * 30))))
    total = scenes[-1][2]
    return timeline_doc(total=total, scenes=scenes, sentences=sents, cues=[])


def project(tmp_path: Path, scenes_dir: Path | None, doc: dict | None = None) -> Project:
    tl = write_doc(tmp_path / "data" / "render-timeline.json", doc or wc_doc())
    return Project(timeline=tl, scenes_dir=scenes_dir)


def write_spec(d: Path, scenes: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "scenes.yaml").write_text(yaml.safe_dump({"version": 1, "scenes": scenes}, allow_unicode=True),
                                   encoding="utf-8")
    return d


def T_of(doc: dict | None = None) -> Timeline:
    return Timeline(doc or wc_doc())


# ---------------------------------------------------------------- ダミーの例: scenes.yaml だけで、Python の場面コードと同じ絵


def test_example_is_drawn_from_scenes_yaml_only():
    assert sorted(p.name for p in EXAMPLE.glob("*.py")) == []          # Python の場面コードは無い
    assert (EXAMPLE / "scenes.yaml").is_file()


def test_example_matches_the_python_scene_code_at_the_end_of_each_scene(tmp_path):
    """読み終えた状態（場面の終わり）の表示リストが、Python の場面コードと同じ（要点の文字の 2px だけ違う）。"""
    py = Renderer(project(tmp_path / "py", PYTHON_VERSION))
    py_ops = {sid: py.layers(py.T.by_id[sid]["f1"] - 1)[0] for sid in ("s02", "s03")}
    ym = Renderer(project(tmp_path / "ym", EXAMPLE))
    assert ym.scenes.sources["s02"] == ym.scenes.sources["s03"] == "scenes.yaml"
    for sid, a in py_ops.items():
        b = ym.layers(ym.T.by_id[sid]["f1"] - 1)[0]
        assert texts_of(a) == texts_of(b), sid
        only_a, only_b = set(a) - set(b), set(b) - set(a)
        assert len(only_a) == len(only_b) <= 1, (sid, only_a, only_b)
        for (ka, xa, ya, aa), (kb, xb, yb, ab) in zip(only_a, only_b):   # s02 の要点: 枠の中の上下の中央に置く
            assert ka == kb and xa == xb and aa == ab and abs(ya - yb) <= 2


def test_example_cue_times_follow_the_narration():
    T = T_of()
    sc = spec.compile_scene(T, "s02", spec.load_spec(EXAMPLE / "scenes.yaml")["scenes"]["s02"])
    cards = sc.parts[1]
    assert [c.t for c in cards.cues] == [T.S("s02-1"), T.S("s02-3"), T.S("s02-4"), T.S("s02-7")]
    assert sc.parts[2].cue.t == T.at("s02-6", "露点は")


# ---------------------------------------------------------------- きっかけの時刻


def test_cue_from_sentence_phrase_both_and_none():
    T = T_of()
    r = lambda item: spec.resolve_cue(T, "s03", item, "w")   # noqa: E731
    assert r({}).t == T.by_id["s03"]["start"]
    assert r({"sentence": 3}).t == T.S("s03-3")
    assert r({"at": "およそ六度"}).t == T.at("s03-3", "およそ六度") > T.S("s03-3")
    assert r({"sentence": 5, "at": "およそ十五点五度"}).t == T.at("s03-5", "およそ十五点五度")


def test_sentence_number_is_the_order_within_the_scene_even_with_global_ids():
    """文の id が通し番号（68, 69, …）の中間データでも、sentence: 2 は場面の 2 番目の文。"""
    doc = timeline_doc(total=300, scenes=[("a", 0, 90), ("b", 90, 300)], cues=[], sentences=[
        {"id": "7", "scene": "a", "spoken": "前の場面です。", "start_sec": 0.5, "end_sec": 2.0},
        {"id": "68", "scene": "b", "spoken": "使うときの約束です。", "start_sec": 3.2, "end_sec": 4.5},
        {"id": "69", "scene": "b", "spoken": "承認済みのものを使います。", "start_sec": 4.8, "end_sec": 6.9},
    ])
    T = T_of(doc)
    assert spec.resolve_cue(T, "b", {"sentence": 2}, "w").t == T.S("69")
    assert spec.resolve_cue(T, "b", {"at": "承認済み"}, "w").sentence == "69"


@pytest.mark.parametrize("item, message", [
    ({"at": "雪が降る"}, "ナレーションにありません"),
    ({"at": "露点"}, "sentence: で文を決める"),            # s03 の 2 つの文にある
    ({"sentence": 9}, "文 9 はありません"),
    ({"sentence": 3, "at": "十五点五"}, "文 3 にありません"),
])
def test_cue_errors_stop_before_drawing(item, message):
    with pytest.raises(spec.SpecError, match=message):
        spec.resolve_cue(T_of(), "s03", item, "w")


def test_motion_progress_uses_sample_book_easing_and_speed():
    st = mo.get("stagger")                                  # 22: cubic-bezier(.2,.8,.2,1)、--i × .08s（長さは説明動画の 0.4s）
    assert (st.number, st.duration, st.step, st.book["duration"]) == ("22", 0.4, 0.08, 0.5)
    assert st.progress(10.0, 10.0) == 0.0 and st.progress(10.4, 10.0) == 1.0
    assert st.progress(10.08, 10.0, i=1) == 0.0                # 2 つ目は .08s 遅れて始まる
    assert st.progress(10.2, 10.0, speed=2.0) == 1.0           # 速さ ×2 で .2s
    assert st.book_motion().progress(10.4, 10.0) < 1.0 and st.book_motion().progress(10.5, 10.0) == 1.0
    assert abs(mo.cubic_bezier(0.25, 0.1, 0.25, 1.0)(0.5) - 0.8024) < 1e-3   # CSS の ease
    assert mo.get("T03").id == "stagger-T03" and mo.get("stagger-22").id == "stagger"
    c = mo.get("counter")                                     # T08: 1-(1-p)^3。説明動画はきっかけから 0.8s
    assert c.progress(0.0, 0.0) == 0.0 and abs(c.progress(0.4, 0.0) - (1 - 0.5 ** 3)) < 1e-9
    cb = c.book_motion()                                      # 見本帳: 0.2s 後から 1.6s
    assert cb.progress(0.2, 0.0) == 0.0 and abs(cb.progress(1.0, 0.0) - (1 - 0.5 ** 3)) < 1e-9


def test_motion_names_are_sample_book_ids():
    ids = {"cut", "fade", "fade-in", "stagger", "stagger-T03", "slidein", "clipreveal", "wipe", "typewriter",
           "roomhighlight", "fill", "underline", "marker", "hotspot", "callout", "counter", "beforeafter",
           "fadethrough"}
    assert set(mo.MOTIONS) == ids
    numbers = {m.id: m.number for m in mo.MOTIONS.values()}
    assert numbers["fill"] == "08" and numbers["underline"] == "07" and numbers["clipreveal"] == "12"
    assert numbers["beforeafter"] == "11" and numbers["marker"] == "T13"
    used = {"underline", "hotspot", "callout", "marker", "fadethrough", "fade"}   # 部品の中で使う（矢印・注釈・until など）
    for cls in PART_TYPES.values():                            # 部品が使う動きは、どれも見本の id
        for allowed in cls.MOTION_FIELDS.values():
            assert set(allowed) - {"none"} <= ids, cls.TYPE
            used |= set(allowed) - {"none"}
    assert used == ids                                         # 使わない見本は並べない


# ---------------------------------------------------------------- scenes.yaml の検証（描く前に止める）


@pytest.mark.parametrize("part, message", [
    ({"type": "slideshow"}, "知らない型 'slideshow'"),
    ({"type": "header", "title": "x", "colour": "red"}, "知らない項目 colour"),
    ({"type": "cards", "items": [{"title": "a"}], "motion": "bounce"}, "'bounce' は使えません"),
    ({"type": "table", "columns": ["a"]}, "項目 'rows' が要ります"),
    ({"type": "cards", "items": [{"title": "a", "sentence": "3"}]}, "整数で書きます"),
])
def test_unknown_type_field_or_motion_is_an_error(part, message):
    errors = spec.validate_doc({"version": 1, "scenes": {"s02": {"parts": [part]}}})
    assert any(message in e for e in errors), errors


def test_load_errors_name_the_file_and_stop_with_exit_code_2(tmp_path, capsys):
    d = write_spec(tmp_path / "scenes", {"s02": {"parts": [{"type": "heading", "text": "x", "at": "雪が降る"}]}})
    p = project(tmp_path, d)
    with pytest.raises(spec.SpecError, match="語句「雪が降る」"):
        Renderer(p)
    rc = cli_main(["sheet", "--project", str(tmp_path), "--scenes", str(d), "1.0"])
    assert rc == 2 and "雪が降る" in capsys.readouterr().err


def test_unknown_scene_id_in_scenes_yaml(tmp_path):
    d = write_spec(tmp_path / "scenes", {"s99": {"parts": [{"type": "heading", "text": "x"}]}})
    with pytest.raises(spec.SpecError, match="中間データに無い場面 id"):
        load_scenes(d, ["s02", "s03"])


def test_schema_file_is_generated_from_the_parts():
    on_disk = json.loads(spec.SCHEMA_FILE.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(spec.json_schema(), ensure_ascii=False))
    assert set(on_disk["$defs"]["part"]["properties"]["type"]["enum"]) == set(PART_TYPES)


def test_schema_check_command(tmp_path, capsys):
    assert cli_main(["schema", "--check"]) == 0
    assert "OK" in capsys.readouterr().out
    other = tmp_path / "scenes.schema.json"
    other.write_text("{}\n", encoding="utf-8")
    assert cli_main(["schema", "--check", "--out", str(other)]) == 1
    assert cli_main(["schema", "--out", str(other)]) == 0
    assert cli_main(["schema", "--check", "--out", str(other)]) == 0


def test_eleven_part_types():
    assert set(PART_TYPES) == {"header", "heading", "title", "cards", "steps", "table", "number", "image", "compare",
                               "callout", "flow"}


# ---------------------------------------------------------------- 優先順位: Python の場面コード ＞ scenes.yaml ＞ 既定の場面


def test_python_scene_code_wins_over_scenes_yaml_which_wins_over_default(tmp_path):
    d = write_spec(tmp_path / "scenes", {"s02": {"parts": [{"type": "heading", "text": "指定の見出し"}]},
                                         "s03": {"parts": [{"type": "heading", "text": "指定の見出し 3"}]}})
    (d / "s03.py").write_text("def scene(f, t, T):\n    f.text('Python の場面', 96, 300)\n", encoding="utf-8")
    doc = wc_doc()
    doc["scenes"].append({"id": "s04", "title": "既定", "start_frame": doc["total_frames"],
                          "end_frame": doc["total_frames"] + 30})
    doc["total_frames"] += 30
    r = Renderer(project(tmp_path, d, doc))
    assert r.scenes.sources == {"s02": "scenes.yaml", "s03": "s03.py", "s04": "default"}
    assert r.scenes.record()["spec_shadowed_by_python"] == ["s03"]
    assert "指定の見出し" in texts_of(r.layers(r.T.by_id["s02"]["f1"] - 1)[0])
    assert texts_of(r.layers(r.T.by_id["s03"]["f1"] - 1)[0]) == ["Python の場面"]
    assert texts_of(r.layers(r.T.by_id["s04"]["f1"] - 1)[0]) == ["既定"]


def test_scenes_yaml_is_part_of_the_input_stamp(tmp_path):
    d = write_spec(tmp_path / "scenes", {"s02": {"parts": [{"type": "heading", "text": "一"}]}})
    a = input_stamp(Renderer(project(tmp_path, d)))
    write_spec(d, {"s02": {"parts": [{"type": "heading", "text": "二"}]}})
    assert input_stamp(Renderer(project(tmp_path, d))) != a


# ---------------------------------------------------------------- 部品の描画


def _scene(parts: list, sid: str = "s03", doc: dict | None = None):
    T = T_of(doc)
    return T, spec.compile_scene(T, sid, {"parts": parts})


def test_card_text_overflow_stops_before_drawing():
    T, sc = _scene([{"type": "cards", "box": [96, 200, 600, 120],
                     "items": [{"title": "見出し", "body": "とても長い説明の文です。" * 8, "sentence": 1}]}])
    with pytest.raises(spec.SpecError, match="カード 1 の文字が入りません"):
        spec.dry_run(T, sc)


def test_table_rows_are_chosen_by_heading_text():
    T, sc = _scene([{"type": "table", "box": [96, 300, 1728, 380], "columns": ["ガラス", "表面", "比べて"],
                     "dim": 0, "rows": [{"name": "1 枚", "sentence": 3, "cells": {"表面": "約 6℃"}},
                                        {"name": "複層", "sentence": 5, "cells": {"表面": "約 15.5℃"}}]}])
    tb = sc.parts[0]
    f_ = __import__("explainer_reel_kit.interactive.engine", fromlist=["Frame"]).Frame()
    sc.draw(f_, T.S("s03-5") + 0.5)       # 2 行目を読んでいる
    x, y, w, h = tb.tb.row("複層")
    glows = [(k, ox, oy) for k, ox, oy, _ in f_.ops if k[0] == "glow"]
    assert glows and glows[-1][0][1:3] == (int(w), int(h))
    assert abs(glows[-1][2] - (y - 28)) <= 1          # 注目枠は「複層」の行に


def test_table_unknown_column_is_an_error():
    with pytest.raises(LayoutError, match="列「温度」はありません"):
        _scene([{"type": "table", "columns": ["ガラス", "表面"], "rows": [{"name": "1 枚", "cells": {"温度": "x"}}]}])


def test_header_progress_and_labels():
    T, sc = _scene([{"type": "header", "title": "約束", "label": "前半｜", "label_accent": "2  比べる",
                     "progress": {"total": 4, "current": 2}, "foot": "説明用に再構成"}])
    f_ = __import__("explainer_reel_kit.interactive.engine", fromlist=["Frame"]).Frame()
    sc.draw(f_, T.by_id["s03"]["end"] - 0.1)
    assert texts_of(f_.ops) == ["約束", "2  比べる", "前半｜", "説明用に再構成"]
    segs = [k for k, *_ in f_.ops if k[0] == "rr" and k[2] == 6]
    assert len(segs) == 4 and segs[1][4] == "#62c0d0"      # 2 段目が今の段（TEAL）


@pytest.mark.parametrize("part", [
    {"type": "heading", "text": "段の見出し", "badge": 2, "sub": "続き"},
    {"type": "title", "lines": [{"text": "題", "size": 76}, {"text": "4段階", "size": 104, "color": "teal"}]},
    {"type": "steps", "marker": "check", "boxed": True, "items": [{"text": "一つ目", "sentence": 1},
                                                                    {"text": "二つ目", "sentence": 2}]},
    {"type": "number", "items": [{"value": "580", "unit": "名", "caption": "のうち", "ratio": 1.0},
                                 {"value": "262", "unit": "名", "ratio": 0.45, "sentence": 2}]},
    {"type": "callout", "style": "band", "texts": [{"text": "一つ目の要点", "sentence": 1},
                                                   {"text": "二つ目の要点", "sentence": 2}]},
    {"type": "callout", "style": "pill", "text": "続いて、後半へ", "arrow": True},
    {"type": "callout", "text": "露点より低いと結露する", "mark": {"text": "結露する", "sentence": 2}},
    {"type": "flow", "items": [{"text": "調べる"}, {"text": "比べる", "sentence": 2}, {"text": "任せる", "sentence": 3}]},
    {"type": "cards", "numbered": True, "arrows": True, "align": "middle", "height": 220,
     "bracket": {"text": "まとめ", "sub": "下の文", "sentence": 4},
     "items": [{"title": ["整理して", "比べる"], "sentence": 1}, {"title": "任せる", "sentence": 2,
                                                              "checks": [{"text": "確かめる", "sentence": 3}]}]},
])
def test_each_part_draws_and_reaches_its_final_state(part):
    T, sc = _scene([part])
    spec.dry_run(T, sc)
    from explainer_reel_kit.interactive.engine import Frame

    f_ = Frame()
    sc.draw(f_, T.by_id["s03"]["end"] - 0.05)
    assert f_.ops and all(a > 0 for *_, a in f_.ops)


def test_image_part_maps_annotations_from_image_pixels(tmp_path):
    from explainer_reel_kit.interactive import engine

    (tmp_path / "assets").mkdir()
    Image.new("RGB", (400, 200), "white").save(tmp_path / "assets" / "plan.png")
    engine.set_asset_dirs([tmp_path / "assets"])
    T, sc = _scene([{"type": "image", "box": [96, 200, 800, 434], "motion": "cut",   # 下の 34px は区分の表示の行
                     "images": [{"src": "plan.png"}],
                     "annotations": [{"shape": "box", "rect": [100, 50, 100, 50], "sentence": 2},
                                     {"shape": "label", "xy": [200, 100], "text": "注記", "sentence": 3},
                                     {"shape": "point", "xy": [300, 150], "sentence": 4}]}])
    im = sc.parts[0]
    assert im.to_screen(0, 0, 0) == (96, 200) and im.to_screen(0, 400, 200) == (896, 600)   # 2 倍
    from explainer_reel_kit.interactive.engine import Frame

    f_ = Frame()
    sc.draw(f_, T.by_id["s03"]["end"] - 0.05)
    boxes = [(k, x, y) for k, x, y, _ in f_.ops if k[0] == "rr" and k[4] == "#f6b93b38"]
    assert boxes and boxes[0][0][1:3] == (200, 100)
    assert "注記" in texts_of(f_.ops) and any(k[0] == "circ" and k[3] == AMBER for k, *_ in f_.ops)
    assert "説明用再構成図" in texts_of(f_.ops)   # 台本の画像ではない静止画の来歴ラベル（既定）


def test_compare_beforeafter_needs_two_images():
    with pytest.raises(LayoutError, match="beforeafter は左右の両方に image"):
        _scene([{"type": "compare", "motion": "beforeafter", "left": {"title": "前"}, "right": {"title": "後"}}])


def test_until_removes_a_part_with_fadethrough():
    T, sc = _scene([{"type": "heading", "text": "前半の段", "until": {"sentence": 4}}])
    from explainer_reel_kit.interactive.engine import Frame

    f1, f2 = Frame(), Frame()
    sc.draw(f1, T.S("s03-4") - 0.1)
    sc.draw(f2, T.S("s03-4") + mo.get("fadethrough").duration + 0.01)
    assert texts_of(f1.ops) == ["前半の段"] and texts_of(f2.ops) == []


# ---------------------------------------------------------------- 確かめの一覧（sheet --cues）


def test_cue_sheets_put_three_frames_per_cue_and_can_compare(tmp_path):
    ym = Renderer(project(tmp_path / "ym", EXAMPLE))
    py = Renderer(project(tmp_path / "py", PYTHON_VERSION))
    paths = make_cue_sheets(ym, tmp_path / "sheets", against=py, scenes=["s03"])
    assert paths and all(p.name.startswith("s03_cues_") for p in paths)
    with Image.open(paths[0]) as im:
        assert im.width == 1920 and im.height > 400
    rc = cli_main(["sheet", "--project", str(tmp_path / "ym"), "--scenes", str(EXAMPLE), "--cues",
                   "--scene", "s02", "--out-dir", str(tmp_path / "cli")])
    assert rc == 0 and sorted(p.name for p in (tmp_path / "cli").glob("*.jpg"))[0] == "s02_cues_00.jpg"
