from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from foxengine.services.identity import identity_facet_tuples

_KIND_TO_ROW_FIELD = {
    "email": "email",
    "phone": "phone",
    "username": "username",
    "id_card": "id_card",
}


def _row_identity_inputs(row: dict[str, Any]) -> tuple[str, str, str, str]:
    phone = str(row.get("phone") or "").strip()
    email = str(row.get("email") or "").strip()
    username = str(row.get("username") or "").strip()
    id_card = str(row.get("id_card") or "").strip()
    return phone, email, username, id_card


def identity_facets(row: dict[str, Any]) -> list[str]:
    """Stable facet keys for union-find (kind:value, aligned with lead_identities)."""
    phone, email, username, id_card = _row_identity_inputs(row)
    facets = identity_facet_tuples(phone, email, username, id_card)
    return [f"{kind}:{value}" for kind, value in facets]


def collect_identity_values(rows: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {col: set() for col in _KIND_TO_ROW_FIELD.values()}
    for row in rows:
        phone, email, username, id_card = _row_identity_inputs(row)
        for kind, value in identity_facet_tuples(phone, email, username, id_card):
            values[_KIND_TO_ROW_FIELD[kind]].add(value)
    return {field: sorted(field_values) for field, field_values in values.items()}


def annotate_related_groups(
    rows: list[dict[str, Any]],
    matched_keys: set[tuple[str, int]],
) -> list[dict[str, Any]]:
    parent = list(range(len(rows)))
    first_seen: dict[str, int] = {}
    facets_by_index: list[list[str]] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for idx, row in enumerate(rows):
        facets = identity_facets(row)
        facets_by_index.append(facets)
        for facet in facets:
            owner = first_seen.get(facet)
            if owner is None:
                first_seen[facet] = idx
            else:
                union(owner, idx)

    roots_in_order: dict[int, int] = {}
    for idx, row in enumerate(rows):
        root = find(idx)
        group = roots_in_order.setdefault(root, len(roots_in_order) + 1)
        key = (str(row.get("batch_id", "")), int(row.get("row_in_batch", 0)))
        row["_related_group"] = group
        row["_related_is_match"] = key in matched_keys
        row["_related_identities"] = facets_by_index[idx]

    indexed_rows = list(enumerate(rows))
    return [
        row
        for _, row in sorted(
            indexed_rows,
            key=lambda item: (
                int(item[1]["_related_group"]),
                not bool(item[1]["_related_is_match"]),
                item[0],
            ),
        )
    ]
