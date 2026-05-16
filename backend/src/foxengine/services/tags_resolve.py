from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Tag
from foxengine.dsl.ast_nodes import And, Expr, Not, Or, Pred


def walk_preds(expr: Expr) -> list[Pred]:
    if isinstance(expr, Pred):
        return [expr]
    if isinstance(expr, Not):
        return walk_preds(expr.inner)
    if isinstance(expr, And | Or):
        out: list[Pred] = []
        for p in expr.parts:
            out.extend(walk_preds(p))
        return out
    return []


async def resolve_tag_predicates(
    session: AsyncSession, preds: list[Pred]
) -> dict[tuple[str, str], list[UUID]]:
    """Map (field, raw_value) -> matching tag UUIDs (non-deleted)."""
    out: dict[tuple[str, str], list[UUID]] = {}
    for p in preds:
        if p.field not in ("tag", "tag.type", "tag.breach_date"):
            continue
        key = (p.field, p.value)
        if key in out:
            continue
        if p.field == "tag":
            stmt = select(Tag.id).where(
                func.lower(Tag.name) == func.lower(p.value),
                Tag.deleted_at.is_(None),
            )
        elif p.field == "tag.type":
            stmt = select(Tag.id).where(
                Tag.type == p.value,
                Tag.deleted_at.is_(None),
            )
        else:
            raw = p.value
            if len(raw) == 4 and raw.isdigit():
                y = int(raw)
                stmt = select(Tag.id).where(
                    Tag.deleted_at.is_(None),
                    func.extract("year", Tag.breach_date) == y,
                )
            else:
                try:
                    d = date.fromisoformat(raw)
                except ValueError:
                    out[key] = []
                    continue
                stmt = select(Tag.id).where(
                    Tag.deleted_at.is_(None),
                    Tag.breach_date == d,
                )
        rows = (await session.execute(stmt)).scalars().all()
        out[key] = list(rows)
    return out
