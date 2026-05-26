from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from foxengine.services.ingest_rows import (
    CH_FINGERPRINT_INSERT_COLUMNS,
    CH_IDENTITY_INSERT_COLUMNS,
    CH_INSERT_COLUMNS,
    CH_TAG_INSERT_COLUMNS,
    materialize_identity_rows,
    materialize_tag_rows,
)


@dataclass(slots=True)
class PreparedLeadInserts:
    ch_rows: list[list[Any]]
    identity_rows: list[list[Any]]
    tag_rows: list[list[Any]]
    fingerprint_rows: list[list[Any]]
    duplicate_rows: int
    next_row_in_batch: int


async def fetch_existing_row_hashes(ch: Any, row_hashes: list[str]) -> set[str]:
    unique = list(dict.fromkeys(h for h in row_hashes if h))
    if not unique:
        return set()

    existing: set[str] = set()
    chunk_size = 5_000
    for i in range(0, len(unique), chunk_size):
        chunk = unique[i : i + chunk_size]
        qr = await ch.query(
            "SELECT row_hash FROM lead_fingerprints "
            "WHERE row_hash IN {row_hashes:Array(String)}",
            parameters={"row_hashes": chunk},
        )
        existing.update(str(row[0]) for row in qr.result_rows)
    return existing


async def prepare_new_lead_inserts(
    ch: Any,
    pending_rows: list[tuple[list[Any], str]],
    *,
    batch_id: UUID,
    next_row_in_batch: int,
    tag_id_strs: list[str],
    assigned_at: datetime,
    tag_source: str,
) -> PreparedLeadInserts:
    existing = await fetch_existing_row_hashes(ch, [row_hash for _, row_hash in pending_rows])

    ch_rows: list[list[Any]] = []
    identity_rows: list[list[Any]] = []
    tag_rows: list[list[Any]] = []
    fingerprint_rows: list[list[Any]] = []
    duplicate_rows = 0

    for ch_row, row_hash in pending_rows:
        if row_hash in existing:
            duplicate_rows += 1
            continue

        next_row_in_batch += 1
        ch_row[1] = next_row_in_batch
        ch_rows.append(ch_row)
        identity_rows.extend(materialize_identity_rows(ch_row))
        tag_rows.extend(
            materialize_tag_rows(
                tag_id_strs,
                ch_row,
                assigned_at=assigned_at,
                source=tag_source,
            )
        )
        fingerprint_rows.append(
            [row_hash, str(batch_id), next_row_in_batch, ch_row[2]]
        )

    return PreparedLeadInserts(
        ch_rows=ch_rows,
        identity_rows=identity_rows,
        tag_rows=tag_rows,
        fingerprint_rows=fingerprint_rows,
        duplicate_rows=duplicate_rows,
        next_row_in_batch=next_row_in_batch,
    )


async def insert_prepared_leads(ch: Any, prepared: PreparedLeadInserts) -> None:
    if not prepared.ch_rows:
        return

    leads = ch.insert("leads", prepared.ch_rows, column_names=CH_INSERT_COLUMNS)
    identities = ch.insert(
        "lead_identities",
        prepared.identity_rows,
        column_names=CH_IDENTITY_INSERT_COLUMNS,
    )
    if prepared.tag_rows:
        tags = ch.insert(
            "lead_tags",
            prepared.tag_rows,
            column_names=CH_TAG_INSERT_COLUMNS,
        )
        await asyncio.gather(leads, identities, tags)
    else:
        await asyncio.gather(leads, identities)

    await ch.insert(
        "lead_fingerprints",
        prepared.fingerprint_rows,
        column_names=CH_FINGERPRINT_INSERT_COLUMNS,
    )
