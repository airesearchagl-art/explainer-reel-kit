"""kind: explainer（kit-1.1.0）・解説のひな形・説明図の部品 7 種の見本。"""
from __future__ import annotations

import copy
import json
import re

import pytest

from conftest import ROOT, write_storyboard
from explainer_reel_kit import diagram as dg
from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.cli import main as erkit

TEMPLATES = ROOT / "src" / "explainer_reel_kit" / "data" / "templates"
EXPLAINER_TEMPLATE = TEMPLATES / "explainer.storyboard.md"
PARTS = ROOT / "samples" / "_parts"
PARTS_STORYBOARD = PARTS / "parts.storyboard.md"
CSS = ROOT / "samples" / "_shared" / "diagram.css"
#: 部品の名前 → 見本の data-mark（docs/design/diagram.md・samples/_parts/README.md と同じ）
PART_MARKS = {
    "section": ["layer_glass_in", "layer_air", "layer_coat"],
    "compare": ["row_single", "row_double", "row_coated"],
    "range": ["band_single", "band_double", "band_coated", "target"],
    "flow": ["step_1", "step_2", "step_3", "step_4"],
    "cards": ["card_1", "card_2", "card_3"],
    "branch": ["question", "leaf_cold", "leaf_sun", "leaf_both"],
    "analogy": ["everyday", "topic", "mapping"],
}


def _doc():
    return sb.load_storyboard(EXPLAINER_TEMPLATE)


# ------------------------------------------------------------------ kind と版

def test_schema_knows_explainer_and_kit_1_1_0():
    schema = sb.load_schema()
    reel = schema["$defs"]["reel"]["properties"]
    assert reel["kind"]["enum"] == ["tool_intro", "work_manual", "explainer"]
    assert "kit-1.1.0" in reel["schema_version"]["enum"]
    assert sb.SCHEMA_VERSION == "kit-1.1.0" and sb.KINDS == ("tool_intro", "work_manual", "explainer")


def test_explainer_storyboard_passes():
    rep = sb.validate_storyboard(_doc())
    assert rep.errors == [] and rep.warnings == []


def test_explainer_needs_kit_1_1_0():
    for old in ("1.1.0", "kit-1.0.0"):
        doc = _doc()
        doc["reel"]["schema_version"] = old
        errors = [e for e in sb.validate_storyboard(doc).errors if "reel.kind" in e]
        assert errors == ["[version] reel.kind 'explainer' は kit-1.1.0 の種別です。schema_version を kit-1.1.0 にしてください"]


def test_existing_kinds_still_pass_with_old_and_new_versions():
    doc = sb.load_storyboard(ROOT / "samples" / "u-value" / "u-value.storyboard.md")
    assert doc["reel"]["schema_version"] == "kit-1.0.0"
    assert sb.validate_storyboard(doc, base_dir=ROOT / "samples" / "u-value").errors == []
    newer = copy.deepcopy(doc)
    newer["reel"]["schema_version"] = "kit-1.1.0"
    assert sb.validate_storyboard(newer, base_dir=ROOT / "samples" / "u-value").errors == []


@pytest.mark.parametrize("kind", ["lesson", "explain", "Explainer", ""])
def test_unknown_kind_is_an_error(kind):
    doc = _doc()
    doc["reel"]["kind"] = kind
    errors = sb.validate_storyboard(doc).errors
    assert any(e.startswith("[schema] reel/kind") for e in errors), errors


def test_explainer_scene_count_is_5_to_7():
    doc = _doc()
    doc["scenes"].append(dict(doc["scenes"][-1], id="s08"))  # 8 シーン: tool_intro なら推奨の中、explainer は外
    assert sb.validate_storyboard(doc).warnings == ["[scenes] シーン数 8（推奨 5〜7）"]
    doc["reel"]["kind"] = "tool_intro"
    assert sb.validate_storyboard(doc).warnings == []
    short = _doc()
    short["scenes"] = short["scenes"][:4]
    assert sb.validate_storyboard(short).warnings == ["[scenes] シーン数 4（推奨 5〜7）"]


def test_check_shows_the_kind(capsys):
    assert erkit(["check", str(EXPLAINER_TEMPLATE)]) == 0
    out = capsys.readouterr().out
    assert "（区分: general、エラー 0、警告 0）" in out and "種別: explainer（一般の解説）" in out


# ------------------------------------------------------------------ ひな形

def test_templates_pass_check(capsys):
    assert erkit(["check", "--strict", str(EXPLAINER_TEMPLATE)]) == 0
    assert erkit(["check", str(TEMPLATES / "storyboard.md")]) == 0  # シーン数の警告は可
    assert sb.load_storyboard(TEMPLATES / "storyboard.md")["reel"]["schema_version"] == "kit-1.1.0"


def test_explainer_template_follows_the_structure():
    doc = _doc()
    text = EXPLAINER_TEMPLATE.read_text(encoding="utf-8")
    assert doc["reel"]["kind"] == "explainer" and doc["reel"]["confidentiality"] == "general"
    assert 5 <= len(doc["scenes"]) <= 7
    assert "問い（身近な場面）→ しくみ → 比べる・条件 → 選び方・減らし方 → まとめ" in text
    # 各シーンのコメントに、どの部品を使うか。指す mark は見本の data-mark
    for sc in doc["scenes"]:
        assert sc["image"] == {"source": "generated", "ref": sc["image"]["ref"], "label": "説明用再構成図"}
        assert sc["capture"]["tool"] == "html" and sc["capture"]["src"].startswith("diagrams/")
        marks = sc["recipe_params"]["mark"]
        marks = marks if isinstance(marks, list) else [marks]
        assert all(any(m in names for names in PART_MARKS.values()) for m in marks), (sc["id"], marks)
    for part in PART_MARKS:
        assert f"{part}.html" in text, part
    assert "SOURCES.md" in text and "未確認" in text and "確かめた日" in text


def test_templates_are_packaged():
    from importlib import resources

    files = resources.files("explainer_reel_kit") / "data" / "templates"
    assert (files / "explainer.storyboard.md").is_file()


# ------------------------------------------------------------------ 部品

def test_each_part_has_a_sample_with_the_documented_marks():
    readme = (PARTS / "README.md").read_text(encoding="utf-8")
    design = (ROOT / "docs" / "design" / "diagram.md").read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for part, marks in PART_MARKS.items():
        html = (PARTS / f"{part}.html").read_text(encoding="utf-8")
        assert re.findall(r'data-mark="([a-z0-9_]+)"', html) == marks, part
        assert 'href="../_shared/diagram.css"' in html and "http" not in html.replace("<!doctype html>", "")
        assert "<style" not in html  # 部品のクラスだけで描く
        assert f"[{part}.html]({part}.html)" in readme and f"`{part}.html`" in design
        for mark in marks:
            assert f"`{mark}`" in readme, (part, mark)
    for cls in (".section", "table.compare", ".range", ".flow", ".cards", ".branch", ".analogy", ".map"):
        assert cls in css, cls


def test_part_colors_are_four_and_never_red():
    css = CSS.read_text(encoding="utf-8")
    assert sorted(set(re.findall(r"^\.c-([a-z]+)\s", css, re.M))) == ["amber", "blue", "gray", "teal"]
    for part in PART_MARKS:
        html = (PARTS / f"{part}.html").read_text(encoding="utf-8")
        assert set(re.findall(r"\bc-([a-z]+)", html)) <= {"blue", "amber", "teal", "gray"}
        assert not re.search(r"\bred\b|#f00\b|#ff0000", html, re.I)


def test_part_font_sizes_are_readable():
    css = CSS.read_text(encoding="utf-8")
    start = css.index("解説の部品")
    sizes = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", css[start:])]
    assert sizes and min(sizes) >= 32


def test_parts_storyboard_passes_check():
    rep = sb.validate_file(PARTS_STORYBOARD)
    assert rep.errors == [] and rep.warnings == []
    doc = sb.load_storyboard(PARTS_STORYBOARD)
    assert [sc["capture"]["src"] for sc in doc["scenes"]] == [f"{p}.html" for p in PART_MARKS]


def test_parts_are_drawn_with_marks(tmp_path, browser_opts, capsys):
    """7 種の見本が erkit diagram で 2420×1000 の PNG と mark になる（ブラウザが無ければ skip）。"""
    from explainer_reel_kit.capture.web.capture import png_size

    out = tmp_path / "parts"
    res = dg.run_diagram(PARTS_STORYBOARD, out, log=lambda *_: None, **browser_opts)
    assert res["failed"] == 0 and res["ok"] == len(PART_MARKS)
    for part, marks in PART_MARKS.items():
        png = out / "assets" / f"{part}.png"
        assert png_size(png) == (dg.WIDTH, dg.HEIGHT)
        data = json.loads((out / "assets" / f"{part}.marks.json").read_text(encoding="utf-8"))
        assert sorted(data["marks"]) == sorted(marks), part
        for name, m in data["marks"].items():  # 図の中にあり、指せる大きさ
            b, px = m["box"], m["px"]
            assert px["w"] >= 8 and px["h"] >= 8, (part, name)
            assert b["x"] >= 0 and b["y"] >= 0 and b["x"] + b["w"] <= 1.0001 and b["y"] + b["h"] <= 1.0001, (part, name)
    result = json.loads((out / dg.RESULT_NAME).read_text(encoding="utf-8"))
    assert result["network"] == "blocked"
    assert not any(sc.get("notes") for sc in result["scenes"]), result["scenes"]  # はみ出しの注記なし


def test_parts_overview_from_the_cli(tmp_path, browser_opts):
    args = ["diagram", str(PARTS_STORYBOARD), "--out", str(tmp_path / "o"), "--overlay", str(tmp_path / "o" / "all.png")]
    if browser_opts.get("channel"):
        args += ["--channel", browser_opts["channel"]]
    assert erkit(args) == 0
    assert (tmp_path / "o" / "all.png").is_file()


RANGE_HTML = """<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="diagram.css">
</head><body><div class="wrap"><div class="range">
<div class="lane"><div class="lane-label">狭い</div><div class="track" data-mark="track_a">
  <div class="band c-gray" style="--l:50%;--w:1%" data-mark="narrow"></div></div></div>
<div class="lane"><div class="lane-label">点</div><div class="track" data-mark="track_b">
  <div class="band c-amber" style="--l:99%;--w:0%" data-mark="point"></div></div></div>
<div class="lane"><div class="lane-label">広い</div><div class="track" data-mark="track_c">
  <div class="band c-blue" style="--l:10%;--w:40%" data-mark="wide"></div></div></div>
<div class="axis"><div class="tick" style="left:0%">0</div><div class="tick" style="left:100%">10</div></div>
</div></div></body></html>"""


def test_range_band_has_a_minimum_width_centered_on_the_range(tmp_path, browser_opts):
    """狭い範囲でも帯は最小幅（73px）以上で、帯の中心は範囲の中心。mark の枠は帯と一致する。"""
    (tmp_path / "diagrams").mkdir()
    (tmp_path / "diagrams" / "diagram.css").write_text(CSS.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "diagrams" / "s01.html").write_text(RANGE_HTML, encoding="utf-8")
    path = write_storyboard(tmp_path / "t.storyboard.json", [{
        "id": "s01", "image": {"source": "generated", "ref": "assets/s01.png", "label": "説明用再構成図"},
        "capture": {"tool": "html", "src": "diagrams/s01.html", "prompt": "範囲の帯"}}])
    res = dg.run_diagram(path, log=lambda *_: None, **browser_opts)
    assert res["failed"] == 0
    marks = json.loads((tmp_path / "assets" / "s01.marks.json").read_text(encoding="utf-8"))["marks"]
    px = {name: m["px"] for name, m in marks.items()}
    minimum = 73

    def center(box):
        return box["x"] + box["w"] / 2

    for band, track, lo, width in (("narrow", "track_a", 0.50, 0.01), ("point", "track_b", 0.99, 0.0),
                                   ("wide", "track_c", 0.10, 0.40)):
        b, t = px[band], px[track]
        want_center = t["x"] + (lo + width / 2) * t["w"]
        want_width = max(width * t["w"], minimum)
        assert abs(center(b) - want_center) <= 1.5, (band, b, t)
        assert abs(b["w"] - want_width) <= 1.5, (band, b, t)
    assert abs(px["narrow"]["w"] - minimum) <= 1 and abs(px["point"]["w"] - minimum) <= 1
    # 広い帯は範囲そのまま（始まりと終わりが目盛りと一致）
    assert abs(px["wide"]["x"] - (px["track_c"]["x"] + 0.10 * px["track_c"]["w"])) <= 1.5


def test_range_sample_narrow_band_is_markable(tmp_path, browser_opts):
    res = dg.run_diagram(PARTS_STORYBOARD, tmp_path, only=["s03"], log=lambda *_: None, **browser_opts)
    assert res["failed"] == 0
    marks = json.loads((tmp_path / "assets" / "range.marks.json").read_text(encoding="utf-8"))["marks"]
    assert marks["band_single"]["px"]["w"] >= 73 and marks["band_single"]["px"]["h"] >= 8


def test_range_docs_describe_the_minimum_width():
    css = CSS.read_text(encoding="utf-8")
    assert "--band-min: 73px" in css and "max(var(--w), var(--band-min))" in css
    design = (ROOT / "docs" / "design" / "diagram.md").read_text(encoding="utf-8")
    assert "最小の幅" in design and "帯の中心を範囲の中心" in design
    assert 'style="--l:' in (PARTS / "range.html").read_text(encoding="utf-8")
