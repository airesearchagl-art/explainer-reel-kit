"""Morph の本番採用と、枠ごとの拡大（zoom: per_mark、カメラ移動）。"""
import json

import pytest
from PIL import Image
from pptx import Presentation

from deck_helpers import NS, slide_roots, slide_transition
from test_deck_marks import _story

from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.deck.builder import IMAGE_BOX, MIN_PART_MS, _fit, split_timeline
from explainer_reel_kit.deck.timing import MORPH_MS
from explainer_reel_kit.deck.zoom import is_per_mark, parse_zoom

TOP = {"x": 0.05, "y": 0.06, "w": 0.18, "h": 0.10}
BOTTOM = {"x": 0.70, "y": 0.80, "w": 0.22, "h": 0.12}


def _split_story(tmp_path, marks=("a", "b"), sec=12, boxes=None):
    boxes = boxes or {"a": TOP, "b": BOTTOM, "c": {"x": 0.45, "y": 0.45, "w": 0.1, "h": 0.1}}
    sb = _story(tmp_path, [("s01", "fade_sequence", None),
                           ("s02", "highlight_box", {"mark": list(marks), "zoom": "per_mark", "pad": 0}),
                           ("s03", "fade_sequence", None)],
                marks={"s02": {m: boxes[m] for m in marks}})
    doc = json.loads(sb.read_text(encoding="utf-8"))
    doc["scenes"][1]["duration_sec"] = sec
    doc["scenes"][1]["on_screen_text"] = "画面テキスト"
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return sb


def _dj(tmp_path, s02):
    p = tmp_path / "durations.json"
    items = [{"id": "intro", "slide_sec": 4.0}, {"id": "s01", "slide_sec": 5.0}, {"id": "s02", **s02},
             {"id": "s03", "slide_sec": 5.0}, {"id": "outro", "slide_sec": 4.0}]
    p.write_text(json.dumps({"format": "explainer-reel/narration-durations", "version": 2, "pre_pause_sec": 0.3,
                             "post_pause_sec": 0.5, "items": items}), encoding="utf-8")
    return p


# ------------------------------------------------------------------ 書き方

def test_parse_per_mark():
    assert is_per_mark("per_mark") and is_per_mark({"mode": "per_mark", "margin": 0.1})
    assert not is_per_mark(True) and not is_per_mark(None)
    assert parse_zoom("per_mark") == (True, 0.08, None)
    assert parse_zoom({"mode": "per_mark", "margin": 0.1}) == (True, 0.1, None)
    assert parse_zoom({"mode": "x"})[2] is not None


# ------------------------------------------------------------------ 分けたスライド

def test_scene_is_split_into_one_slide_per_box(tmp_path):
    res = build_deck(_split_story(tmp_path), tmp_path / "o.pptx")
    assert res.slide_ids == ["intro", "s01", "s02#1", "s02#2", "s03", "outro"]
    roots = slide_roots(res.output)
    assert [r.find("p:cSld", NS).get("name") for r in roots] == [f"er:{n}" for n in res.slide_ids]
    prs = Presentation(str(res.output))
    p1, p2 = prs.slides[2], prs.slides[3]
    # ノートは最初のスライドにまとめる
    assert p1.notes_slide.notes_text_frame.text == "テストです。" and p2.notes_slide.notes_text_frame.text == ""
    # 見出し・画面テキスト・出所ラベルは同じ名前・同じ位置（動かない）
    for name in ("Heading", "On-screen Text", "Provenance Label"):
        a = next(s for s in p1.shapes if s.name == name)
        b = next(s for s in p2.shapes if s.name == name)
        assert (a.left, a.top, a.width, a.height, a.text_frame.text) == (b.left, b.top, b.width, b.height, b.text_frame.text)
    # 撮影画像と枠は !! 付きの同じ名前（Morph で同じ物として動く）
    for sl in (p1, p2):
        names = [s.name for s in sl.shapes]
        assert names.count("!!Shot") == 1 and names.count("!!Box") == 1


def test_each_part_zooms_on_its_own_box(tmp_path):
    res = build_deck(_split_story(tmp_path), tmp_path / "o.pptx")
    parts = res.split["s02"]
    assert [p["mark"] for p in parts] == ["a", "b"]
    prs = Presentation(str(res.output))
    for k, (slide, b) in enumerate(zip((prs.slides[2], prs.slides[3]), (TOP, BOTTOM))):
        v = parts[k]["view"]
        pic = next(s for s in slide.shapes if s.name == "!!Shot")
        assert pic.crop_left == pytest.approx(v["x"], abs=1e-3) and pic.crop_top == pytest.approx(v["y"], abs=1e-3)
        assert v["x"] <= b["x"] and v["x"] + v["w"] >= b["x"] + b["w"]
        assert v["y"] <= b["y"] and v["y"] + v["h"] >= b["y"] + b["h"]
        assert v["w"] < 1  # 拡大されている
        box = next(s for s in slide.shapes if s.name == "!!Box")
        cx = pic.left + pic.width * ((b["x"] - v["x"]) / v["w"])
        assert box.left == pytest.approx(cx, abs=400)  # view は 4 桁に丸めた記録から計算（0.0004in 以内）
    # 上の部品と下の部品で、表示範囲（カメラ）が動く
    assert parts[1]["view"]["y"] > parts[0]["view"]["y"] and parts[1]["view"]["x"] > parts[0]["view"]["x"]
    assert [a.part for a in res.annotations if a.scene == "s02"] == [0, 1]


def test_split_slides_are_joined_by_morph(tmp_path):
    res = build_deck(_split_story(tmp_path), tmp_path / "o.pptx")
    roots = slide_roots(res.output)
    tr1, kind1 = slide_transition(roots[2])
    tr2, kind2 = slide_transition(roots[3])
    assert kind1 == "none" and kind2 == "morph"
    ac = roots[3].find("mc:AlternateContent", NS)
    choice = ac.find("mc:Choice", NS)
    assert choice.get("Requires") == "p159" and choice.nsmap["p159"] == NS["p159"]
    assert tr2.find("p159:morph", NS).get("option") == "byObject"
    assert tr2.get(f"{{{NS['p14']}}}dur") == str(res.split["s02"][1]["morph_ms"])
    fb = ac.find("mc:Fallback/p:transition", NS)
    assert fb.find("p:fade", NS) is not None and fb.get("advTm") == tr2.get("advTm") and fb.get("advClick") == "0"
    assert roots[3].find("p:transition", NS) is None
    # 子要素の順（cSld, clrMapOvr, 切替, timing）
    tags = [c.tag.split("}")[1] for c in roots[3]]
    assert tags[:2] == ["cSld", "clrMapOvr"] and tags[2] == "AlternateContent"
    # 2 枚目は枠の点滅だけ（変形で移ってくる）
    effects = roots[3].findall(".//p:cTn[@presetClass]", NS)
    assert [e.get("presetClass") for e in effects] == ["emph"]


# ------------------------------------------------------------------ 秒数

def _scene_total(res, sid):
    return sum(p["adv_ms"] + p["morph_ms"] for p in res.split[sid])


def test_split_total_equals_scene_seconds_equal_split(tmp_path):
    res = build_deck(_split_story(tmp_path, sec=12), tmp_path / "o.pptx")
    assert _scene_total(res, "s02") == 12000
    parts = res.split["s02"]
    assert parts[0]["morph_ms"] == 0 and parts[1]["morph_ms"] == MORPH_MS


def test_split_follows_paragraph_starts(tmp_path):
    dj = _dj(tmp_path, {"slide_sec": 11.0, "paragraph_starts_sec": [0.0, 5.0]})
    res = build_deck(_split_story(tmp_path), tmp_path / "o.pptx", durations=dj)
    parts = res.split["s02"]
    # 2 段落目（WAV 先頭から 5.0 秒 ＋ 余白 0.3 秒）で、2 枚目への変形が始まる
    assert parts[0]["adv_ms"] == 5300
    assert _scene_total(res, "s02") == 11000
    assert not any("段落" in w for w in res.warnings)


def test_split_paragraph_mismatch_warns_and_splits_evenly(tmp_path):
    dj = _dj(tmp_path, {"slide_sec": 12.0, "paragraph_starts_sec": [0.0, 3.0, 6.0]})
    res = build_deck(_split_story(tmp_path), tmp_path / "o.pptx", durations=dj)
    assert any("段落 3 個" in w and "均等" in w for w in res.warnings)
    assert _scene_total(res, "s02") == 12000


def test_three_boxes(tmp_path):
    res = build_deck(_split_story(tmp_path, marks=("a", "c", "b"), sec=15), tmp_path / "o.pptx")
    assert len(res.split["s02"]) == 3 and _scene_total(res, "s02") == 15000
    assert res.slide_ids[2:5] == ["s02#1", "s02#2", "s02#3"]


def test_split_timeline_shortens_morph_when_paragraphs_are_close():
    adv, morph, w = split_timeline(2, 4000, [2000, 2600])
    assert sum(adv) + sum(morph) == 4000 and morph[1] < MORPH_MS and adv[1] == MIN_PART_MS
    assert w == []
    adv, morph, w = split_timeline(2, 3000, [2000, 2900])
    assert w and adv[1] == MIN_PART_MS // 2  # 短すぎるときは最短にして警告（合計が延びる）


def test_per_mark_falls_back_without_marks_or_image(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": ["a", "b"], "zoom": "per_mark"})], marks={"s01": {}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.split == {} and res.slide_ids == ["intro", "s01", "outro"]
    assert any("per_mark" in w for w in res.warnings)


def test_per_mark_with_one_box_is_plain_zoom(tmp_path):
    sb = _story(tmp_path, [("s01", "highlight_box", {"mark": "a", "zoom": "per_mark"})], marks={"s01": {"a": TOP}})
    res = build_deck(sb, tmp_path / "o.pptx")
    assert res.split == {} and "s01" in res.views


# ------------------------------------------------------------------ 一覧画像

def test_overlay_has_one_tile_per_split_slide(tmp_path):
    from explainer_reel_kit.deck import overlay as ov

    png = tmp_path / "ov.png"
    build_deck(_split_story(tmp_path), tmp_path / "o.pptx", overlay=png)
    im = Image.open(png)
    tiles = 4  # s01, s02#1, s02#2, s03
    rows = (tiles + ov.COLS - 1) // ov.COLS
    assert im.height > rows * ov.TILE_W * 9 / 16
