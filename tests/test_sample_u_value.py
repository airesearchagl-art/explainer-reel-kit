"""サンプル題材 samples/u-value: 台本の検証、計算ページが外の URL を読まないこと、説明図 → 撮影 → deck で未解決の注釈 0。"""
from __future__ import annotations

import re

from conftest import ROOT
from explainer_reel_kit import marks as mk
from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.capture.web import capture as wc
from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.diagram import run_diagram

SAMPLE = ROOT / "samples" / "u-value"
STORYBOARD = SAMPLE / "u-value.storyboard.md"
APP = SAMPLE / "app" / "index.html"
EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import|fetch\(|XMLHttpRequest""", re.I)


def _quiet(*_):
    pass


def test_storyboard_is_valid_and_general():
    doc = sb.load_storyboard(STORYBOARD)
    rep = sb.validate_storyboard(doc, base_dir=SAMPLE)
    assert rep.ok and not rep.warnings, (rep.errors, rep.warnings)
    assert sb.confidentiality(doc) == "general" and doc["reel"]["kind"] == "tool_intro"
    ids = [s["id"] for s in doc["scenes"]]
    assert ids == ["s01", "s02", "s03", "s04", "s05"]
    assert wc.crosscheck(doc, wc.load_actions(wc.default_actions_path(STORYBOARD, "u-value"))).ok


def test_app_and_diagrams_reference_nothing_outside():
    for path in [APP, *sorted((SAMPLE / "diagrams").glob("*.html"))]:
        text = path.read_text(encoding="utf-8")
        assert not EXTERNAL.search(text), f"{path.name} が外の URL を読もうとしています"


def test_app_values_match_sources():
    """計算ページの U 値の範囲が、SOURCES.md の表と同じであること（片方だけ直すのを防ぐ）。"""
    app = APP.read_text(encoding="utf-8")
    src = (SAMPLE / "SOURCES.md").read_text(encoding="utf-8")
    pairs = re.findall(r'name: "([^"]+)", lo: ([\d.]+), hi: ([\d.]+)', app)
    assert len(pairs) == 4
    for name, lo, hi in pairs:
        assert re.search(rf"\| {re.escape(name)} \| {lo}〜{hi} \|", src), name


def test_sample_pipeline_has_no_unresolved_marks(tmp_path, browser_opts):
    assets = tmp_path / "u-value"
    assert run_diagram(STORYBOARD, assets, log=_quiet, **browser_opts)["failed"] == 0
    res = wc.run_capture(STORYBOARD, assets, serve=SAMPLE / "app", log=_quiet, **browser_opts)
    assert res["failed"] == 0, [r.get("error") for r in res["scenes"]]
    # 計算ページの結果（面積 2.0 m²・温度差 15℃・Low-E 複層）の注釈の部品が撮れている
    m5 = mk.load(assets / "captures" / "u-value" / "s05_compare.marks.json")
    assert {"bar_lowe", "compare_chart"} <= set(m5["marks"])
    deck = build_deck(STORYBOARD, tmp_path / "u_value.pptx", assets_root=assets)
    assert deck.unresolved == [], deck.unresolved_text()
    assert {a.status for a in deck.annotations} == {"mark"}
    assert len(deck.annotations) == 3 + 2 + 1 + 2 + 1


def test_app_works_offline(browser_opts):
    """ネットワークを止めたブラウザで file:// から開いても計算でき、外へは 1 件も読みに行かない。"""
    from explainer_reel_kit import browser as br

    asked: list[str] = []
    with br.sync_playwright() as pw:
        b = br.launch(pw, browser_opts["channel"])
        try:
            ctx = b.new_context(offline=True)

            def guard(route):
                if route.request.url.startswith(("file:", "data:", "about:", "blob:")):
                    route.continue_()
                else:
                    asked.append(route.request.url)
                    route.abort()

            ctx.route("**/*", guard)
            page = ctx.new_page()
            page.goto(APP.as_uri())
            page.select_option('[data-testid="glass-select"]', "gas")
            page.fill('[data-testid="area-input"]', "1")
            page.fill('[data-testid="dt-input"]', "10")
            assert page.text_content('[data-testid="result-value"]') == "11〜19 W"
        finally:
            b.close()
    assert asked == []
