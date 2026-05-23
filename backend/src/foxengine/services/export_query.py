"""ClickHouse SQL for export jobs (keyset batches and server-side S3 writes)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from foxengine.dsl.sql import CompiledLeadsQuery

# Columns written to export files (no per-row tag aggregation; keeps export memory bounded).
EXPORT_LEAD_COLUMNS: tuple[str, ...] = (
    "batch_id",
    "row_in_batch",
    "ingest_ts",
    "phone_norm",
    "phone_raw",
    "email_norm",
    "email_raw",
    "email_local",
    "email_domain",
    "username",
    "id_card",
    "full_name",
    "first_name",
    "last_name",
    "dob",
    "gender",
    "address",
    "city",
    "country",
    "zip",
    "ip",
    "user_agent",
    "isp",
    "phone_carrier",
    "password",
    "password_hash",
    "last_seen",
    "extras",
)

CH_EXPORT_SETTINGS: dict[str, Any] = {
    "max_execution_time": 3600,
    "max_memory_usage": "8000000000",
    "s3_truncate_on_insert": 1,
}

CH_STREAM_EXPORT_SETTINGS: dict[str, Any] = {
    "max_execution_time": 3600,
    "max_memory_usage": "8000000000",
}


@dataclass(frozen=True, slots=True)
class ExportCursor:
    ingest_ts: datetime
    batch_id: UUID
    row_in_batch: int

    def to_parameters(self) -> dict[str, Any]:
        return {
            "cursor_ts": self.ingest_ts,
            "cursor_bid": self.batch_id,
            "cursor_rib": self.row_in_batch,
        }

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> ExportCursor:
        ts = row["ingest_ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        bid = row["batch_id"]
        if isinstance(bid, str):
            bid = UUID(bid)
        return cls(
            ingest_ts=ts,
            batch_id=bid,
            row_in_batch=int(row["row_in_batch"]),
        )

    @classmethod
    def from_checkpoint(cls, raw: object) -> ExportCursor | None:
        if not isinstance(raw, dict):
            return None
        try:
            ts_s = raw["ingest_ts"]
            bid_s = raw["batch_id"]
            rib = raw["row_in_batch"]
            if not isinstance(ts_s, str) or not isinstance(bid_s, str):
                return None
            return cls(
                ingest_ts=datetime.fromisoformat(ts_s.replace("Z", "+00:00")),
                batch_id=UUID(bid_s),
                row_in_batch=int(rib),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_checkpoint(self) -> dict[str, str | int]:
        return {
            "ingest_ts": self.ingest_ts.isoformat(),
            "batch_id": str(self.batch_id),
            "row_in_batch": self.row_in_batch,
        }


def _export_from_clause(compiled: CompiledLeadsQuery, leads_ref: str) -> str:
    if compiled.tag_keys_select:
        return f"""
FROM (
    {compiled.tag_keys_select}
) AS tagged
INNER JOIN leads AS {leads_ref} USING (batch_id, row_in_batch)
""".strip()
    return f"FROM leads AS {leads_ref}"


def _keyset_sql(cursor: ExportCursor | None, leads_ref: str) -> str:
    if cursor is None:
        return ""
    return f"""
AND (
    {leads_ref}.ingest_ts < {{cursor_ts:DateTime}}
    OR (
        {leads_ref}.ingest_ts = {{cursor_ts:DateTime}}
        AND {leads_ref}.batch_id < {{cursor_bid:UUID}}
    )
    OR (
        {leads_ref}.ingest_ts = {{cursor_ts:DateTime}}
        AND {leads_ref}.batch_id = {{cursor_bid:UUID}}
        AND {leads_ref}.row_in_batch < {{cursor_rib:UInt32}}
    )
)"""


def leads_export_batch_sql(
    compiled: CompiledLeadsQuery,
    *,
    limit: int,
    cursor: ExportCursor | None = None,
) -> str:
    leads_ref = "l"
    cols = ", ".join(f"{leads_ref}.{c}" for c in EXPORT_LEAD_COLUMNS)
    return f"""
SELECT {cols}
{_export_from_clause(compiled, leads_ref)}
WHERE {compiled.leads_where}
{_keyset_sql(cursor, leads_ref)}
ORDER BY {leads_ref}.ingest_ts DESC, {leads_ref}.batch_id DESC, {leads_ref}.row_in_batch DESC
LIMIT {int(limit)}
""".strip()


def leads_export_s3_insert_sql(
    compiled: CompiledLeadsQuery,
    *,
    s3_url: str,
    access_key: str,
    secret_key: str,
    ch_format: str,
    row_cap: int,
) -> str:
    """INSERT INTO FUNCTION s3(...) SELECT ... — single-shot export on the ClickHouse server."""
    leads_ref = "l"
    cols = ", ".join(f"{leads_ref}.{c}" for c in EXPORT_LEAD_COLUMNS)
    url_lit = _ch_sql_string(s3_url)
    key_lit = _ch_sql_string(access_key)
    secret_lit = _ch_sql_string(secret_key)
    fmt_lit = _ch_sql_string(ch_format)
    return f"""
INSERT INTO FUNCTION s3({url_lit}, {key_lit}, {secret_lit}, {fmt_lit})
SELECT {cols}
{_export_from_clause(compiled, leads_ref)}
WHERE {compiled.leads_where}
ORDER BY {leads_ref}.ingest_ts DESC, {leads_ref}.batch_id DESC, {leads_ref}.row_in_batch DESC
LIMIT {int(row_cap)}
""".strip()


def export_ch_format(export_format: str) -> str:
    if export_format == "jsonl":
        return "JSONEachRow"
    if export_format == "csv":
        return "CSVWithNames"
    raise ValueError(f"unsupported export format: {export_format!r}")


def stream_ch_format(export_format: str, *, include_header: bool) -> str:
    if export_format == "jsonl":
        return "JSONEachRow"
    return "CSVWithNames" if include_header else "CSV"


def _ch_sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def export_object_key(job_id: UUID, export_format: str) -> str:
    ext = "csv" if export_format == "csv" else "jsonl"
    return f"exports/{job_id}/result.{ext}"


def export_s3_url(endpoint_url: str, bucket: str, key: str) -> str:
    base = endpoint_url.rstrip("/")
    return f"{base}/{bucket}/{key}"
