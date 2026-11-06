"""Web 撮影（erkit capture）: 操作定義の検証と台本との突き合わせ、順序、URL、ローカルページの撮影と marks。"""
from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest
import yaml

from conftest import EXAMPLE, ROOT, write_storyboard
from explainer_reel_kit import marks as mk
from explainer_reel_kit.capture.web import capture as wc
from explainer_reel_kit.capture.web import overlay, serve
from explainer_reel_kit.cli import main

EXAMPLE_ACTIONS = ROOT / "examples" / "hello-kit.actions.yaml"
EXAMPLE_PAGE = ROOT / "examples" / "hello-page"


def _quiet(*_):
    pass


def _actions(reel_id="t", **scenes):
    return {"schema": wc.ACTIONS_SCHEMA, "reel_id": reel_id, "defaults": {"settle_ms": 0, "timeout_ms": 3000, "device_scale_factor": 1},
            "scenes": scenes}


def _web(sid, url, vp=None, **extra):
    sc = {"id": sid, "image": {"source": "web", "ref": f"captures/t/{sid}.png", "label": "実キャプチャ"},
          "capture": {"url": url, "steps": ["テスト"]}}
    if vp:
        sc["capture"]["viewport"] = vp
    sc.update(extra)
    return sc


# ---------------------------------------------------------------- 検証（ブラウザ不要）

def test_example_actions_match_example_storyboard():
    doc = wc.load_storyboard(EXAMPLE)
    rep = wc.crosscheck(doc, wc.load_actions(EXAMPLE_ACTIONS))
    assert rep.ok, rep.errors
    assert wc.default_actions_path(EXAMPLE, "hello-kit") == EXAMPLE_ACTIONS.resolve()


@pytest.mark.parametrize("op,msg", [
    ({"op": "jump"}, "未対応の op"),
    ({"op": "click"}, "selector が必要"),
    ({"op": "click", "selector": "a", "x": 1}, "使えない項目"),
    ({"op": "fill", "selector": "a", "value": True}, "fill.value"),
    ({"op": "fill", "selector": "a", "value": 1, "commit": "tab"}, "fill.commit"),
    ({"op": "scroll", "y": -1}, "scroll.y"),
    ({"op": "wait", "ms": "1"}, "wait.ms"),
    ({"op": "goto", "url": "ftp://x"}, "file://"),
    ({"op": "wait_load", "state": "idle"}, "wait_load.state"),
])
def test_invalid_ops_are_reported(op, msg):
    errs = wc.validate_actions(_actions(s01={"actions": [op]}))
    assert any(msg in e for e in errs), errs


def test_goto_file_url_is_allowed():
    assert wc.validate_actions(_actions(s01={"actions": [{"op": "goto", "url": "file:///x.html"}]})) == []


def test_invalid_top_level_shot_and_marks():
    errs = " ".join(wc.validate_actions({"schema": "x", "scenes": {"s01": {"shot": {"type": "element"},
                                                                          "marks": {"Bad": "#a", "ok": []}}}}))
    for msg in ("schema:", "reel_id", "selector が必要", "英小文字", "セレクタの並び"):
        assert msg in errs
    assert wc.validate_actions([]) and wc.validate_actions(_actions())


def test_crosscheck(tmp_path):
    doc = json.loads(write_storyboard(tmp_path / "a.json", [
        _web("s01", "http://localhost:8000/", recipe_params={"mark": ["a", "b"]}),
        {"id": "s02", "image": {"source": "generated", "ref": "x.png", "label": "説明用再構成図"},
         "capture": {"prompt": "図"}},
    ]).read_text(encoding="utf-8"))
    rep = wc.crosscheck(doc, _actions("other", s01={"actions": [], "marks": {"a": "#a"}}, s02={}, s09={}))
    errs = " ".join(rep.errors)
    for msg in ("reel_id が台本と違います", "s02: 台本では web シーンではない", "s09: 台本にないシーン", "mark「b」が操作定義にありません"):
        assert msg in errs
    assert any("reset: true" in w for w in rep.warnings)
    rep = wc.crosscheck(doc, _actions(s09={}))
    assert any("s01: 台本の web シーンに対応する操作定義がありません" in e for e in rep.errors)


def test_plan_only_replays_from_last_reset(tmp_path):
    doc = json.loads(write_storyboard(tmp_path / "a.json", [_web(f"s0{i}", "http://localhost/") for i in range(1, 5)])
                     .read_text(encoding="utf-8"))
    acts = _actions(s01={"reset": True}, s02={}, s03={"reset": True}, s04={})
    steps = wc.plan(doc, acts, ["s02", "s04"])
    assert [(s.scene["id"], s.shoot) for s in steps] == [("s01", False), ("s02", True), ("s03", False), ("s04", True)]
    with pytest.raises(wc.CaptureError, match="web シーンでない"):
        wc.plan(doc, acts, ["s09"])


def test_url_map_and_local_rebase():
    m = wc.parse_url_map(["https://a.example/=http://localhost:5173/"])
    assert wc.map_url("https://a.example/x?q=1", m) == "http://localhost:5173/x?q=1"
    assert wc.map_url("http://localhost:8000/app/i.html?q=1#f", [], "http://127.0.0.1:4567/") \
        == "http://127.0.0.1:4567/app/i.html?q=1#f"
    assert wc.map_url("http://127.0.0.1/", [], "http://127.0.0.1:4567/") == "http://127.0.0.1:4567/"
    assert wc.map_url("https://a.example/", [], "http://127.0.0.1:4567/") == "https://a.example/"
    with pytest.raises(wc.CaptureError):
        wc.parse_url_map(["no-equal"])


@pytest.mark.parametrize("url,local", [
    ("file:///c/x.html", True), ("http://localhost:3000/", True), ("http://127.0.0.1/", True),
    ("http://[::1]:8000/", True), ("https://a.example/", False), ("http://192.168.0.2/", False),
    ("http://localhost.example.com/", False),
])
def test_is_local_url(url, local):
    assert serve.is_local_url(url) is local


def test_confidential_refuses_outside_urls(tmp_path):
    sb = write_storyboard(tmp_path / "c.json", [_web("s01", "https://a.example/")], confidentiality=None)
    acts = tmp_path / "t.actions.yaml"
    acts.write_text(yaml.safe_dump(_actions(s01={"reset": True, "actions": []})), encoding="utf-8")
    with pytest.raises(wc.CaptureError, match="社外秘"):
        wc.run_capture(sb, tmp_path / "out", acts, log=_quiet)
    assert not (tmp_path / "out").exists()   # ブラウザも開かず、何も書かない
    # 一般の台本は外の URL も撮れる（ここでは確かめだけ）
    doc = json.loads(sb.read_text(encoding="utf-8"))
    doc["reel"]["confidentiality"] = "general"
    assert wc.check_confidential_urls(doc, {"s01": "https://a.example/"}) == []


def test_default_dirs(tmp_path, monkeypatch):
    doc = {"reel": {"id": "hello-kit"}}
    monkeypatch.delenv(wc.ENV_CAPTURES_ROOT, raising=False)
    assert wc.default_out_dir(doc) == Path.home() / "ExplainerReelKit" / "captures" / "web" / "hello-kit"
    monkeypatch.setenv(wc.ENV_CAPTURES_ROOT, str(tmp_path))
    assert wc.default_out_dir(doc) == tmp_path / "web" / "hello-kit"
    assert wc.default_out_dir(doc, "My Tool", tmp_path / "r") == tmp_path / "r" / "web" / "My-Tool"
    with pytest.raises(wc.CaptureError):
        wc.folder_name('..')


def test_cli_check(capsys, tmp_path):
    assert main(["capture", str(EXAMPLE), "--check"]) == 0
    assert "web シーン 1 件すべてに操作定義があります" in capsys.readouterr().out
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(_actions("hello-kit", s09={})), encoding="utf-8")
    assert main(["capture", str(EXAMPLE), "--check", "--actions", str(bad)]) == 1
    assert main(["capture", str(EXAMPLE), "--check", "--actions", str(tmp_path / "none.yaml")]) == 2
    assert "操作定義がありません" in capsys.readouterr().err


# ---------------------------------------------------------------- ローカルのページを撮る

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;font-family:sans-serif} .tall{height:2000px;background:#eef}
#out{font-size:40px;display:inline-block} #far{background:#fc0;padding:20px}</style></head><body>
<h2 id="title">テスト画面</h2>
<input id="q" type="number" value="1"
  onkeydown="if(event.key==='Enter'){document.getElementById('out').textContent='Q='+this.value}">
<button onclick="document.getElementById('out').textContent='clicked'">押す</button>
<div id="out">初期</div><div class="tall"></div><div id="far">下の要素</div>
</body></html>"""

MARKS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0} div{position:absolute}
#a{left:100px;top:50px;width:200px;height:80px;background:#f00}
#b{left:300px;top:300px;width:100px;height:60px;background:#0f0}
#tiny{left:10px;top:10px;width:4px;height:4px;background:#00f}
#hidden{left:10px;top:400px;width:50px;height:50px;display:none}
#off{left:700px;top:500px;width:300px;height:300px;background:#ff0}
#far{left:50px;top:1500px;width:120px;height:90px;background:#0ff}
</style></head><body>
<div id="a"></div><div id="b"></div><div id="tiny"></div><div id="hidden"></div><div id="off"></div><div id="far"></div>
<div style="position:static;height:2000px"></div></body></html>"""


@pytest.fixture(scope="module")
def site_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    (root / "marks.html").write_text(MARKS_PAGE, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def site(site_dir):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def _four(tmp_path, url):
    return write_storyboard(tmp_path / "t.storyboard.json", [
        _web("s01", url, {"width": 800, "height": 600}), _web("s02", url), _web("s03", url), _web("s04", url)])


def _write_actions(tmp_path, scenes):
    p = tmp_path / "t.actions.yaml"
    p.write_text(yaml.safe_dump(_actions(**scenes), allow_unicode=True), encoding="utf-8")
    return p


def test_capture_static_html(tmp_path, site, browser_opts):
    sb = _four(tmp_path, site)
    _write_actions(tmp_path, {
        "s01": {"reset": True, "actions": [{"op": "wait_load"}, {"op": "wait_for", "selector": "#title"}]},
        "s02": {"actions": [{"op": "fill", "selector": "#q", "value": 42}, {"op": "wait_for", "selector": "text=Q=42"}],
                "shot": {"type": "element", "selector": "#out"}},
        "s03": {"actions": [{"op": "click", "selector": "#nothing"}]},  # 失敗させる
        "s04": {"actions": [{"op": "scroll_to", "selector": "#far", "block": "center"}],
                "shot": {"type": "element", "selector": "#far", "padding": 10}},
    })
    out = tmp_path / "out"
    res = wc.run_capture(sb, out, log=_quiet, **browser_opts)   # 操作定義は台本の隣（既定）
    by = {r["id"]: r for r in res["scenes"]}
    assert (res["ok"], res["failed"]) == (3, 1)
    assert (by["s01"]["width"], by["s01"]["height"]) == (800, 600) and (out / "captures/t/s01.png").is_file()
    assert by["s02"]["status"] == "ok" and "notes" not in by["s02"] and by["s02"]["width"] < 800
    assert by["s03"]["status"] == "failed" and "TimeoutError" in by["s03"]["error"]
    assert not (out / "captures/t/s03.png").exists()
    assert by["s04"]["status"] == "ok" and "前のシーンが失敗" in by["s04"]["notes"][0]
    saved = json.loads((out / wc.RESULT_NAME).read_text(encoding="utf-8"))
    assert saved["reel_id"] == "t" and saved["assets_root"] == str(out.resolve()) and saved["tool"] == "erkit capture"


def test_capture_only_prepares_previous_scenes(tmp_path, site, browser_opts):
    sb = _four(tmp_path, site)
    _write_actions(tmp_path, {
        "s01": {"reset": True, "actions": [{"op": "click", "selector": "button"}]},
        "s02": {"actions": [], "shot": {"type": "element", "selector": "#out"}},
        "s03": {"actions": []}, "s04": {"actions": []},
    })
    out = tmp_path / "out"
    res = wc.run_capture(sb, out, only=["s02"], log=_quiet, **browser_opts)
    assert [(r["id"], r["status"]) for r in res["scenes"]] == [("s01", "prepared"), ("s02", "ok")]
    assert not (out / "captures/t/s01.png").exists() and (out / "captures/t/s02.png").is_file()


def test_capture_writes_marks_json(tmp_path, site, browser_opts):
    sb = _four(tmp_path, site + "marks.html")
    _write_actions(tmp_path, {
        "s01": {"reset": True, "actions": [{"op": "wait_load"}], "marks": {"single": "#a", "union": ["#a", "#b"]}},
        "s02": {"actions": [], "marks": {"tiny": "#tiny", "gone": "#nothing", "hidden": "#hidden",
                                         "off": "#off", "ok": "#b"}},
        "s03": {"actions": [{"op": "scroll", "y": 1400}], "marks": {"far": "#far"}},
        "s04": {"actions": [{"op": "scroll", "y": 0}],
                "shot": {"type": "element", "selector": "#b", "padding": 20}, "marks": {"b": "#b"}},
    })
    out = tmp_path / "out"
    stale = out / "captures/t/s02.marks.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    res = wc.run_capture(sb, out, log=_quiet, **browser_opts)
    by = {r["id"]: r for r in res["scenes"]}

    m1 = mk.load(out / "captures/t/s01.marks.json")
    assert m1["source"] == "web" and m1["image"] == "s01.png" and m1["image_size"] == {"w": 800, "h": 600}
    assert m1["marks"]["single"]["px"] == {"x": 100, "y": 50, "w": 200, "h": 80}
    assert m1["marks"]["single"]["box"] == {"x": 0.125, "y": 0.0833, "w": 0.25, "h": 0.1333}
    assert m1["marks"]["union"]["px"] == {"x": 100, "y": 50, "w": 300, "h": 310}
    assert m1["marks"]["union"]["how"] == "selector: #a + #b"
    assert by["s01"]["marks"] == ["single", "union"]

    assert by["s02"]["status"] == "failed"
    for msg in ("mark tiny: 小さすぎます", "mark gone: 見つかりません", "mark hidden: 非表示",
                "mark off: 画像からはみ出しています"):
        assert msg in by["s02"]["error"]
    assert set(mk.load(stale)["marks"]) == {"ok"}   # 前回のファイルは上書きされる

    assert mk.load(out / "captures/t/s03.marks.json")["marks"]["far"]["px"] == {"x": 50, "y": 100, "w": 120, "h": 90}
    m4 = mk.load(out / "captures/t/s04.marks.json")
    assert m4["image_size"] == {"w": 140, "h": 100} and m4["marks"]["b"]["px"] == {"x": 20, "y": 20, "w": 100, "h": 60}

    used = overlay.build_overlay(out / wc.RESULT_NAME, tmp_path / "overlay.png", cols=2, width=400)
    assert used == ["s01", "s03", "s04"] and (tmp_path / "overlay.png").is_file()


def test_capture_file_url_via_url_map(tmp_path, site_dir, browser_opts):
    sb = write_storyboard(tmp_path / "t.storyboard.json", [
        _web("s01", "http://localhost:8000/marks.html", {"width": 800, "height": 600},
             recipe_params={"mark": "single"})], confidentiality=None)       # 社外秘でも file:// は撮れる
    _write_actions(tmp_path, {"s01": {"reset": True, "actions": [], "marks": {"single": "#a"}}})
    out = tmp_path / "out"
    res = wc.run_capture(sb, out, url_map=[("http://localhost:8000/", site_dir.as_uri() + "/")], log=_quiet,
                         **browser_opts)
    assert res["ok"] == 1 and res["scenes"][0]["url"].startswith("file://")
    doc = mk.load(out / "captures/t/s01.marks.json")
    scene = json.loads(sb.read_text(encoding="utf-8"))["scenes"][0]
    assert mk.resolve_refs(scene, doc) == ({"single": {"x": 0.125, "y": 0.0833, "w": 0.25, "h": 0.1333}}, [])


def test_example_with_serve_cli(tmp_path, browser_opts, capsys):
    ch = ["--channel", browser_opts["channel"]] if browser_opts["channel"] else []
    out = tmp_path / "out"
    rc = main(["capture", str(EXAMPLE), "--serve", str(EXAMPLE_PAGE), "--out", str(out),
               "--overlay", str(out / "check.png"), *ch])
    assert rc == 0, capsys.readouterr()
    res = json.loads((out / wc.RESULT_NAME).read_text(encoding="utf-8"))
    assert res["served"] == str(EXAMPLE_PAGE.resolve()) and res["scenes"][0]["url"].startswith("http://127.0.0.1:")
    doc = mk.load(out / "captures/hello-kit/s03_page.marks.json")
    assert set(doc["marks"]) == {"input_area", "result_area"}
    # 台本の arrow_move（to: {mark: result_area}）の行き先が決まる
    scene = next(s for s in wc.load_storyboard(EXAMPLE)["scenes"] if s["id"] == "s03")
    found, missing = mk.resolve_refs(scene, doc)
    assert missing == [] and 0 < found["result_area"]["w"] < 1 and (out / "check.png").is_file()


def test_serve_dir_missing(tmp_path):
    with pytest.raises(wc.CaptureError, match="--serve"):
        wc.run_capture(EXAMPLE, tmp_path / "o", serve=tmp_path / "none", log=_quiet)


# ---------------------------------------------------------------- 画面の大きさ（画像枠の縦横比）

def test_default_viewport_matches_image_frame():
    vp = wc.DEFAULT_VIEWPORT
    assert abs(vp["width"] / vp["height"] - 12.333 / 5.1) < 0.01   # スライドの画像枠 ≒ 2.42:1
    assert (vp["width"] * wc.DEFAULT_SCALE, vp["height"] * wc.DEFAULT_SCALE) == (2400, 990)


def test_capture_uses_default_viewport_and_scale(tmp_path, site, browser_opts):
    sb = write_storyboard(tmp_path / "t.storyboard.json", [_web("s01", site + "marks.html")])  # viewport を書かない
    acts = _actions(s01={"reset": True, "actions": [], "marks": {"a": "#a"}})
    del acts["defaults"]["device_scale_factor"]   # 既定の 1.5 倍で撮る
    (tmp_path / "t.actions.yaml").write_text(yaml.safe_dump(acts), encoding="utf-8")
    res = wc.run_capture(sb, tmp_path / "out", log=_quiet, **browser_opts)
    rec = res["scenes"][0]
    assert (rec["width"], rec["height"]) == (2400, 990)
    m = mk.load(tmp_path / "out" / "captures/t/s01.marks.json")
    assert m["marks"]["a"]["px"] == {"x": 150, "y": 75, "w": 300, "h": 120}       # CSS px × 1.5
    assert m["marks"]["a"]["box"] == {"x": 0.0625, "y": 0.0758, "w": 0.125, "h": 0.1212}


@pytest.mark.parametrize("page", [ROOT / "samples" / "u-value" / "app" / "index.html", EXAMPLE_PAGE / "index.html"])
def test_sample_pages_fit_one_screen(page, browser_opts):
    """サンプルと例の撮るページは、既定の画面（1600×660）に 1 画面で収まる（はみ出した所は写らないため）。"""
    from explainer_reel_kit import browser as br

    with br.sync_playwright() as pw:
        b = br.launch(pw, browser_opts["channel"])
        try:
            p = b.new_page(viewport=wc.DEFAULT_VIEWPORT)
            p.goto(page.as_uri())
            w, h = p.evaluate("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
        finally:
            b.close()
    assert w <= wc.DEFAULT_VIEWPORT["width"] and h <= wc.DEFAULT_VIEWPORT["height"], (w, h)
