"""JSON parsing helpers for LLM output that may be wrapped in code fences or prose."""
from __future__ import annotations

import json
import re

_JSON_OBJECT_PATTERN = re.compile(r"\{[^{}]*\}", re.DOTALL)


def extract_json_object(text: str) -> dict:
    """Parse the first JSON object from raw LLM output.

    Handles three common shapes:
    1. Bare JSON object.
    2. JSON wrapped in ``` fences (with or without a language tag).
    3. JSON object embedded anywhere in a longer prose response.

    Raises ``ValueError`` if no JSON object can be extracted, or propagates the
    underlying ``json.JSONDecodeError`` when the shallow object is malformed.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fenced = re.sub(r"^```[^\n]*\n(.*?)\n```\s*$", r"\1", stripped, flags=re.DOTALL)
    try:
        return json.loads(fenced.strip())
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_PATTERN.search(stripped)
    if m:
        return json.loads(m.group())
    raise ValueError(f"no JSON object found in: {stripped!r}")
