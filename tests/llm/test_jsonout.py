from __future__ import annotations

import pytest

from explainer_reel_kit.llm.jsonout import check_json, extract_json

JSON_SCHEMA = {
    "type": "object",
    "required": ["title", "scenes"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "scenes": {"type": "array", "minItems": 3, "maxItems": 3,
                   "items": {"type": "object", "required": ["heading", "narration"],
                             "properties": {"heading": {"type": "string", "minLength": 1},
                                            "narration": {"type": "string", "minLength": 1}}}},
    },
}
GOOD = '{"title": "t", "scenes": [{"heading": "a", "narration": "b"}, {"heading": "c", "narration": "d"}, {"heading": "e", "narration": "f"}]}'


@pytest.mark.parametrize(
    "text, exact",
    [
        (GOOD, True),
        ("  " + GOOD + "\n", True),
        ("```json\n" + GOOD + "\n```", False),
        ("はい、こちらです。\n```\n" + GOOD + "\n```\n以上です。", False),
        ("台本です: " + GOOD + " よろしくお願いします", False),
        ("<think>考え中 {not json}</think>\n" + GOOD, False),
    ],
)
def test_extract_json(text, exact):
    value, is_exact = extract_json(text)
    assert value["title"] == "t" and is_exact is exact


@pytest.mark.parametrize("text", ["", "JSON はありません", "{broken", "```json\n{broken}\n```"])
def test_extract_json_fails(text):
    with pytest.raises(ValueError):
        extract_json(text)


def test_check_json_schema():
    assert check_json(GOOD, JSON_SCHEMA).schema_ok
    two = '{"title": "t", "scenes": [{"heading": "a", "narration": "b"}]}'
    result = check_json(two, JSON_SCHEMA)
    assert result.parsed and not result.schema_ok and "scenes" in result.error
    assert not check_json("nope", JSON_SCHEMA).parsed
