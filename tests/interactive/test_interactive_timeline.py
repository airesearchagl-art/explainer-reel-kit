"""中間データ（render timeline）の検証と、場面コードに渡す T。"""
from __future__ import annotations


import pytest
from interactive_helpers import timeline_doc, write_doc

from explainer_reel_kit.interactive.timeline import (Timeline, TimelineError, _schema, load_timeline_doc,
                                                     validate_timeline)


def test_schema_is_valid_draft_2020_12():
    from jsonschema import Draft202012Validator

    schema = _schema()
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["format"]["const"] == "explainer-reel/render-timeline@1"


def test_valid_doc_passes():
    assert validate_timeline(timeline_doc()) == []


@pytest.mark.parametrize("mutate, word", [
    (lambda d: d["scenes"][1].update(start_frame=50), "続いていません"),          # 場面の間に隙間
    (lambda d: d["scenes"][0].update(start_frame=3), "0 フレームから"),
    (lambda d: d["scenes"][1].update(end_frame=80), "total_frames"),
    (lambda d: d["sentences"][0].update(scene="zz"), "場面 zz"),
    (lambda d: d["cues"][1].update(start_frame=30), "重なる"),                  # 字幕の重なり
    (lambda d: d["cues"][1].update(end_frame=95), "total_frames"),
    (lambda d: d["cues"][0].update(sentence="nope"), "文 nope"),
    (lambda d: d["sentences"][1].update(id="a-1"), "重複"),
    (lambda d: d.update(fps=25), "schema"),                                    # 今は 30 fps だけ
    (lambda d: d["scenes"][0].update(id="bad id"), "schema"),
])
def test_invalid_docs_are_rejected(mutate, word):
    d = timeline_doc()
    mutate(d)
    errors = validate_timeline(d)
    assert errors and any(word in e for e in errors), errors


def test_load_reports_path_and_errors(tmp_path):
    d = timeline_doc()
    d["scenes"][1]["start_frame"] = 50
    p = write_doc(tmp_path / "tl.json", d)
    with pytest.raises(TimelineError, match="tl.json"):
        load_timeline_doc(p)


def test_cue_and_scene_lookup():
    T = Timeline(timeline_doc())
    assert T.cue_at(8) is None and T.cue_at(9)["sentence"] == "a-1" and T.cue_at(38)["number"] == 1
    assert T.cue_at(39) is None and T.cue_at(48)["number"] == 2 and T.cue_at(81) is None
    assert T.scene_at(0)["id"] == "a" and T.scene_at(44)["id"] == "a" and T.scene_at(45)["id"] == "b"
    assert T.scene_at(89)["id"] == "b" and T.by_id["b"]["start"] == 1.5
    assert T.nframes == 90 and T.total == 3.0


def test_at_estimates_by_character_weight_and_leads():
    T = Timeline(timeline_doc())
    assert T.S("a-1") == 0.3 and T.E("a-1") == 1.3
    assert T.at("a-1", "空気") == 0.3                     # 文の頭は開始そのもの（先行しない）
    t = T.at("a-1", "水蒸気")                              # 読点の直後。無音が無ければ比例配分 − 0.1 秒
    assert 0.3 < t < 1.3
    assert T.log["a-1|水蒸気"] == t                        # 使った時刻は記録に残る（cue_points.json）


def test_at_snaps_to_pause_after_comma():
    doc = timeline_doc()
    T0 = Timeline(doc)
    est = T0.at("a-1", "水蒸気") + 0.10
    T = Timeline(doc, pauses={"a-1": [[est - 0.4, est + 0.3]]})
    assert T.at("a-1", "水蒸気") == round(est + 0.3 - 0.10, 3)   # 無音の終わりに合わせ、0.1 秒先行


def test_at_uses_measured_words_first():
    doc = timeline_doc()
    doc["sentences"][0]["words"] = [{"text": "空気には、", "start_sec": 0.3}, {"text": "水蒸気が", "start_sec": 0.72},
                                    {"text": "含まれています。", "start_sec": 0.95}]
    T = Timeline(doc)
    assert T.at("a-1", "水蒸気") == round(0.72 - 0.10, 3)
    assert T.at("a-1", "含まれ") == round(0.95 - 0.10, 3)


def test_at_weights_can_be_overridden():
    doc = timeline_doc(sentences=[{"id": "x", "scene": "a", "spoken": "あ12い", "start_sec": 0.0, "end_sec": 1.0},
                                  {"id": "y", "scene": "b", "spoken": "う", "start_sec": 1.6, "end_sec": 2.0}],
                       cues=[])
    a = Timeline(doc).at("x", "い", lead=0)                         # 数字 2.6（前半の実績）
    b = Timeline(doc, weights={"digit": 2.0}).at("x", "い", lead=0)  # 数字 2.0（後半の実績）
    assert a == round((1 + 5.2) / (1 + 5.2 + 1), 3) and b == round(5 / 6, 3)


def test_unknown_sentence_or_phrase_is_an_error():
    T = Timeline(timeline_doc())
    with pytest.raises(TimelineError, match="文 zz"):
        T.S("zz")
    with pytest.raises(TimelineError, match="ありません"):
        T.at("a-1", "存在しない語")
