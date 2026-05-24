"""Resume helpers for file ingest: rebuild dedup state from ClickHouse."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from foxengine.services.identity import row_dedup_key

log = logging.getLogger(__name__)

_DEDUP_SELECT = """
SELECT
    phone_norm,
    email_norm,
    username,
    id_card,
    full_name,
    first_name,
    last_name,
    dob,
    gender,
    address,
    city,
    country,
    zip,
    ip,
    user_agent,
    isp,
    phone_carrier,
    password,
    password_hash,
    last_seen,
    extras
FROM leads
WHERE batch_id = {batch_id:UUID}
"""

_DEDUP_PROGRESS_EVERY = 100_000


def checkpoint_int(ck: dict[str, Any], key: str, default: int = 0) -> int:
    raw = ck.get(key)
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw)
    return default


def ingest_needs_resume(ck: dict[str, Any]) -> bool:
    return (
        checkpoint_int(ck, "rib") > 0
        or checkpoint_int(ck, "resume_line_index", default=-1) >= 0
        or checkpoint_int(ck, "resume_csv_row", default=-1) >= 0
    )


def lead_dict_from_ch_row(row: dict[str, Any]) -> dict[str, Any]:
    extras = row.get("extras") or {}
    if not isinstance(extras, dict):
        extras = dict(extras) if extras else {}
    dob = row.get("dob")
    last_seen = row.get("last_seen")

    def _str_field(key: str) -> str:
        v = row.get(key)
        if v is None:
            return ""
        return str(v)

    return {
        "phone_norm": _str_field("phone_norm"),
        "email_norm": _str_field("email_norm"),
        "username": _str_field("username"),
        "id_card": _str_field("id_card"),
        "full_name": _str_field("full_name"),
        "first_name": _str_field("first_name"),
        "last_name": _str_field("last_name"),
        "dob": str(dob) if dob is not None else None,
        "gender": _str_field("gender"),
        "address": _str_field("address"),
        "city": _str_field("city"),
        "country": _str_field("country"),
        "zip": _str_field("zip"),
        "ip": _str_field("ip"),
        "user_agent": _str_field("user_agent"),
        "isp": _str_field("isp"),
        "phone_carrier": _str_field("phone_carrier"),
        "password": _str_field("password"),
        "password_hash": _str_field("password_hash"),
        "last_seen": str(last_seen) if last_seen is not None else None,
        "extras": {str(k): str(v) for k, v in extras.items()},
    }


async def load_seen_hashes_from_batch(
    ch: Any,
    batch_id: UUID,
    *,
    on_progress: Callable[[int], Awaitable[None]] | None = None,
) -> set[str]:
    log.info("loading dedup keys from clickhouse for batch %s", batch_id)
    qr = await ch.query(_DEDUP_SELECT, parameters={"batch_id": str(batch_id)})
    seen: set[str] = set()
    count = 0
    for row in qr.named_results():
        seen.add(row_dedup_key(lead_dict_from_ch_row(dict(row))))
        count += 1
        if on_progress is not None and count % _DEDUP_PROGRESS_EVERY == 0:
            await on_progress(count)
    if on_progress is not None and count % _DEDUP_PROGRESS_EVERY != 0:
        await on_progress(count)
    log.info("loaded %s dedup keys for batch %s", count, batch_id)
    return seen


async def max_row_in_batch(ch: Any, batch_id: UUID) -> int:
    qr = await ch.query(
        "SELECT max(row_in_batch) AS m FROM leads WHERE batch_id = {batch_id:UUID}",
        parameters={"batch_id": str(batch_id)},
    )
    rows = list(qr.named_results())
    if not rows:
        return 0
    m = rows[0].get("m")
    if m is None:
        return 0
    return int(m)
