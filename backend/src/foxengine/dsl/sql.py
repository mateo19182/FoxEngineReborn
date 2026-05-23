from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from foxengine.dsl.ast_nodes import And, Expr, Not, Or, Pred
from foxengine.dsl.tag_query import (
    combine_tag_positive,
    compile_tag_keys_select,
    contains_tag_pred,
    flatten_and,
    has_mixed_tag_or,
    is_positive_tag_only,
    is_tag_only,
)

FIELD_TO_COLUMN: dict[str, str | None] = {
    "full_name": "full_name",
    "first_name": "first_name",
    "last_name": "last_name",
    "dob": "dob",
    "gender": "gender",
    "address": "address",
    "city": "city",
    "country": "country",
    "zip": "zip",
    "ip": "ip",
    "user_agent": "user_agent",
    "isp": "isp",
    "phone_carrier": "phone_carrier",
    "password": "password",
    "password_hash": "password_hash",
    "last_seen": "last_seen",
    "email.domain": "email_domain",
    "email.local": "email_local",
    "phone.country": None,
}

IDENTITY_FIELD_TO_KIND = {
    "phone": "phone",
    "email": "email",
    "username": "username",
    "id_card": "id_card",
}


@dataclass
class CompiledWhere:
    sql: str
    parameters: dict[str, Any]


@dataclass
class CompiledLeadsQuery:
    """ClickHouse leads filter; tag_keys_select enables tag-first join plans."""

    leads_where: str
    parameters: dict[str, Any]
    tag_keys_select: str | None = None


class CompileError(Exception):
    pass


def _next_name(params: dict[str, Any], base: str) -> str:
    i = 0
    while True:
        name = f"{base}_{i}"
        if name not in params:
            return name
        i += 1


def _split_value(raw: str) -> tuple[str, str]:
    """Return (mode, core) where mode is exact|prefix|suffix|substring."""
    if raw.startswith("*") and raw.endswith("*") and len(raw) >= 2:
        return "substring", raw[1:-1]
    if raw.endswith("*") and len(raw) > 1:
        return "prefix", raw[:-1]
    if raw.startswith("*") and len(raw) > 1:
        return "suffix", raw[1:]
    return "exact", raw


def _string_match(expr: str, mode: str, param_name: str) -> str:
    if mode == "exact":
        return f"{expr} = {{{param_name}:String}}"
    if mode == "prefix":
        return f"startsWith({expr}, {{{param_name}:String}})"
    if mode == "suffix":
        return f"endsWith({expr}, {{{param_name}:String}})"
    return f"position({expr}, {{{param_name}:String}}) > 0"


def _extras_pred_sql(field: str, mode: str, core: str, params: dict[str, Any]) -> str:
    pn = _next_name(params, "ev")
    params[pn] = core
    value_match = _string_match("v", mode, pn)

    if field == "extras":
        return f"arrayExists(v -> {value_match}, mapValues(extras))"

    if field.startswith("extras."):
        subkey = field[len("extras.") :]
        if not subkey:
            raise CompileError("extras subkey must not be empty")
        ek = _next_name(params, "ek")
        params[ek] = subkey
        keyed_match = _string_match("v", mode, pn)
        return (
            "arrayExists("
            f"(k, v) -> lowerUTF8(k) = {{{ek}:String}} AND {keyed_match}, "
            "mapKeys(extras), mapValues(extras))"
        )

    raise CompileError(f"unknown field {field!r}")


def _lead_key_in(table: str, where_sql: str) -> str:
    return (
        "(batch_id, row_in_batch) IN "
        f"(SELECT batch_id, row_in_batch FROM {table} WHERE {where_sql})"
    )


def _pred_sql(
    p: Pred, params: dict[str, Any], tag_uuid_lists: dict[tuple[str, str], list[UUID]]
) -> str:
    field = p.field
    mode, core = _split_value(p.value)

    if field in ("tag", "tag.family", "tag.breach_date"):
        key = (field, p.value)
        uuids = tag_uuid_lists.get(key, [])
        if not uuids:
            return "1 = 0"
        if len(uuids) == 1:
            pn = _next_name(params, "tu")
            params[pn] = str(uuids[0])
            return _lead_key_in("lead_tags", f"tag_id = toUUID({{{pn}:String}})")
        names = []
        for u in uuids:
            pn = _next_name(params, "tu")
            params[pn] = str(u)
            names.append(f"toUUID({{{pn}:String}})")
        inner = ", ".join(names)
        return _lead_key_in("lead_tags", f"tag_id IN ({inner})")

    identity_kind = IDENTITY_FIELD_TO_KIND.get(field)
    if identity_kind:
        pn = _next_name(params, "iv")
        params[pn] = core.lower() if field == "username" else core
        value_predicate = _string_match("identity_value", mode, pn)
        return _lead_key_in(
            "lead_identities",
            f"identity_kind = '{identity_kind}' AND {value_predicate}",
        )

    col = FIELD_TO_COLUMN.get(field)
    if col is None and field == "phone.country":
        pn = _next_name(params, "pc")
        params[pn] = core
        return _lead_key_in(
            "lead_identities",
            f"identity_kind = 'phone' AND startsWith(identity_value, {{{pn}:String}})",
        )

    if field == "extras" or field.startswith("extras."):
        return _extras_pred_sql(field, mode, core, params)

    if not col:
        raise CompileError(f"unknown field {field!r}")

    if col == "dob":
        pn = _next_name(params, "dv")
        params[pn] = core
        return f"dob = toDateOrNull({{{pn}:String}})"

    if col == "last_seen":
        pn = _next_name(params, "ls")
        params[pn] = core
        return f"last_seen = parseDateTimeBestEffortOrNull({{{pn}:String}})"

    pn = _next_name(params, "v")
    params[pn] = core

    return _string_match(col, mode, pn)


def _compile_expr_sql(
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
    params: dict[str, Any],
) -> str:
    def walk(e: Expr) -> str:
        if isinstance(e, Pred):
            return _pred_sql(e, params, tag_uuid_lists)
        if isinstance(e, Not):
            return f"NOT ({walk(e.inner)})"
        if isinstance(e, And):
            inner = " AND ".join(f"({walk(p)})" for p in e.parts)
            return inner or "1 = 1"
        if isinstance(e, Or):
            inner = " OR ".join(f"({walk(p)})" for p in e.parts)
            return inner or "1 = 0"
        raise CompileError("unsupported expression")

    return walk(expr)


def _try_tag_first_compile(
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
    params: dict[str, Any],
) -> CompiledLeadsQuery | None:
    if has_mixed_tag_or(expr) or not contains_tag_pred(expr):
        return None

    if is_positive_tag_only(expr):
        return CompiledLeadsQuery(
            leads_where="1 = 1",
            parameters=params,
            tag_keys_select=compile_tag_keys_select(expr, tag_uuid_lists, params),
        )

    parts = flatten_and(expr)
    tag_positive: list[Expr] = []
    leads_parts: list[Expr] = []
    for part in parts:
        if isinstance(part, Not) and is_tag_only(part.inner):
            leads_parts.append(part)
        elif is_positive_tag_only(part):
            tag_positive.append(part)
        else:
            leads_parts.append(part)

    if not tag_positive:
        return None

    tag_expr = combine_tag_positive(tag_positive)
    leads_where = "1 = 1"
    if leads_parts:
        if len(leads_parts) == 1:
            leads_where = _compile_expr_sql(leads_parts[0], tag_uuid_lists, params)
        else:
            leads_where = _compile_expr_sql(And(leads_parts), tag_uuid_lists, params)

    return CompiledLeadsQuery(
        leads_where=leads_where,
        parameters=params,
        tag_keys_select=compile_tag_keys_select(tag_expr, tag_uuid_lists, params),
    )


def compile_leads_query(
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
) -> CompiledLeadsQuery:
    params: dict[str, Any] = {}
    tag_first = _try_tag_first_compile(expr, tag_uuid_lists, params)
    if tag_first is not None:
        return tag_first
    sql = _compile_expr_sql(expr, tag_uuid_lists, params)
    return CompiledLeadsQuery(leads_where=sql, parameters=params, tag_keys_select=None)


def compile_expr(
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
) -> CompiledWhere:
    params: dict[str, Any] = {}
    sql = _compile_expr_sql(expr, tag_uuid_lists, params)
    return CompiledWhere(sql=sql, parameters=params)
