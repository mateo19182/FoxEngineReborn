from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.config import get_settings
from foxengine.db.models import Batch, IngestRejection, Tag
from foxengine.deps import Principal
from foxengine.services.deleted_batches import lightweight_delete_batch_rows
from foxengine.services.ingest_rows import (
    RowOutcome,
    ingest_timestamp,
    materialize_lead_row,
)
from foxengine.services.lead_fingerprints import (
    insert_prepared_leads,
    prepare_new_lead_inserts,
)


async def resolve_tag_ids(
    session: AsyncSession, names: list[str], created_by: UUID
) -> list[UUID]:
    ids: list[UUID] = []
    for name in names:
        n = name.strip()
        if not n:
            continue
        r = await session.execute(select(Tag).where(Tag.name == n, Tag.deleted_at.is_(None)))
        existing = r.scalar_one_or_none()
        if existing:
            ids.append(existing.id)
            continue
        tag = Tag(name=n, created_by=created_by)
        session.add(tag)
        await session.flush()
        ids.append(tag.id)
    return ids


async def ingest_sync(
    session: AsyncSession,
    ch: Any,
    principal: Principal,
    leads: list[dict[str, Any]],
    tag_names: list[str],
    batch_name: str | None,
) -> dict[str, Any]:
    s = get_settings()
    if len(leads) > s.max_index_rows_sync:
        raise ValueError(f"too many rows in one request (max {s.max_index_rows_sync})")

    tag_ids = await resolve_tag_ids(session, tag_names, principal.user_id)
    tag_id_strs = [str(u) for u in tag_ids]

    batch = Batch(name=batch_name, ingested_by=principal.user_id)
    session.add(batch)
    await session.flush()
    await lightweight_delete_batch_rows(ch, batch.id)

    seen_hashes: set[str] = set()
    rejected = 0
    dup = 0
    pending_rows: list[tuple[list[Any], str]] = []
    row_no = 0
    ts = ingest_timestamp()

    for raw in leads:
        row_no += 1
        outcome, ch_row, row_hash, reason, raw_line = materialize_lead_row(
            raw,
            batch_id=batch.id,
            row_in_batch=0,
            ingest_ts=ts,
            seen_hashes=seen_hashes,
            default_phone_region=None,
        )
        if outcome is RowOutcome.rejected:
            session.add(
                IngestRejection(
                    batch_id=batch.id,
                    line_no=row_no,
                    reason=reason or "rejected",
                    raw_line=(raw_line or str(raw))[:8000],
                )
            )
            rejected += 1
            continue
        if outcome is RowOutcome.duplicate:
            dup += 1
            continue
        assert ch_row is not None
        assert row_hash is not None
        pending_rows.append((ch_row, row_hash))

    prepared = await prepare_new_lead_inserts(
        ch,
        pending_rows,
        batch_id=batch.id,
        next_row_in_batch=0,
        tag_id_strs=tag_id_strs,
        assigned_at=ts,
        tag_source="ingest_sync",
    )
    await insert_prepared_leads(ch, prepared)
    accepted = len(prepared.ch_rows)
    dup += prepared.duplicate_rows

    batch.accepted_rows = accepted
    batch.rejected_rows = rejected
    batch.duplicate_rows = dup
    await session.commit()

    return {
        "batch_id": str(batch.id),
        "accepted_rows": accepted,
        "rejected_rows": rejected,
        "duplicate_rows": dup,
    }
