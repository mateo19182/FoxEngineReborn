"""Compile DSL to a ClickHouse WHERE clause plus parameters (shared by query and export)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.dsl.parser import parse_dsl
from foxengine.dsl.sql import compile_expr, compile_tag_keys_rows_sql
from foxengine.services.deleted_batches import deleted_batch_sql_clause
from foxengine.services.tags_resolve import resolve_tag_predicates, walk_preds

_LEADS_EXCEPT = "batch_id, row_in_batch, extras"
_KEYSET_ORDER = "ingest_ts DESC, batch_id ASC, row_in_batch ASC"


@dataclass(frozen=True)
class KeysetCursor:
    ingest_ts: str
    batch_id: str
    row_in_batch: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> KeysetCursor:
        return cls(
            ingest_ts=str(row["ingest_ts"]),
            batch_id=str(row["batch_id"]),
            row_in_batch=int(row["row_in_batch"]),
        )

    @classmethod
    def from_checkpoint(cls, raw: object) -> KeysetCursor | None:
        if not isinstance(raw, dict):
            return None
        data = cast(dict[str, Any], raw)
        ts = data.get("ingest_ts")
        bid = data.get("batch_id")
        rib = data.get("row_in_batch")
        if not isinstance(ts, str) or not isinstance(bid, str):
            return None
        if isinstance(rib, int):
            row_in_batch = rib
        elif isinstance(rib, str):
            try:
                row_in_batch = int(rib)
            except ValueError:
                return None
        else:
            return None
        return cls(ingest_ts=ts, batch_id=bid, row_in_batch=row_in_batch)

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "ingest_ts": self.ingest_ts,
            "batch_id": self.batch_id,
            "row_in_batch": self.row_in_batch,
        }


@dataclass(frozen=True)
class CompiledLeadsQuery:
    leads_where_sql: str
    parameters: dict[str, Any]
    tag_keys_rows_sql: str | None = None


async def compile_leads_query(session: AsyncSession, dsl: str) -> CompiledLeadsQuery:
    ast = parse_dsl(dsl)
    preds = walk_preds(ast)
    tag_map = await resolve_tag_predicates(session, preds)
    cw = compile_expr(ast, tag_map)
    tag_keys = compile_tag_keys_rows_sql(ast, tag_map)
    extra, extra_params = await deleted_batch_sql_clause(session)
    params = dict(cw.parameters)
    params.update(extra_params)
    tag_keys_rows_sql = None
    if tag_keys is not None:
        if extra:
            tag_keys_rows_sql = (
                "SELECT batch_id, row_in_batch, ingest_ts FROM ("
                f"{tag_keys.sql}) AS tag_keys WHERE 1 = 1{extra}"
            )
        else:
            tag_keys_rows_sql = tag_keys.sql
    return CompiledLeadsQuery(
        leads_where_sql=f"({cw.sql}){extra}",
        parameters=params,
        tag_keys_rows_sql=tag_keys_rows_sql,
    )


async def compile_leads_where(session: AsyncSession, dsl: str) -> tuple[str, dict[str, Any]]:
    query = await compile_leads_query(session, dsl)
    return query.leads_where_sql, query.parameters


def keyset_parameters(cursor: KeysetCursor) -> dict[str, Any]:
    return {
        "cur_ts": cursor.ingest_ts,
        "cur_bid": cursor.batch_id,
        "cur_rib": cursor.row_in_batch,
    }


def _keyset_after_sql(prefix: str) -> str:
    col = f"{prefix}." if prefix else ""
    return (
        f"(({col}ingest_ts < {{cur_ts:DateTime}}) "
        f"OR ({col}ingest_ts = {{cur_ts:DateTime}} AND {col}batch_id > {{cur_bid:UUID}}) "
        f"OR ({col}ingest_ts = {{cur_ts:DateTime}} AND {col}batch_id = {{cur_bid:UUID}} "
        f"AND {col}row_in_batch > {{cur_rib:UInt32}}))"
    )


def leads_count_sql(query: CompiledLeadsQuery) -> str:
    if query.tag_keys_rows_sql is not None:
        return f"SELECT count() FROM ({query.tag_keys_rows_sql})"
    return f"SELECT count() FROM leads WHERE {query.leads_where_sql}"


def leads_bounded_count_sql(query: CompiledLeadsQuery, cap: int) -> str:
    lim = int(cap) + 1
    if query.tag_keys_rows_sql is not None:
        inner = query.tag_keys_rows_sql
    else:
        inner = f"SELECT batch_id, row_in_batch FROM leads WHERE {query.leads_where_sql}"
    return f"SELECT count() FROM (SELECT 1 FROM ({inner}) LIMIT {lim})"


def leads_select_sql(
    where_sql: str,
    *,
    limit: int,
    offset: int = 0,
    include_extras: bool = False,
    tag_keys_rows_sql: str | None = None,
    cursor: KeysetCursor | None = None,
) -> str:
    lim = int(limit)
    off = int(offset)
    exc = _LEADS_EXCEPT if not include_extras else "batch_id, row_in_batch"

    if tag_keys_rows_sql is not None:
        keyset = ""
        if cursor is not None:
            keyset = f"WHERE {_keyset_after_sql('tag_keys')}\n    "
        pagination = f"{keyset}ORDER BY {_KEYSET_ORDER}\n    LIMIT {lim}"
        if cursor is None and off:
            pagination = f"ORDER BY {_KEYSET_ORDER}\n    LIMIT {lim} OFFSET {off}"
        return f"""
WITH sorted_keys AS (
    SELECT batch_id, row_in_batch, ingest_ts
    FROM ({tag_keys_rows_sql}) AS tag_keys
    {pagination}
)
SELECT
    l.batch_id AS batch_id,
    l.row_in_batch AS row_in_batch,
    l.* EXCEPT ({exc})
FROM leads AS l
WHERE (l.batch_id, l.row_in_batch) IN (
    SELECT batch_id, row_in_batch FROM sorted_keys
)
ORDER BY l.ingest_ts DESC, l.batch_id ASC, l.row_in_batch ASC
""".strip()

    keyset_clause = ""
    if cursor is not None:
        keyset_clause = f" AND {_keyset_after_sql('l')}"
    pagination = f"LIMIT {lim}"
    if cursor is None and off:
        pagination = f"LIMIT {lim} OFFSET {off}"
    return f"""
SELECT
    l.batch_id AS batch_id,
    l.row_in_batch AS row_in_batch,
    l.* EXCEPT ({exc})
FROM leads AS l
WHERE {where_sql}{keyset_clause}
ORDER BY l.ingest_ts DESC, l.batch_id ASC, l.row_in_batch ASC
{pagination}
""".strip()
