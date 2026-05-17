"""Local-LLM assisted CSV column mapping."""

from __future__ import annotations

import json
import re
from typing import Any

from foxengine.services.format_detect import CANONICAL_FIELDS
from foxengine.services.llm_client import LlmError, chat_completion

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = _JSON_OBJECT.search(stripped)
    if match:
        stripped = match.group(0)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise LlmError("LLM returned invalid JSON") from e
    if not isinstance(parsed, dict):
        raise LlmError("LLM returned JSON that is not an object")
    return parsed


async def suggest_column_map_with_llm(
    *,
    headers: list[str],
    sample_rows: list[dict[str, str]],
    inner_name: str | None,
) -> dict[str, str]:
    """Return an exact CSV header -> canonical field map suggested by the local LLM."""
    header_set = set(headers)
    canonical = set(CANONICAL_FIELDS)
    system = (
        "You map CSV column headers to FoxEngine canonical lead fields. "
        "Return only a JSON object. Keys must be exact source header strings from the input. "
        "Values must be one of the canonical fields. Omit headers that should not be mapped."
    )
    user = json.dumps(
        {
            "inner_name": inner_name or "",
            "canonical_fields": list(CANONICAL_FIELDS),
            "headers": headers,
            "sample_rows": sample_rows[:12],
        },
        ensure_ascii=False,
    )
    content = await chat_completion(system=system, user=user)
    parsed = _extract_json_object(content)

    out: dict[str, str] = {}
    for raw_header, raw_field in parsed.items():
        header = str(raw_header)
        field = str(raw_field)
        if header not in header_set:
            continue
        if field not in canonical:
            raise LlmError(f"LLM returned unknown canonical field: {field}")
        out[header] = field
    return out
