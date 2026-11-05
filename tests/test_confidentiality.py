"""区分の既定（未記入・読めない値は confidential）。"""
from __future__ import annotations

import pytest

from explainer_reel_kit import storyboard as sb


@pytest.mark.parametrize("doc, expected", [
    ({"reel": {"confidentiality": "general"}}, "general"),
    ({"reel": {"confidentiality": "confidential"}}, "confidential"),
    ({"reel": {}}, "confidential"),                                # 未記入
    ({"reel": {"schema_version": "1.0.0"}}, "confidential"),       # 1.0.0 の台本
    ({"reel": {"confidentiality": "General"}}, "confidential"),    # 書き間違い
    ({"reel": {"confidentiality": "public"}}, "confidential"),     # 知らない値
    ({"reel": {"confidentiality": None}}, "confidential"),
    ({"reel": "x"}, "confidential"),
    ({}, "confidential"),
    (None, "confidential"),
    ("text", "confidential"),
])
def test_confidentiality_default_is_confidential(doc, expected):
    assert sb.confidentiality(doc) == expected


def test_template_default_is_confidential():
    from conftest import TEMPLATE
    assert sb.confidentiality(sb.load_storyboard(TEMPLATE)) == "confidential"


def test_example_is_general(example_doc):
    assert sb.confidentiality(example_doc) == "general"
