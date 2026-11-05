"""例の台本: 説明図（erkit diagram）と撮影（erkit capture）の marks.json から、スライドの赤枠・矢印の位置が決まる。"""
from __future__ import annotations

from conftest import EXAMPLE, ROOT
from explainer_reel_kit.capture.web import capture as wc
from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.diagram import run_diagram


def _quiet(*_):
    pass


def test_diagram_and_capture_marks_drive_deck(tmp_path, browser_opts):
    assets = tmp_path / "assets_root"
    assert run_diagram(EXAMPLE, assets, log=_quiet, **browser_opts)["failed"] == 0
    assert wc.run_capture(EXAMPLE, assets, serve=ROOT / "examples" / "hello-page", log=_quiet,
                          **browser_opts)["failed"] == 0
    res = build_deck(EXAMPLE, tmp_path / "hello.pptx", assets_root=assets)
    assert res.unresolved == [], res.unresolved_text()
    by = {(a.scene, a.mark): a for a in res.annotations}
    assert by[("s01", "scene_block")].status == "mark"     # 説明図の data-mark
    assert by[("s03", "result_area")].status == "mark"     # 撮影の操作定義の marks
