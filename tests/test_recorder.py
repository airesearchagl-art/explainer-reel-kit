"""記録モード（erkit record）: イベント列 → 操作定義、セレクタの優先順と警告、mark、ローカルページで 記録 → 撮影 → marks.json。"""
from __future__ import annotations

import copy
import functools
import http.server
import json
import threading

import pytest
import yaml

from conftest import write_storyboard
from explainer_reel_kit import marks as mk
from explainer_reel_kit.capture.web import capture as wc
from explainer_reel_kit.capture.web import recorder as rc
from explainer_reel_kit.cli import main


def ev(kind, cands, **kw):
    return {"type": kind, "tag": kw.pop("tag", "button"), "text": kw.pop("text", ""), "candidates": cands, **kw}


def c(kind, selector, count=1):
    return {"kind": kind, "selector": selector, "count": count}


# ---------------------------------------------------------------- セレクタの優先順と警告

def test_priority_testid_role_text_ancestor_css():
    full = [c("css", "div > button"), c("text", 'text="保存"'), c("role", 'role=button[name="保存"]'),
            c("testid", '[data-testid="save"]'), c("text_ancestor", 'text="x" >> xpath=ancestor::*[1]')]
    assert rc.pick_selector({"candidates": full}).kind == "testid"
    assert rc.pick_selector({"candidates": full[:3]}).selector == 'role=button[name="保存"]'
    assert rc.pick_selector({"candidates": [full[0], full[1]]}).kind == "text"
    assert rc.pick_selector({"candidates": [full[0], full[4]]}).kind == "text_ancestor"
    p = rc.pick_selector({"candidates": [full[0]]})
    assert p.kind == "css" and any("CSS セレクタ" in w for w in p.warnings)


def test_skips_non_unique_candidates():
    p = rc.pick_selector({"candidates": [c("testid", '[data-testid="row"]', 3), c("role", 'role=button[name="A"]', 2),
                                         c("text", 'text="A 行"', 1)]})
    assert p.kind == "text" and p.warnings == []
    p = rc.pick_selector({"candidates": [c("role", 'role=button[name="A"]', 2), c("css", "div > a", 4)]})
    assert p.kind == "role" and "2 件に一致" in p.warnings[0]


@pytest.mark.parametrize("sel, msg", [
    ("div.card > button:nth-of-type(2)", "nth"),
    ("div.css-1x2y3z > span", "css-1x2y3z"),
    ("div.sc-bdVaJa > a", "sc-bdVaJa"),
    ("div._3kD9xQ > a", "_3kD9xQ"),
    ("div.Button__root--a1b2c > a", "Button__root--a1b2c"),
])
def test_unstable_css_warnings(sel, msg):
    p = rc.pick_selector({"candidates": [c("css", sel)]})
    assert any(msg in w for w in p.warnings), p.warnings


def test_stable_css_has_only_last_resort_warning():
    p = rc.pick_selector({"candidates": [c("css", "main > section.results > table")]})
    assert len(p.warnings) == 1


def test_no_candidates():
    with pytest.raises(wc.CaptureError, match="候補"):
        rc.pick_selector({"candidates": []})


# ---------------------------------------------------------------- イベント列 → 操作定義

BTN = [c("role", 'role=button[name="方式 A"]')]
INPUT = [c("role", 'role=spinbutton[name="入力値"]')]
CARD = [c("text_ancestor", 'text="計測パネル" >> xpath=ancestor::*[1]')]


def test_events_to_actions_basic():
    events = [
        ev("click", BTN),
        ev("fill", INPUT, value="100", commit="blur"),
        ev("fill", INPUT, value="120", commit="enter"),         # 同じ欄への続けての入力は最後だけ
        ev("mark", CARD, name="meter_panel", tag="div"),
        ev("shot", [], scrollY=0),
        ev("select", [c("role", 'role=combobox[name="方式"]')], value="mode_b"),
        ev("mark", BTN, name="Bad-Name"),                       # 使えない名前は捨てる
        ev("shot", [], scrollY=640),
        ev("click", BTN),                                       # F8 で区切っていない → 捨てる
        ev("finish", []),
        ev("click", BTN),                                       # finish の後は無視
    ]
    data, warns = rc.events_to_actions(events, "demo-intro", viewport={"width": 1280, "height": 720})
    assert data["schema"] == wc.ACTIONS_SCHEMA and data["reel_id"] == "demo-intro"
    assert data["defaults"]["viewport"] == {"width": 1280, "height": 720}
    s1, s2 = data["scenes"]["s01"], data["scenes"]["s02"]
    assert s1["reset"] is True and "reset" not in s2
    assert s1["actions"] == [{"op": "wait_load"}, {"op": "click", "selector": 'role=button[name="方式 A"]'},
                             {"op": "fill", "selector": 'role=spinbutton[name="入力値"]', "value": "120", "commit": "enter"},
                             {"op": "scroll", "y": 0}]
    assert s1["marks"] == {"meter_panel": 'text="計測パネル" >> xpath=ancestor::*[1]'} and s1["shot"] == {"type": "viewport"}
    assert s2["actions"] == [{"op": "select", "selector": 'role=combobox[name="方式"]', "value": "mode_b"},
                             {"op": "scroll", "y": 640}]
    assert "marks" not in s2
    assert any("Bad-Name" in w for w in warns) and any("捨てました" in w and "1 件" in w for w in warns)
    assert wc.validate_actions(data) == []


def test_start_number_and_notes():
    events = [ev("click", [c("css", "div > button:nth-of-type(3)")]), ev("shot", [], scrollY=10)]
    data, _ = rc.events_to_actions(events, "x", start=5)
    assert list(data["scenes"]) == ["s05"]
    assert "nth" in data["scenes"]["s05"]["note"] and "CSS セレクタ" in data["scenes"]["s05"]["note"]


def test_no_scene_or_no_reel():
    with pytest.raises(wc.CaptureError, match="F8"):
        rc.events_to_actions([ev("click", BTN)], "x")
    with pytest.raises(wc.CaptureError, match="--reel"):
        rc.events_to_actions([ev("shot", [])], "")


def test_dump_is_valid_yaml_with_header():
    data, warns = rc.events_to_actions([ev("click", BTN), ev("shot", [], scrollY=0)], "x")
    text = rc.dump_actions(data, "http://127.0.0.1:8000/", ["テスト警告"])
    assert text.startswith("# erkit record で作成") and "# 警告: テスト警告" in text
    assert yaml.safe_load(text) == data


def test_select_op_is_validated():
    base = {"schema": wc.ACTIONS_SCHEMA, "reel_id": "x", "scenes": {"s01": {"actions": []}}}
    for op, ok in (({"op": "select", "selector": "#s", "value": "a"}, True),
                   ({"op": "select", "selector": "#s"}, False),
                   ({"op": "select", "selector": "#s", "value": True}, False)):
        d = copy.deepcopy(base)
        d["scenes"]["s01"]["actions"] = [op]
        assert (wc.validate_actions(d) == []) is ok


def test_parse_viewport():
    assert rc.parse_viewport("1280x720") == {"width": 1280, "height": 720}
    assert rc.parse_viewport("1920 × 1080") == {"width": 1920, "height": 1080}
    with pytest.raises(wc.CaptureError):
        rc.parse_viewport("big")


# ---------------------------------------------------------------- ローカルのページで 記録 → 撮影 → marks.json

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Recorder test</title><style>
body{margin:0;font-family:sans-serif} .pad{height:900px} .card{width:300px;padding:16px;border:1px solid #888;margin:8px}
.gen-x9f3k2{color:#333}
</style></head><body>
<h2>テストツール</h2>
<button data-testid="go">開始</button>
<button>方式を切替</button>
<button>方式を切替</button>
<div class="card"><span>計測パネル</span><div id="v">2.50</div></div>
<label for="q">入力値</label><input id="q" type="number" value="120"
  onchange="document.getElementById('out').textContent='Q=' + this.value">
<select id="m" aria-label="方式" onchange="document.getElementById('out').textContent='M=' + this.value">
  <option value="louver">方式 A</option><option value="mode_b">方式 B</option></select>
<div id="out">初期</div>
<div class="pad"></div>
<div class="card"><span class="gen-x9f3k2">下のカード</span></div>
<div class="pad"></div>
</body></html>"""


@pytest.fixture(scope="module")
def site_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("rec_site")
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def site(site_dir):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def _drive(page):
    """人の代わりの操作: クリック・入力・選択・F8・Shift＋クリックで mark。"""
    names = iter(["meter^", "go_button", "lower_card^"])
    page.on("dialog", lambda d: d.accept(next(names)))
    page.click('[data-testid="go"]')
    page.fill("#q", "200")
    page.press("#q", "Enter")
    page.click("text=計測パネル", modifiers=["Shift"])      # ^ で 1 つ上（カード全体）
    page.keyboard.press("F8")                               # s01
    page.select_option("#m", "mode_b")
    page.click('[data-testid="go"]', modifiers=["Shift"])   # 撮影位置（下へスクロール）では画面外になる mark
    page.evaluate("window.scrollTo(0, 800)")
    page.click("text=下のカード", modifiers=["Shift"])
    page.keyboard.press("F8")                               # s02（スクロール 800 で撮影）
    page.click("text=方式を切替 >> nth=0")                    # 2 つに当たる → 警告
    page.keyboard.press("F10")


def test_record_capture_marks_end_to_end(tmp_path, site, browser_opts):
    out = tmp_path / "rec.yaml"
    logs = []
    res = rc.record(site, "minimal", out, headed=False, drive=_drive, log=logs.append, **browser_opts)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data == res["data"] and wc.validate_actions(data) == []
    s1, s2 = data["scenes"]["s01"], data["scenes"]["s02"]
    assert s1["actions"][0] == {"op": "wait_load"}
    assert s1["actions"][1] == {"op": "click", "selector": '[data-testid="go"]'}      # testid が最優先
    assert s1["actions"][2]["op"] == "fill" and s1["actions"][2]["value"] == "200" and s1["actions"][2]["commit"] == "enter"
    assert s1["actions"][2]["selector"] == 'role=spinbutton[name="入力値"]'          # label の名前
    assert s1["marks"]["meter"] == 'text="計測パネル" >> xpath=ancestor::*[1]'       # ^ で親（カード）
    assert s2["actions"][0] == {"op": "select", "selector": 'role=combobox[name="方式"]', "value": "mode_b"}
    assert s2["actions"][-1] == {"op": "scroll", "y": 800}
    assert set(s2["marks"]) == {"lower_card", "go_button"}
    assert any("捨てました" in w for w in res["warnings"])                              # F8 の後のクリック
    assert any("s02: mark go_button" in p and "画面の外" in p for p in res["problems"]), res["problems"]

    # 記録した操作定義で撮影 → marks.json（台本は同じ id の web シーンを持つテスト用のもの）
    sb = write_storyboard(tmp_path / "t.storyboard.json", [
        {"id": sid, "image": {"source": "web", "ref": f"captures/r/{sid}.png", "label": "実キャプチャ"},
         "capture": {"url": site, "steps": ["記録した操作"], "viewport": {"width": 1920, "height": 1080}}}
        for sid in ("s01", "s02")], reel_id="minimal")
    # 画面外の mark（go_button）は撮影で失敗になるので、撮影の確認では外す
    del data["scenes"]["s02"]["marks"]["go_button"]
    acts = tmp_path / "rec-ok.yaml"
    acts.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    shots = tmp_path / "shots"
    cap = wc.run_capture(sb, shots, acts, log=lambda *_: None, **browser_opts)
    assert (cap["ok"], cap["failed"]) == (2, 0), cap
    m1 = mk.load(shots / "captures/r/s01.marks.json")
    box = m1["marks"]["meter"]["px"]
    assert box["w"] > 300 and box["h"] > 30                                             # カード全体（span ではない）
    m2 = mk.load(shots / "captures/r/s02.marks.json")
    assert set(m2["marks"]) == {"lower_card"}


def test_record_refuses_existing_file(tmp_path):
    out = tmp_path / "exists.yaml"
    out.write_text("keep", encoding="utf-8")
    with pytest.raises(wc.CaptureError, match="追記しません"):
        rc.record("http://127.0.0.1:1/", "x", out, headed=False, drive=lambda p: None)
    assert out.read_text(encoding="utf-8") == "keep"


def test_record_without_scene_writes_nothing(tmp_path, site, browser_opts):
    out = tmp_path / "none.yaml"
    with pytest.raises(wc.CaptureError, match="F8"):
        rc.record(site, "x", out, headed=False, drive=lambda p: p.click('[data-testid="go"]'), **browser_opts)
    assert not out.exists()


def test_cli_record_existing_file_exit_2(tmp_path, capsys):
    out = tmp_path / "x.yaml"
    out.write_text("keep", encoding="utf-8")
    assert main(["record", "--url", "http://127.0.0.1:1/", "--reel", "x", "--out", str(out)]) == 2
    assert "追記しません" in capsys.readouterr().err and out.read_text(encoding="utf-8") == "keep"


def test_record_url_scheme_and_serve_dir(tmp_path):
    with pytest.raises(wc.CaptureError, match="file://"):
        rc.record("ftp://x/", "x", tmp_path / "a.yaml", headed=False, drive=lambda p: None)
    with pytest.raises(wc.CaptureError, match="--serve"):
        rc.record("http://localhost/", "x", tmp_path / "a.yaml", headed=False, drive=lambda p: None,
                  serve=tmp_path / "none")


def test_record_with_serve(tmp_path, site_dir, browser_opts):
    def drive(page):
        page.on("dialog", lambda d: d.accept("meter^"))
        page.click("text=計測パネル", modifiers=["Shift"])
        page.keyboard.press("F8")

    out = tmp_path / "served.yaml"
    res = rc.record("http://localhost:8000/index.html", "x", out, headed=False, drive=drive, serve=site_dir,
                    **browser_opts)
    assert res["problems"] == [] and "meter" in res["data"]["scenes"]["s01"]["marks"]
    assert "# 記録した URL: http://localhost:8000/index.html" in out.read_text(encoding="utf-8")
