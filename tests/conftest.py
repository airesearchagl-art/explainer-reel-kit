from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLE = ROOT / "examples" / "hello-kit.storyboard.md"
TEMPLATE = ROOT / "src" / "explainer_reel_kit" / "data" / "templates" / "storyboard.md"
COMPAT = sorted((FIXTURES / "compat").glob("*.storyboard.json"))


@pytest.fixture
def example_doc():
    from explainer_reel_kit import storyboard as sb
    return sb.load_storyboard(EXAMPLE)


@pytest.fixture
def compat_docs():
    return {p.stem.split(".")[0]: json.loads(p.read_text(encoding="utf-8")) for p in COMPAT}


@pytest.fixture
def clone():
    return copy.deepcopy


@pytest.fixture(scope="session")
def browser_opts():
    """使えるブラウザ（Playwright の Chromium → chrome → msedge）。なければ skip。"""
    pytest.importorskip("playwright.sync_api")
    from explainer_reel_kit import browser as br

    for channel in (None, "chrome", "msedge"):
        try:
            with br.sync_playwright() as pw:
                br.launch(pw, channel).close()
            return {"channel": channel}
        except br.BrowserError:
            continue
    msg = "Playwright で起動できるブラウザがありません（python -m playwright install chromium）"
    if os.environ.get("ERKIT_REQUIRE_BROWSER"):
        pytest.fail(msg)
    pytest.skip(msg)


def write_storyboard(path, scenes, *, reel_id="t", confidentiality="general"):
    """テスト用の台本（kit-1.0.0、JSON）を書く。intro / outro は例の台本のもの。
    scenes はシーンの dict の並び（id・image・capture など。足りない項目は埋める）。"""
    from explainer_reel_kit import storyboard as sb

    doc = sb.load_storyboard(EXAMPLE)
    doc["reel"].update(id=reel_id, output_name="t")
    doc["reel"].pop("confidentiality", None)
    if confidentiality is not None:
        doc["reel"]["confidentiality"] = confidentiality
    full = []
    for sc in scenes:
        item = {"heading": "画面を確かめる", "narration": "説明します。", "recipe": "highlight_box"}
        item.update(sc)
        full.append(item)
    doc["scenes"] = full
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path
