"""Local-LLM assisted CSV column mapping."""

from __future__ import annotations

import json
import re
from typing import Any

from foxengine.services.format_detect import CANONICAL_FIELDS
from foxengine.services.llm_client import LlmError, chat_completion

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_THINKING_BLOCK = re.compile(
    r"<think(?:ing)?>.*?</think(?:ing)?>",
    re.DOTALL | re.IGNORECASE,
)

_COLUMN_MAP_MAX_TOKENS = 2048
_LLM_SAMPLE_ROWS = 5
_LLM_SAMPLE_CELL_CHARS = 80


def _strip_thinking(text: str) -> str:
    return _THINKING_BLOCK.sub("", text).strip()


def _trim_sample_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows[:_LLM_SAMPLE_ROWS]:
        trimmed: dict[str, str] = {}
        for key, value in row.items():
            s = str(value)
            if len(s) > _LLM_SAMPLE_CELL_CHARS:
                s = s[:_LLM_SAMPLE_CELL_CHARS] + "…"
            trimmed[str(key)] = s
        out.append(trimmed)
    return out


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_thinking(text.strip())
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
        "You map CSV column headers to FoxEngine canonical lead fields using headers and sample_rows. "
        "Reply with a single JSON object only: no markdown, no explanation, no chain-of-thought. "
        "Keys must be exact header strings from the input. "
        "Values must be one of canonical_fields. Omit unmapped headers."
    )
    user = json.dumps(
        {
            "inner_name": inner_name or "",
            "canonical_fields": list(CANONICAL_FIELDS),
            "headers": headers,
            "sample_rows": _trim_sample_rows(sample_rows),
        },
        ensure_ascii=False,
    )
    content = await chat_completion(
        system=system,
        user=user,
        max_tokens=_COLUMN_MAP_MAX_TOKENS,
    )
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
