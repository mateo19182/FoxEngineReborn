"""Canonical tag types and families (aligned with PLAN.md: LOGIN / VM / LEAK)."""

from __future__ import annotations

from collections import defaultdict
from typing import Final

# Family codes group tag types for coarse filtering (DSL: tag.family:DATA_LEAK).
TAG_FAMILIES: Final[tuple[str, ...]] = ("CREDENTIAL", "DATA_LEAK", "INFRASTRUCTURE")

# Each tag type belongs to exactly one family.
TYPE_TO_FAMILY: Final[dict[str, str]] = {
    "LOGIN": "CREDENTIAL",
    "LEAK": "DATA_LEAK",
    "VM": "INFRASTRUCTURE",
}

VALID_TAG_TYPES: Final[frozenset[str]] = frozenset(TYPE_TO_FAMILY)

_m: dict[str, list[str]] = defaultdict(list)
for _typ, _fam in TYPE_TO_FAMILY.items():
    _m[_fam].append(_typ)
FAMILY_TO_TYPES: Final[dict[str, tuple[str, ...]]] = {k: tuple(sorted(v)) for k, v in _m.items()}
del _m, _typ, _fam


def types_for_family(family_code: str) -> tuple[str, ...] | None:
    """Return tag types in this family, or None if family is unknown."""
    key = family_code.strip().upper()
    return FAMILY_TO_TYPES.get(key)


def family_for_type(tag_type: str | None) -> str | None:
    """Return the family for a stored tag type, or None if missing / unknown."""
    if tag_type is None or not str(tag_type).strip():
        return None
    return TYPE_TO_FAMILY.get(str(tag_type).strip().upper())


def normalize_tag_type(value: str | None) -> str | None:
    """Return canonical tag type string, or None for empty input."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.upper()


def assert_known_tag_type(value: str | None) -> str | None:
    """Normalize and require that non-empty values are valid tag types."""
    c = normalize_tag_type(value)
    if c is None:
        return None
    if c not in VALID_TAG_TYPES:
        allowed = ", ".join(sorted(VALID_TAG_TYPES))
        raise ValueError(f"unknown tag type {value!r}; allowed: {allowed}")
    return c


def taxonomy_payload() -> dict[str, object]:
    """Shape for GET /tags/taxonomy and OpenAPI."""
    types = [{"code": t, "family": TYPE_TO_FAMILY[t]} for t in sorted(TYPE_TO_FAMILY)]
    families = [{"code": f, "types": list(FAMILY_TO_TYPES[f])} for f in TAG_FAMILIES]
    return {"types": types, "families": families}
