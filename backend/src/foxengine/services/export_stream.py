"""Fallback export: keyset batches from ClickHouse, stream bytes to S3."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from foxengine.dsl.sql import CompiledLeadsQuery
from foxengine.services.export_query import (
    CH_EXPORT_SETTINGS,
    CH_STREAM_EXPORT_SETTINGS,
    ExportCursor,
    export_columns_with_cursor,
    export_ch_format,
    leads_export_batch_sql,
    leads_export_s3_insert_sql,
    normalize_export_columns,
)
from foxengine.services.export_s3 import ExportS3Writer

log = logging.getLogger(__name__)

BatchProgressFn = Callable[[int, ExportCursor | None], Awaitable[None]]


def _export_json_default(o: Any) -> Any:
    if isinstance(o, (bytes, bytearray)):
        return o.decode("utf-8", errors="replace")
    return str(o)


def _fmt_csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, default=_export_json_default)
    return str(v)


async def try_export_clickhouse_s3(
    ch: Any,
    *,
    compiled: CompiledLeadsQuery,
    s3_url: str,
    access_key: str,
    secret_key: str,
    export_format: str,
    row_cap: int,
    columns: list[str] | tuple[str, ...] | None = None,
    query_id: str | None = None,
) -> None:
    ch_fmt = export_ch_format(export_format)
    export_columns = normalize_export_columns(columns)
    sql = leads_export_s3_insert_sql(
        compiled,
        s3_url=s3_url,
        access_key=access_key,
        secret_key=secret_key,
        ch_format=ch_fmt,
        row_cap=row_cap,
        columns=export_columns,
    )
    settings = dict(CH_EXPORT_SETTINGS)
    if query_id:
        settings["query_id"] = query_id
    await ch.command(sql, parameters=compiled.parameters, settings=settings)


async def export_streaming_to_s3(
    ch: Any,
    *,
    compiled: CompiledLeadsQuery,
    writer: ExportS3Writer,
    export_format: str,
    row_cap: int,
    batch_size: int,
    cursor: ExportCursor | None,
    columns: list[str] | tuple[str, ...] | None = None,
    csv_include_header: bool = True,
    on_batch: BatchProgressFn | None = None,
) -> tuple[int, ExportCursor | None]:
    total_written = 0
    last_cursor = cursor
    export_columns = normalize_export_columns(columns)
    query_columns = export_columns_with_cursor(export_columns)
    csv_header_pending = csv_include_header

    while total_written < row_cap:
        lim = min(batch_size, row_cap - total_written)
        rows = await _fetch_batch(ch, compiled, lim, last_cursor, query_columns)
        if not rows:
            break
        if export_format == "csv":
            chunk = _encode_csv_batch(
                rows,
                list(export_columns),
                include_header=csv_header_pending,
            )
            csv_header_pending = False
            await writer.write(chunk)
            batch_count = len(rows)
        else:
            chunk = _encode_jsonl_batch(rows, export_columns)
            await writer.write(chunk)
            batch_count = len(rows)

        last_cursor = ExportCursor.from_mapping(rows[-1])
        total_written += batch_count
        if on_batch is not None:
            await on_batch(total_written, last_cursor)
        if batch_count < lim:
            break

    return total_written, last_cursor


async def _fetch_batch(
    ch: Any,
    compiled: CompiledLeadsQuery,
    limit: int,
    cursor: ExportCursor | None,
    columns: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    params = dict(compiled.parameters)
    if cursor is not None:
        params.update(cursor.to_parameters())
    sql = leads_export_batch_sql(compiled, limit=limit, cursor=cursor, columns=columns)
    qr = await ch.query(sql, parameters=params, settings=CH_STREAM_EXPORT_SETTINGS)
    return [dict(r) for r in qr.named_results()]


def _encode_csv_batch(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    include_header: bool,
) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if include_header:
        writer.writerow(columns)
    for row in rows:
        d = dict(row)
        writer.writerow([_fmt_csv_cell(d.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8")


def _encode_jsonl_batch(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> bytes:
    lines = []
    for row in rows:
        d = dict(row)
        lines.append(
            json.dumps(
                {col: d.get(col) for col in columns},
                ensure_ascii=False,
                default=_export_json_default,
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")
