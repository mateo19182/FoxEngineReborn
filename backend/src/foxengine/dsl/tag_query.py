"""Tag-first ClickHouse compilation for DSL queries (lead_tags driving the join)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from foxengine.dsl.ast_nodes import And, Expr, Not, Or, Pred

TAG_FIELDS = frozenset({"tag", "tag.family", "tag.breach_date"})


def is_tag_field(field: str) -> bool:
    return field in TAG_FIELDS


def is_tag_pred(expr: Expr) -> bool:
    return isinstance(expr, Pred) and is_tag_field(expr.field)


def is_tag_only(expr: Expr) -> bool:
    if isinstance(expr, Pred):
        return is_tag_field(expr.field)
    if isinstance(expr, Not):
        return is_tag_only(expr.inner)
    if isinstance(expr, And | Or):
        return all(is_tag_only(p) for p in expr.parts)
    return False


def is_positive_tag_only(expr: Expr) -> bool:
    """Tag expression without NOT (safe to drive lead_tags scan)."""
    if isinstance(expr, Not):
        return False
    if isinstance(expr, Pred):
        return is_tag_field(expr.field)
    if isinstance(expr, And | Or):
        return all(is_positive_tag_only(p) for p in expr.parts)
    return False


def contains_tag_pred(expr: Expr) -> bool:
    if isinstance(expr, Pred):
        return is_tag_field(expr.field)
    if isinstance(expr, Not):
        return contains_tag_pred(expr.inner)
    if isinstance(expr, And | Or):
        return any(contains_tag_pred(p) for p in expr.parts)
    return False


def contains_non_tag_pred(expr: Expr) -> bool:
    if isinstance(expr, Pred):
        return not is_tag_field(expr.field)
    if isinstance(expr, Not):
        return contains_non_tag_pred(expr.inner)
    if isinstance(expr, And | Or):
        return any(contains_non_tag_pred(p) for p in expr.parts)
    return False


def has_mixed_tag_or(expr: Expr) -> bool:
    """True when an OR mixes tag predicates with non-tag predicates."""
    if isinstance(expr, Or):
        has_tag = any(contains_tag_pred(p) for p in expr.parts)
        has_non_tag = any(contains_non_tag_pred(p) for p in expr.parts)
        if has_tag and has_non_tag:
            return True
        return any(has_mixed_tag_or(p) for p in expr.parts)
    if isinstance(expr, And):
        return any(has_mixed_tag_or(p) for p in expr.parts)
    if isinstance(expr, Not):
        return has_mixed_tag_or(expr.inner)
    return False


def flatten_and(expr: Expr) -> list[Expr]:
    if isinstance(expr, And):
        out: list[Expr] = []
        for part in expr.parts:
            out.extend(flatten_and(part))
        return out
    return [expr]


TagUuidMap = dict[tuple[str, str], list[UUID]]


def _uuids_for_tag_pred(pred: Pred, tag_uuid_lists: TagUuidMap) -> list[UUID]:
    return list(tag_uuid_lists.get((pred.field, pred.value), []))


def _uuids_for_tag_child(expr: Expr, tag_uuid_lists: TagUuidMap) -> list[UUID]:
    if isinstance(expr, Pred):
        return _uuids_for_tag_pred(expr, tag_uuid_lists)
    if isinstance(expr, Or):
        out: list[UUID] = []
        for part in expr.parts:
            out.extend(_uuids_for_tag_child(part, tag_uuid_lists))
        return out
    raise ValueError("tag child must be Pred or Or")


def _next_name(params: dict[str, Any], base: str) -> str:
    i = 0
    while True:
        name = f"{base}_{i}"
        if name not in params:
            return name
        i += 1


def _tag_id_in_sql(uuids: list[UUID], params: dict[str, Any], *, param_base: str = "tu") -> str:
    if not uuids:
        return "1 = 0"
    if len(uuids) == 1:
        pn = _next_name(params, param_base)
        params[pn] = str(uuids[0])
        return f"toUUID({{{pn}:String}})"
    names: list[str] = []
    for u in uuids:
        pn = _next_name(params, param_base)
        params[pn] = str(u)
        names.append(f"toUUID({{{pn}:String}})")
    return "tag_id IN (" + ", ".join(names) + ")"


def _tag_child_having(
    child: Expr, tag_uuid_lists: dict[tuple[str, str], list[UUID]], params: dict[str, Any]
) -> str:
    uuids = _uuids_for_tag_child(child, tag_uuid_lists)
    if not uuids:
        return "0"
    in_sql = _tag_id_in_sql(uuids, params)
    if in_sql.startswith("tag_id IN"):
        return f"countIf({in_sql}) > 0"
    return f"countIf(tag_id = {in_sql}) > 0"


def compile_tag_keys_select(
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
    params: dict[str, Any],
) -> str:
    """SELECT batch_id, row_in_batch FROM lead_tags … for positive tag-only expressions."""
    if isinstance(expr, Pred):
        uuids = _uuids_for_tag_pred(expr, tag_uuid_lists)
        if not uuids:
            return "SELECT batch_id, row_in_batch FROM lead_tags WHERE 1 = 0"
        where = _tag_id_in_sql(uuids, params)
        if where.startswith("tag_id IN"):
            pass
        else:
            where = f"tag_id = {where}"
        return f"SELECT DISTINCT batch_id, row_in_batch FROM lead_tags WHERE {where}"

    if isinstance(expr, Or):
        uuids: list[UUID] = []
        for part in expr.parts:
            uuids.extend(_uuids_for_tag_child(part, tag_uuid_lists))
        if not uuids:
            return "SELECT batch_id, row_in_batch FROM lead_tags WHERE 1 = 0"
        where = _tag_id_in_sql(uuids, params)
        if not where.startswith("tag_id IN"):
            where = f"tag_id = {where}"
        return f"SELECT DISTINCT batch_id, row_in_batch FROM lead_tags WHERE {where}"

    if isinstance(expr, And):
        having_parts = [_tag_child_having(part, tag_uuid_lists, params) for part in expr.parts]
        if any(h == "0" for h in having_parts):
            return "SELECT batch_id, row_in_batch FROM lead_tags WHERE 1 = 0"
        all_uuids: list[UUID] = []
        for part in expr.parts:
            all_uuids.extend(_uuids_for_tag_child(part, tag_uuid_lists))
        if not all_uuids:
            return "SELECT batch_id, row_in_batch FROM lead_tags WHERE 1 = 0"
        where = _tag_id_in_sql(all_uuids, params)
        if not where.startswith("tag_id IN"):
            where = f"tag_id = {where}"
        having = " AND ".join(having_parts)
        return (
            "SELECT batch_id, row_in_batch FROM lead_tags "
            f"WHERE {where} "
            "GROUP BY batch_id, row_in_batch "
            f"HAVING {having}"
        )

    raise ValueError(f"unsupported tag expression: {expr!r}")


def combine_tag_positive(parts: list[Expr]) -> Expr:
    if len(parts) == 1:
        return parts[0]
    return And(parts)
