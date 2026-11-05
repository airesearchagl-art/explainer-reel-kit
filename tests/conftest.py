from __future__ import annotations

import copy
import json
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
