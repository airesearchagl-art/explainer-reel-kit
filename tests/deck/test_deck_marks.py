"""撮影時の注釈位置（marks.json）を赤枠・矢印に反映する。"""
import json
import math
import re

import pytest
from PIL import Image
from pptx import Presentation

from deck_helpers import NS, SAMPLES, slide_roots

from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.deck import cli as deck_cli
from explainer_reel_kit.deck import overlay as ov
from explainer_reel_kit.deck.builder import IMAGE_BOX, SLIDE_H, SLIDE_W, _fit, load_storyboard
from explainer_reel_kit.deck.marks import edge_point, pad_box, resolve_scene, side_start

WEB = SAMPLES["web"]


# ------------------------------------------------------------------ helpers

def _marks(img, scene, boxes, size=None):
    w, h = size or Image.open(img).size
    data = {"format": "explainer-reel/marks@1", "scene": scene, "source": "web", "image": img.name,
            "image_size": {"w": w, "h": h}, "captured_at": "2026-10-29T10:00:00+09:00",
            "marks": {n: {"box": b, "px": {"x": round(b["x"] * w), "y": round(b["y"] * h),
                                           "w": round(b["w"] * w), "h": round(b["h"] * h)}, "how": "test"}
                      for n, b in boxes.items()}}
    p = img.with_name(img.stem + ".marks.json")
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _story(tmp_path, scenes, size=(1920, 1080), marks=None, image=True):
    """scenes: [(id, recipe, recipe_params)]。web 画像を size で作り、marks {id: {name: box}} を書く。"""
    sc = []
    for sid, recipe, rp in scenes:
        ref = f"captures/t/{sid}.png"
        if image:
            img = tmp_path / ref
            img.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", size, (200, 210, 220)).save(img)
            if marks and sid in marks:
                _marks(img, sid, marks[sid])
        s = {"id": sid, "heading": "位置を確かめる", "image": {"source": "web", "ref": ref, "label": "実キャプチャ"},
             "narration": "テストです。", "recipe": recipe, "duration_sec": 9,
             "capture": {"url": "http://localhost/", "steps": ["開く"]}}
        if rp is not None:
            s["recipe_params"] = rp
        sc.append(s)
    doc = {"reel": {"id": "marks-test", "title": "注釈テスト", "schema_version": "1.0.0", "audience": "C",
                    "kind": "tool_intro", "output_name": "marks_test"},
           "intro": {"summary": "s", "narration": "はじめ。"}, "scenes": sc,
           "outro": {"summary": "o", "narration": "おわり。"}}
    path = tmp_path / "t.storyboard.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _shape(slide, name):
    return next(s for s in slide.shapes if s.name == name)


def _rect(size):
    return _fit(size[0], size[1], IMAGE_BOX)


# ------------------------------------------------------------------ 座標の変換

@pytest.mark.parametrize("size", [(1920, 1080), (1000, 1000), (600, 1200), (2400, 800)],
                         ids=["16x9", "square", "tall", "wide"])
def test_box_lands_on_mark_for_any_aspect(tmp_path, size):
    b = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "target", "pad": 0})], size, {"s01": {"target": b}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.unresolved == []
    slide = Presentation(str(res.output)).slides[1]
    pic = next(s for s in slide.shapes if s.shape_type == 13)
    l, t, w, h = _rect(size)
    assert (pic.left, pic.top, pic.width, pic.height) == (l, t, w, h)  # 画像は縦横比を保って枠の中央
    box = _shape(slide, "Highlight Box")
    assert abs(box.left - (l + w * 0.1)) <= 1 and abs(box.top - (t + h * 0.2)) <= 1
    assert abs(box.width - w * 0.3) <= 1 and abs(box.height - h * 0.4) <= 1
    a = res.annotations[0]
    assert a.status == "mark" and a.mark == "target" and a.slide_emu["left"] == box.left


def test_pad_is_relative_to_image_width():
    b = {"x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2}
    p = pad_box(b, 0.01, 16 / 9)
    assert p["x"] == pytest.approx(0.19) and p["w"] == pytest.approx(0.22)
    assert p["y"] == pytest.approx(0.2 - 0.01 * 16 / 9) and p["h"] == pytest.approx(0.2 + 0.02 * 16 / 9)
    edge = pad_box({"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}, 0.05, 1.0)
    assert edge["x"] == 0 and edge["y"] == 0  # 画像の内側に収める


def test_default_pad_is_applied(tmp_path):
    b = {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "m"})], marks={"s01": {"m": b}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.annotations[0].box["x"] == pytest.approx(0.39)


# ------------------------------------------------------------------ 複数の枠

def _step_starts(sld):
    grp = sld.find(".//p:seq/p:cTn/p:childTnLst/p:par/p:cTn", NS)
    steps = grp.findall("p:childTnLst/p:par/p:cTn", NS)
    return [int(s.find("p:stCondLst/p:cond", NS).get("delay")) for s in steps], steps


def _box_times(sld, spid):
    """spid の枠が出る（entr）・消える（exit）時刻（スライド開始からの ms）。"""
    starts, steps = _step_starts(sld)
    out = {"entr": [], "exit": []}
    for st_start, st in zip(starts, steps):
        for e in st.findall("p:childTnLst/p:par/p:cTn", NS):
            tgt = e.find(".//p:spTgt", NS)
            if tgt is not None and tgt.get("spid") == str(spid) and e.get("presetClass") in out:
                out[e.get("presetClass")].append(st_start + int(e.find("p:stCondLst/p:cond", NS).get("delay")))
    return out


def test_multiple_boxes_appear_in_order_and_previous_is_removed(tmp_path):
    boxes = {"a": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "b": {"x": 0.6, "y": 0.5, "w": 0.3, "h": 0.3},
             "c": {"x": 0.4, "y": 0.7, "w": 0.1, "h": 0.1}}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": ["a", "b", "c"]})], marks={"s01": boxes})
    res = build_deck(sb, tmp_path / "o.pptx")
    slide = Presentation(str(res.output)).slides[1]
    shapes = [_shape(slide, n) for n in ("Highlight Box", "Highlight Box 2", "Highlight Box 3")]
    assert [a.mark for a in res.annotations] == ["a", "b", "c"] and [a.index for a in res.annotations] == [0, 1, 2]
    sld = slide_roots(res.output)[1]
    t = [_box_times(sld, s.shape_id) for s in shapes]
    assert len(t[0]["entr"]) == 1 and t[0]["exit"] and t[1]["exit"] and not t[2]["exit"]
    # 前の枠が消えてから次の枠が出る、順番どおり
    assert t[0]["entr"][0] < t[0]["exit"][0] < t[1]["entr"][0] < t[1]["exit"][0] < t[2]["entr"][0]
    # 均等割り: 9 秒のスライドの残り時間を 3 等分（±0.2 秒）
    first = t[0]["entr"][0]
    slot = (9000 - 300 - first) / 3
    assert t[0]["exit"][0] == pytest.approx(first + slot, abs=200)  # 2 つ目の枠の時刻に 1 つ目が消え始める
    assert t[1]["exit"][0] == pytest.approx(first + 2 * slot, abs=200)
    assert t[2]["exit"] == [] and t[2]["entr"][0] < 9000
    assert len(sld.findall(".//p:cTn[@presetClass='exit']", NS)) == 2
    assert all(e.get("presetID") == "10" for e in sld.findall(".//p:cTn[@presetClass='exit']", NS))


def test_box_times_follow_narration_paragraphs(tmp_path):
    boxes = {"a": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "b": {"x": 0.6, "y": 0.5, "w": 0.3, "h": 0.3}}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": ["a", "b"]})], marks={"s01": boxes})
    dj = tmp_path / "durations.json"
    dj.write_text(json.dumps({"format": "explainer-reel/narration-durations", "version": 1, "complete": True,
                              "pre_pause_sec": 0.3, "post_pause_sec": 0.5,
                              "items": [{"id": "intro", "slide_sec": 3.0},
                                        {"id": "s01", "slide_sec": 12.0, "paragraph_starts_sec": [0.0, 6.0]},
                                        {"id": "outro", "slide_sec": 3.0}]}), encoding="utf-8")
    res = build_deck(sb, tmp_path / "o.pptx", durations=dj)
    slide = Presentation(str(res.output)).slides[1]
    sld = slide_roots(res.output)[1]
    t2 = _box_times(sld, _shape(slide, "Highlight Box 2").shape_id)
    t1 = _box_times(sld, _shape(slide, "Highlight Box").shape_id)
    # 2 つ目の段落（WAV 先頭から 6.0 秒、余白 0.3 秒）で前の枠が消え始める
    assert t1["exit"][0] == pytest.approx(6300, abs=10) and t2["entr"][0] == pytest.approx(6600, abs=10)
    assert not any("均等" in w for w in res.warnings)


def test_paragraph_count_mismatch_falls_back_to_even_split(tmp_path):
    boxes = {"a": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "b": {"x": 0.6, "y": 0.5, "w": 0.3, "h": 0.3}}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": ["a", "b"]})], marks={"s01": boxes})
    dj = tmp_path / "durations.json"
    dj.write_text(json.dumps({"format": "explainer-reel/narration-durations", "version": 1,
                              "items": [{"id": "s01", "slide_sec": 12.0, "paragraph_starts_sec": [0.0, 3.0, 6.0]}]}),
                  encoding="utf-8")
    res = build_deck(sb, tmp_path / "o.pptx", durations=dj)
    assert any("均等" in w and "s01" in w for w in res.warnings)


# ------------------------------------------------------------------ 矢印

def test_arrow_tip_stops_on_mark_edge(tmp_path):
    target = {"x": 0.7, "y": 0.2, "w": 0.2, "h": 0.3}
    sb = _story(tmp_path, [("s01", "arrow_move", {"to": {"mark": "meter"}, "from_side": "left"})],
                marks={"s01": {"meter": target}})
    res = build_deck(sb, tmp_path / "o.pptx")
    a = res.annotations[0]
    assert a.status == "mark" and a.target == target
    assert a.end == pytest.approx({"x": 0.7, "y": 0.35})  # 左の辺の中点
    assert a.start == pytest.approx({"x": 0.55, "y": 0.35})  # 画像幅の 0.15 左
    slide = Presentation(str(res.output)).slides[1]
    arrow = _shape(slide, "Moving Arrow")
    l, t, w, h = _rect((1920, 1080))
    # 図形の先端（中心 + 半長 × 向き）が出発点にあり、移動量だけ動くと到着点（枠の辺）に着く
    ang = math.radians(arrow.rotation)
    tip_x = arrow.left + arrow.width / 2 + math.cos(ang) * arrow.width / 2
    tip_y = arrow.top + arrow.height / 2 + math.sin(ang) * arrow.width / 2
    assert tip_x == pytest.approx(l + w * 0.55, abs=2) and tip_y == pytest.approx(t + h * 0.35, abs=2)
    path = slide_roots(res.output)[1].find(".//p:animMotion", NS).get("path")
    dx, dy = map(float, re.match(r"M 0 0 L (\S+) (\S+) E", path).groups())
    assert tip_x + dx * SLIDE_W == pytest.approx(l + w * 0.7, abs=SLIDE_W * 0.0001 + 2)
    assert tip_y + dy * SLIDE_H == pytest.approx(t + h * 0.35, abs=SLIDE_H * 0.0001 + 2)


@pytest.mark.parametrize("side,start,end", [
    ("right", (0.65, 0.5), (0.5, 0.5)),
    ("top", (0.45, 0.4 - 0.15 * 16 / 9), (0.45, 0.4)),
    ("bottom", (0.45, 0.6 + 0.15 * 16 / 9), (0.45, 0.6)),
])
def test_arrow_from_sides(side, start, end):
    b = {"x": 0.4, "y": 0.4, "w": 0.1, "h": 0.2}
    s = side_start(b, side, 16 / 9)
    e = edge_point(s, b)
    assert (s["x"], s["y"]) == pytest.approx((start[0], min(1.0, max(0.0, start[1]))))
    assert (e["x"], e["y"]) == pytest.approx(end)


def test_arrow_explicit_from_hits_nearest_edge():
    b = {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}
    e = edge_point({"x": 0.1, "y": 0.1}, b)  # 左上から中心へ → 左上の角
    assert (e["x"], e["y"]) == pytest.approx((0.5, 0.5))


# ------------------------------------------------------------------ 未確定の注釈

@pytest.mark.parametrize("case,expect", [
    ("no_file", "記録ファイルがありません"),
    ("missing_name", "記録にありません"),
    ("no_params", "指定"),
    ("bad_format", "format"),
    ("no_image", "撮影画像がない"),
    ("bad_name", "書式"),
])
def test_unresolved_cases(tmp_path, case, expect):
    rp = {"mark": "Bad-Name" if case == "bad_name" else "wanted"}
    marks = {"s01": {"other": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}}}
    if case == "no_params":
        rp = None
    sb = _story(tmp_path, [("s01", "highlight_box", rp)],
                marks=None if case == "no_file" else marks, image=case != "no_image")
    if case == "bad_format":
        (tmp_path / "captures/t/s01.marks.json").write_text('{"format": "x"}', encoding="utf-8")
    res = build_deck(sb, tmp_path / "o.pptx")
    assert len(res.unresolved) == 1 and expect in res.unresolved[0].reason and res.unresolved[0].scene == "s01"
    a = res.annotations[0]
    assert a.status == "default" and a.box == {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}  # 既定位置


def test_unresolved_arrow_uses_default(tmp_path):
    sb = _story(tmp_path, [("s01", "arrow_move", {"to": {"mark": "nope"}})], marks={"s01": {}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert [u.mark for u in res.unresolved] == ["nope"]
    assert res.annotations[0].start == {"x": 0.2, "y": 0.5} and res.annotations[0].end == {"x": 0.8, "y": 0.5}


def test_coordinates_still_work_and_mark_wins(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}}),
                           ("s02", "highlight_box", {"mark": "m", "box": {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1},
                                                     "pad": 0})],
                marks={"s02": {"m": {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.unresolved == []
    assert [a.status for a in res.annotations] == ["coords", "mark"]
    assert res.annotations[1].box == pytest.approx({"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2})


def test_marks_record_mismatch_warns(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "m"})],
                marks={"s01": {"m": {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}}})
    mp = tmp_path / "captures/t/s01.marks.json"
    data = json.loads(mp.read_text(encoding="utf-8"))
    data["scene"], data["image_size"] = "s09", {"w": 1000, "h": 1000}
    mp.write_text(json.dumps(data), encoding="utf-8")
    res = build_deck(sb, tmp_path / "o.pptx")
    assert any("取り違え" in w for w in res.warnings) and any("縦横比" in w for w in res.warnings)


def test_cli_reports_unresolved_and_writes_overlay(tmp_path, capsys):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "x"})])
    png = tmp_path / "check" / "overlay.png"
    assert deck_cli.main([str(sb), "--out", str(tmp_path / "o.pptx"),
                          "--overlay", str(png)]) == 0
    cap = capsys.readouterr()
    assert "未確定の注釈が 1 件" in cap.err and "s01（x）" in cap.err and "unresolved_marks=1" in cap.out
    assert png.is_file()


# ------------------------------------------------------------------ 一覧画像

def test_overlay_draws_boxes_where_the_slide_puts_them(tmp_path):
    boxes = {"a": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}, "b": {"x": 0.6, "y": 0.1, "w": 0.3, "h": 0.3}}
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": ["a", "b"], "pad": 0}),
                           ("s02", "arrow_move", {"to": {"mark": "b"}})],
                marks={"s01": boxes, "s02": {"b": boxes["b"]}})
    png = tmp_path / "overlay.png"
    res = build_deck(sb, tmp_path / "o.pptx", overlay=png)
    assert res.overlay == png
    im = Image.open(png).convert("RGB")
    assert im.width == ov.COLS * ov.TILE_W + (ov.COLS + 1) * ov.MARGIN
    tile_h = round(ov.TILE_W * 9 / 16)
    x0, y0 = ov.MARGIN, ov.MARGIN + ov.HEADER_H  # 1 枚目の画像の左上
    # 枠 a の左の辺の上（縦の中ほど）が赤い
    px = im.getpixel((x0 + int(0.1 * ov.TILE_W) + 1, y0 + int(0.4 * tile_h)))
    assert px[0] > 180 and px[1] < 90 and px[2] < 90
    # 枠の内側は撮影画像の色のまま
    inner = im.getpixel((x0 + int(0.25 * ov.TILE_W), y0 + int(0.4 * tile_h)))
    assert inner == (200, 210, 220)
    # 2 枚目（矢印）: 到着点（枠 b の左の辺の中点）の少し手前が赤い
    x1 = ov.MARGIN * 2 + ov.TILE_W
    ex = x1 + int(0.6 * ov.TILE_W) - 4
    ey = y0 + int(0.25 * tile_h)
    assert im.getpixel((ex, ey))[0] > 180


def test_overlay_marks_unresolved_and_missing_images(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "x"})], image=False)
    png = tmp_path / "overlay.png"
    build_deck(sb, tmp_path / "o.pptx", overlay=png)
    im = Image.open(png).convert("RGB")
    # 未確定は橙色で既定位置（中央 50%）に描く
    tile_h = round(ov.TILE_W * 9 / 16)
    px = im.getpixel((ov.MARGIN + int(0.25 * ov.TILE_W) + 1, ov.MARGIN + ov.HEADER_H + int(0.5 * tile_h)))
    assert px == ov.ORANGE


# ------------------------------------------------------------------ Web 撮影の台本（mark の名前で指す）

def test_web_storyboard_uses_marks():
    doc = load_storyboard(WEB, None)
    got = {s["id"]: (s["recipe"], s.get("recipe_params")) for s in doc["scenes"]}
    assert got == {
        # s01〜s04 は注釈まわりを拡大（s05・s06 は 2 か所が離れているため拡大しない）
        "s01": ("highlight_box", {"mark": ["input_a", "input_b"], "zoom": True}),
        "s02": ("highlight_box", {"mark": ["choice_a", "choice_b"], "zoom": "per_mark"}),  #
        "s03": ("highlight_box", {"mark": "main_view", "zoom": True}),
        "s04": ("arrow_move", {"to": {"mark": "meter"}, "from_side": "left", "zoom": True}),
        "s05": ("highlight_box", {"mark": ["main_view", "alert"], "zoom": "per_mark"}),
        "s06": ("highlight_box", {"mark": ["main_view", "meter"], "zoom": "per_mark"}),
    }


def test_web_without_captures_reports_all_marks_unresolved(tmp_path):
    res = build_deck(WEB, tmp_path / "d.pptx")
    assert len(res.unresolved) == 10 and {u.scene for u in res.unresolved} == {f"s0{i}" for i in range(1, 7)}
    assert all(u.reason.startswith("撮影画像がない") for u in res.unresolved)


def test_resolve_scene_ignores_other_recipes():
    sm = resolve_scene({"id": "s01", "recipe": "fade_sequence", "recipe_params": {"mark": "x"}}, None)
    assert sm.annotations == [] and sm.unresolved == []
