from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from foxengine.dsl.ast_nodes import And, Expr, Not, Or, Pred

FIELD_TO_COLUMN: dict[str, str | None] = {
    "phone": "phone_norm",
    "email": "email_norm",
    "username": "username",
    "id_card": "id_card",
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


@dataclass
class CompiledWhere:
    sql: str
    parameters: dict[str, Any]


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


def _pred_sql(
    p: Pred, params: dict[str, Any], tag_uuid_lists: dict[tuple[str, str], list[UUID]]
) -> str:
    field = p.field
    mode, core = _split_value(p.value)

    if field in ("tag", "tag.type", "tag.breach_date"):
        key = (field, p.value)
        uuids = tag_uuid_lists.get(key, [])
        if not uuids:
            return "1 = 0"
        if len(uuids) == 1:
            pn = _next_name(params, "tu")
            params[pn] = str(uuids[0])
            return f"has(tag_ids, toUUID({{{pn}:String}}))"
        names = []
        for u in uuids:
            pn = _next_name(params, "tu")
            params[pn] = str(u)
            names.append(f"toUUID({{{pn}:String}})")
        inner = ", ".join(names)
        return f"hasAny(tag_ids, [{inner}])"

    col = FIELD_TO_COLUMN.get(field)
    if col is None and field == "phone.country":
        pn = _next_name(params, "pc")
        params[pn] = core
        return f"startsWith(phone_norm, {{{pn}:String}})"

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

    if mode == "exact":
        return f"{col} = {{{pn}:String}}"
    if mode == "prefix":
        return f"startsWith({col}, {{{pn}:String}})"
    if mode == "suffix":
        return f"endsWith({col}, {{{pn}:String}})"
    return f"position({col}, {{{pn}:String}}) > 0"


def compile_expr(
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
) -> CompiledWhere:
    params: dict[str, Any] = {}

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

    sql = walk(expr)
    return CompiledWhere(sql=sql, parameters=params)
