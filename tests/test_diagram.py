"""説明図の段（erkit diagram）: HTML → PNG と marks.json、data-mark の位置、外の URL を止める、来歴の確認。"""
from __future__ import annotations

import json

import pytest

from conftest import EXAMPLE, ROOT, write_storyboard
from explainer_reel_kit import diagram as dg
from explainer_reel_kit import marks as mk
from explainer_reel_kit.capture.web.capture import png_size
from explainer_reel_kit.cli import main

CSS = (ROOT / "samples" / "_shared" / "diagram.css").read_text(encoding="utf-8")


def _html(body, head=""):
    return (f"<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='diagram.css'>{head}"
            f"</head><body>{body}</body></html>")


ABS = "position:absolute;left:{}px;top:{}px;width:{}px;height:{}px;background:#cde"
GOOD = _html(
    f"<div data-mark='left_card' style='{ABS.format(121, 100, 484, 300)}'></div>"
    f"<div data-mark='right_card' style='{ABS.format(1210, 500, 968, 400)}'><span>中身</span></div>"
    f"<div style='{ABS.format(700, 700, 100, 100)}'>名前なし</div>")


def _setup(tmp_path, html_by_scene, *, label="説明用再構成図", recipe_params=None, confidentiality="general"):
    (tmp_path / "diagrams").mkdir(exist_ok=True)
    (tmp_path / "diagrams" / "diagram.css").write_text(CSS, encoding="utf-8")
    scenes = []
    for sid, html in html_by_scene.items():
        (tmp_path / "diagrams" / f"{sid}.html").write_text(html, encoding="utf-8")
        scenes.append({
            "id": sid,
            "image": {"source": "generated", "ref": f"assets/{sid}.png", "label": label},
            "capture": {"tool": "html", "src": f"diagrams/{sid}.html", "prompt": "テストの図"},
            "recipe_params": (recipe_params or {}).get(sid, {}),
        })
    scenes.append({"id": "s99", "image": {"source": "generated", "ref": "assets/s99.png", "label": label},
                   "capture": {"prompt": "HTML で描かない図（対象外）"}, "recipe": "fade_sequence"})
    return write_storyboard(tmp_path / "t.storyboard.json", scenes, confidentiality=confidentiality)


def _quiet(*_):
    pass


def test_png_and_marks_positions(tmp_path, browser_opts):
    sb = _setup(tmp_path, {"s01": GOOD}, recipe_params={"s01": {"mark": ["left_card", "right_card"]}})
    res = dg.run_diagram(sb, log=_quiet, **browser_opts)
    assert (res["ok"], res["failed"]) == (1, 0) and [r["id"] for r in res["scenes"]] == ["s01"]
    png = tmp_path / "assets" / "s01.png"
    assert png_size(png) == (2420, 1000)
    doc = mk.load(mk.marks_path(png))   # 形式の検査も通る
    assert doc["source"] == "generated" and doc["image"] == "s01.png" and doc["image_size"] == {"w": 2420, "h": 1000}
    assert set(doc["marks"]) == {"left_card", "right_card"}
    left, right = doc["marks"]["left_card"], doc["marks"]["right_card"]
    assert left["px"] == {"x": 121, "y": 100, "w": 484, "h": 300}
    assert left["box"] == {"x": 0.05, "y": 0.1, "w": 0.2, "h": 0.3}
    assert right["box"] == {"x": 0.5, "y": 0.5, "w": 0.4, "h": 0.4}
    assert left["how"] == "data-mark: <div>"
    # 台本の mark: 名前 で、highlight_box の枠が決まる
    scene = json.loads(sb.read_text(encoding="utf-8"))["scenes"][0]
    found, missing = mk.resolve_refs(scene, doc)
    assert missing == [] and found["right_card"] == {"x": 0.5, "y": 0.5, "w": 0.4, "h": 0.4}
    saved = json.loads((tmp_path / dg.RESULT_NAME).read_text(encoding="utf-8"))
    assert saved["network"] == "blocked" and saved["scenes"][0]["label"] == "説明用再構成図"


def test_arrow_move_target_and_out_dir(tmp_path, browser_opts):
    sb = _setup(tmp_path, {"s01": GOOD}, recipe_params={"s01": {"to": {"mark": "right_card"}, "from_side": "left"}})
    out = tmp_path / "elsewhere"
    res = dg.run_diagram(sb, out, log=_quiet, **browser_opts)
    assert res["ok"] == 1 and not (tmp_path / "assets").exists()
    doc = mk.load(out / "assets" / "s01.marks.json")
    scene = json.loads(sb.read_text(encoding="utf-8"))["scenes"][0]
    assert mk.resolve_refs(scene, doc)[1] == []


@pytest.mark.parametrize("head,body", [
    ("", "<img src='https://example.com/a.png'>"),
    ("<link rel='stylesheet' href='https://fonts.example.com/x.css'>", ""),
    ("<style>@import url('http://example.com/y.css');</style>", ""),
    ("", "<script>fetch('https://example.com/data.json').catch(()=>{})</script>"),
])
def test_external_urls_are_blocked(tmp_path, browser_opts, head, body):
    html = _html(f"<div data-mark='a' style='{ABS.format(10, 10, 100, 100)}'></div>{body}", head)
    sb = _setup(tmp_path, {"s01": html})
    png = tmp_path / "assets" / "s01.png"
    png.parent.mkdir()
    png.write_bytes(b"old")                         # 前回の画像は残さない
    res = dg.run_diagram(sb, log=_quiet, **browser_opts)
    rec = res["scenes"][0]
    assert rec["status"] == "failed" and "外の URL を読もうとした" in rec["error"]
    assert rec["blocked"] and all(u.startswith("http") for u in rec["blocked"])
    assert not png.exists() and not mk.marks_path(png).exists()
    assert main(["diagram", str(sb), *(["--channel", browser_opts["channel"]] if browser_opts["channel"] else [])]) == 1


def test_mark_problems_fail_the_scene(tmp_path, browser_opts):
    html = _html(
        f"<div data-mark='dup' style='{ABS.format(10, 10, 100, 100)}'></div>"
        f"<div data-mark='dup' style='{ABS.format(300, 10, 100, 100)}'></div>"
        f"<div data-mark='Bad-Name' style='{ABS.format(10, 300, 100, 100)}'></div>"
        f"<div data-mark='hidden' style='{ABS.format(10, 500, 100, 100)};display:none'></div>"
        f"<div data-mark='tiny' style='{ABS.format(10, 700, 4, 4)}'></div>"
        f"<div data-mark='off' style='{ABS.format(2300, 900, 400, 300)}'></div>"
        f"<div data-mark='ok' style='{ABS.format(600, 300, 200, 200)}'></div>")
    sb = _setup(tmp_path, {"s01": html}, recipe_params={"s01": {"mark": ["ok", "missing"]}})
    res = dg.run_diagram(sb, log=_quiet, **browser_opts)
    rec = res["scenes"][0]
    assert rec["status"] == "failed"
    for msg in ("「dup」が 2 つ以上", "「Bad-Name」", "mark hidden: 非表示", "mark tiny: 小さすぎます",
                "mark off: 画像からはみ出しています", "mark「missing」が HTML にありません"):
        assert msg in rec["error"], msg
    doc = mk.load(tmp_path / "assets" / "s01.marks.json")
    assert set(doc["marks"]) == {"ok"}          # 正しいものだけ記録する


def test_preflight_label_html_and_only(tmp_path, browser_opts):
    sb = _setup(tmp_path, {"s01": GOOD}, label="実キャプチャ")
    with pytest.raises(dg.DiagramError, match="説明用再構成図"):
        dg.run_diagram(sb, log=_quiet, **browser_opts)
    sb = _setup(tmp_path, {"s01": GOOD})
    (tmp_path / "diagrams" / "s01.html").unlink()
    with pytest.raises(dg.DiagramError, match="HTML がありません"):
        dg.run_diagram(sb, log=_quiet, **browser_opts)
    with pytest.raises(dg.DiagramError, match="--only の s99"):
        dg.run_diagram(sb, only=["s99"], log=_quiet, **browser_opts)


def test_only_and_overflow_note(tmp_path, browser_opts):
    big = _html(f"<div data-mark='a' style='{ABS.format(10, 10, 100, 100)}'></div>"
                "<div style='position:absolute;left:0;top:1200px;width:10px;height:10px'></div>")
    big = big.replace("<link rel='stylesheet' href='diagram.css'>", "<style>body{margin:0}</style>")
    sb = _setup(tmp_path, {"s01": GOOD, "s02": big})
    res = dg.run_diagram(sb, only=["s02"], log=_quiet, **browser_opts)
    assert [r["id"] for r in res["scenes"]] == ["s02"] and res["ok"] == 1
    assert "はみ出した部分は写りません" in res["scenes"][0]["notes"][0]
    assert not (tmp_path / "assets" / "s01.png").exists()


def test_confidential_storyboard_can_draw(tmp_path, browser_opts):
    sb = _setup(tmp_path, {"s01": GOOD}, confidentiality=None)   # 未記入 = confidential
    res = dg.run_diagram(sb, log=_quiet, **browser_opts)
    assert res["confidentiality"] == "confidential" and res["ok"] == 1


def test_example_storyboard_with_cli_and_overlay(tmp_path, browser_opts, capsys):
    ch = ["--channel", browser_opts["channel"]] if browser_opts["channel"] else []
    out = tmp_path / "out"
    assert main(["diagram", str(EXAMPLE), "--out", str(out), "--overlay", str(out / "check.png"), *ch]) == 0
    text = capsys.readouterr().out
    assert "説明図 4 件 / 失敗 0 件" in text and (out / "check.png").is_file()  # s01・s02・s04・s05
    doc = mk.load(out / "assets" / "s01_storyboard.marks.json")
    assert "scene_block" in doc["marks"]


def test_cli_diagram_errors(tmp_path, capsys):
    assert main(["diagram", str(tmp_path / "none.storyboard.md")]) == 2
    assert "台本を読めません" in capsys.readouterr().err
