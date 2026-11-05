"""注釈位置（marks@1）の共通部分: 画像座標への変換と検証、形式の検査、台本の参照の解決。"""
from __future__ import annotations

from pathlib import Path

import pytest

from explainer_reel_kit import marks as mk


def _m(x, y, w, h, how="selector: #a"):
    return {"css": (x, y, w, h), "how": how}


def test_marks_path():
    assert mk.marks_path(Path("a/s01_page.png")) == Path("a/s01_page.marks.json")


def test_storyboard_mark_refs():
    assert mk.storyboard_mark_refs({"recipe_params": {"mark": ["a", "b", "a"]}}) == ["a", "b"]
    assert mk.storyboard_mark_refs({"recipe_params": {"to": {"mark": "c"}, "from": {"mark": "d"}}}) == ["c", "d"]
    assert mk.storyboard_mark_refs({"recipe_params": {"box": {"x": 0.1}}}) == []
    assert mk.storyboard_mark_refs({}) == []


def test_to_image_coordinates_and_scale():
    ok, errs = mk.to_image({"a": _m(100, 50, 200, 80)}, (0, 0), 1, 800, 600)
    assert errs == []
    assert ok["a"]["px"] == {"x": 100, "y": 50, "w": 200, "h": 80}
    assert ok["a"]["box"] == {"x": 0.125, "y": 0.0833, "w": 0.25, "h": 0.1333}
    # 原点（element 撮影の切り抜き）と device_scale_factor 2
    ok, _ = mk.to_image({"a": _m(110, 60, 50, 40)}, (100, 50), 2, 400, 400)
    assert ok["a"]["px"] == {"x": 20, "y": 20, "w": 100, "h": 80}


@pytest.mark.parametrize("m,msg", [
    ({"error": "見つかりません: #x"}, "見つかりません"),
    (_m(0, 0, 5, 50), "小さすぎます"),
    (_m(700, 500, 300, 300), "はみ出しています"),
])
def test_to_image_validation(m, msg):
    ok, errs = mk.to_image({"x": m}, (0, 0), 1, 800, 600)
    assert ok == {} and msg in errs[0] and errs[0].startswith("mark x:")


def test_to_image_small_overhang_is_clipped():
    ok, errs = mk.to_image({"a": _m(-4, 10, 200, 100)}, (0, 0), 1, 800, 600)  # 2% はみ出し
    assert errs == [] and ok["a"]["px"] == {"x": 0, "y": 10, "w": 196, "h": 100}


def _doc(**marks):
    return {"format": mk.FORMAT, "scene": "s01", "source": "generated", "image": "s01.png",
            "image_size": {"w": 2420, "h": 1000}, "marks": marks}


def test_validate_doc_ok_and_errors():
    good = {"box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "px": {"x": 242, "y": 100, "w": 484, "h": 200}, "how": "x"}
    assert mk.validate_doc(_doc(a=good)) == []
    bad = _doc(**{"A": good, "b": {"box": {"x": 0.9, "y": 0, "w": 0.2, "h": 0.1}, "px": {"x": 1, "y": 1, "w": 1, "h": 1}}})
    bad["format"] = "x"
    errs = " ".join(mk.validate_doc(bad))
    assert "format" in errs and "marks.A" in errs and "0〜1" in errs
    assert mk.validate_doc([]) and mk.validate_doc({**_doc(), "source": "sketchup"})


def test_load_and_resolve_refs(tmp_path):
    good = {"box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, "px": {"x": 242, "y": 100, "w": 484, "h": 200}, "how": "x"}
    p = tmp_path / "s01.marks.json"
    mk.write(p, _doc(inputs=good))
    doc = mk.load(p)
    found, missing = mk.resolve_refs({"recipe_params": {"mark": ["inputs", "nothing"]}}, doc)
    assert found == {"inputs": good["box"]} and missing == ["nothing"]
    p.write_text("{", encoding="utf-8")
    with pytest.raises(mk.MarksError):
        mk.load(p)
