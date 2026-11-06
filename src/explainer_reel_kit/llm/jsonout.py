"""Pull a JSON object out of a model answer and check it against a schema."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class JsonCheck:
    parsed: bool
    schema_ok: bool
    exact: bool  # the whole answer was the JSON object (no fences, no surrounding text)
    value: Any = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"parsed": self.parsed, "schema_ok": self.schema_ok, "exact": self.exact, "error": self.error}


def extract_json(text: str) -> tuple[Any, bool]:
    """(value, exact). Accepts a bare object, a ```json fenced block, or the first {...} span.

    Reasoning models' ``<think>…</think>`` blocks are dropped first. Raises ValueError if no
    JSON object can be found.
    """
    cleaned = _THINK_RE.sub("", text).strip()
    try:
        return json.loads(cleaned), cleaned == text.strip()
    except json.JSONDecodeError:
        pass
    for match in _FENCE_RE.finditer(cleaned):
        try:
            return json.loads(match.group(1).strip()), False
        except json.JSONDecodeError:
            continue
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1]), False
        except json.JSONDecodeError as error:
            raise ValueError(f"JSON として読めません: {error}") from error
    raise ValueError("応答に JSON オブジェクトがありません")


def check_json(text: str, schema: dict[str, Any]) -> JsonCheck:
    try:
        value, exact = extract_json(text)
    except ValueError as error:
        return JsonCheck(False, False, False, None, str(error))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        return JsonCheck(True, False, exact, value, f"{where}: {first.message}")
    return JsonCheck(True, True, exact, value, None)
