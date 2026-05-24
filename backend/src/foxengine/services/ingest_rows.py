"""Shared lead normalization and ClickHouse row materialization for sync and file ingest."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from foxengine.services.identity import (
    has_any_identity,
    identity_key,
    normalize_email,
    normalize_phone,
    row_dedup_key,
)

CH_INSERT_COLUMNS = [
    "batch_id",
    "row_in_batch",
    "ingest_ts",
    "identity_key",
    "phone_norm",
    "phone_raw",
    "email_norm",
    "email_raw",
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
]

CH_IDENTITY_INSERT_COLUMNS = [
    "identity_kind",
    "identity_value",
    "batch_id",
    "row_in_batch",
    "ingest_ts",
]

CH_TAG_INSERT_COLUMNS = [
    "tag_id",
    "batch_id",
    "row_in_batch",
    "ingest_ts",
    "assigned_at",
    "source",
]


KNOWN_RAW_FIELDS = frozenset(
    {
        "phone",
        "email",
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
    }
)


class RowOutcome(StrEnum):
    accepted = "accepted"
    rejected = "rejected"
    duplicate = "duplicate"


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _parse_dob(v: Any) -> str | None:
    if v is None or v == "":
        return None
    s = str(v).strip()
    return s or None


def _parse_last_seen(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v).strip() or None


def materialize_lead_row(
    raw: dict[str, Any],
    *,
    batch_id: UUID,
    row_in_batch: int,
    ingest_ts: datetime,
    seen_hashes: set[str],
    default_phone_region: str | None = None,
) -> tuple[RowOutcome, list[Any] | None, str | None, str | None]:
    """Return (outcome, ch_row, rejection_reason, raw_line_snippet).

    On duplicate, ch_row is None and raw_line_snippet is None.
    On rejection, raw_line_snippet is a short diagnostic string.
    """
    extras = raw.get("extras") or {}
    if not isinstance(extras, dict):
        extras = {}

    phone_norm, phone_raw = normalize_phone(raw.get("phone"), default_phone_region)
    email_norm, email_raw = normalize_email(raw.get("email"))
    username = _as_str(raw.get("username"))
    id_card = _as_str(raw.get("id_card"))

    if not has_any_identity(phone_norm, email_norm, username, id_card):
        return RowOutcome.rejected, None, "missing identity", str(raw)[:8000]

    ikey = identity_key(phone_norm, email_norm, username, id_card)
    built: dict[str, Any] = {
        "phone_norm": phone_norm,
        "phone_raw": phone_raw or _as_str(raw.get("phone")),
        "email_norm": email_norm,
        "email_raw": email_raw or _as_str(raw.get("email")),
        "username": username,
        "id_card": id_card,
        "full_name": _as_str(raw.get("full_name")),
        "first_name": _as_str(raw.get("first_name")),
        "last_name": _as_str(raw.get("last_name")),
        "dob": _parse_dob(raw.get("dob")),
        "gender": _as_str(raw.get("gender")),
        "address": _as_str(raw.get("address")),
        "city": _as_str(raw.get("city")),
        "country": _as_str(raw.get("country")),
        "zip": _as_str(raw.get("zip")),
        "ip": _as_str(raw.get("ip")),
        "user_agent": _as_str(raw.get("user_agent")),
        "isp": _as_str(raw.get("isp")),
        "phone_carrier": _as_str(raw.get("phone_carrier")),
        "password": _as_str(raw.get("password")),
        "password_hash": _as_str(raw.get("password_hash")),
        "last_seen": _parse_last_seen(raw.get("last_seen")),
        "extras": {str(k): str(v) for k, v in extras.items()},
    }
    dk = row_dedup_key(built)
    if dk in seen_hashes:
        return RowOutcome.duplicate, None, None, None
    seen_hashes.add(dk)

    ch_row = [
        str(batch_id),
        row_in_batch,
        ingest_ts,
        ikey,
        built["phone_norm"],
        built["phone_raw"],
        built["email_norm"],
        built["email_raw"],
        built["username"],
        built["id_card"],
        built["full_name"],
        built["first_name"],
        built["last_name"],
        built["dob"] or None,
        built["gender"],
        built["address"],
        built["city"],
        built["country"],
        built["zip"],
        built["ip"],
        built["user_agent"],
        built["isp"],
        built["phone_carrier"],
        built["password"],
        built["password_hash"],
        built["last_seen"] or None,
        built["extras"],
    ]
    return RowOutcome.accepted, ch_row, None, None


def materialize_identity_rows(lead_row: list[Any]) -> list[list[Any]]:
    batch_id = lead_row[0]
    row_in_batch = lead_row[1]
    ingest_ts = lead_row[2]
    identity_key_value = str(lead_row[3])
    phone_norm = str(lead_row[4])
    email_norm = str(lead_row[6])
    username = str(lead_row[8]).strip().lower()
    id_card = str(lead_row[9]).strip()

    identities = [
        ("identity_key", identity_key_value),
        ("phone", phone_norm),
        ("email", email_norm),
        ("username", username),
        ("id_card", id_card),
    ]
    return [
        [kind, value, batch_id, row_in_batch, ingest_ts]
        for kind, value in identities
        if value
    ]


def materialize_tag_rows(
    tag_id_strs: list[str],
    lead_row: list[Any],
    *,
    assigned_at: datetime,
    source: str,
) -> list[list[Any]]:
    batch_id = lead_row[0]
    row_in_batch = lead_row[1]
    ingest_ts = lead_row[2]
    return [
        [tag_id, batch_id, row_in_batch, ingest_ts, assigned_at, source]
        for tag_id in tag_id_strs
    ]


def csv_row_to_raw(
    header: list[str],
    cells: list[str],
    column_map: dict[str, str],
    *,
    allow_known_field_fallback: bool = True,
) -> dict[str, Any]:
    """Map a CSV data line to the ingest `raw` dict using header names.

    `column_map` maps CSV header label -> canonical field name (e.g. ``email``).
    Headers not present in ``column_map`` become extras unless fallback is enabled
    and the header (lowered) matches a known field name.
    """
    raw: dict[str, Any] = {}
    extras: dict[str, str] = {}
    for i, h in enumerate(header):
        val = cells[i] if i < len(cells) else ""
        hs = h.strip()
        key = column_map.get(h) or column_map.get(hs)
        if key is None:
            hl = hs.lower()
            if allow_known_field_fallback and hl in KNOWN_RAW_FIELDS:
                key = hl
            else:
                extras[hs] = val
                continue
        if key == "extras":
            continue
        if key in KNOWN_RAW_FIELDS and key != "extras":
            raw[key] = val
    if extras:
        raw["extras"] = extras
    return raw


def ingest_timestamp() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
