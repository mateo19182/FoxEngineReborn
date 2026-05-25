from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Tag, TagFamily
from foxengine.dsl.ast_nodes import And, Expr, Not, Or, Pred

TAG_FIELDS = frozenset({"tag", "tag.family", "tag.breach_date"})


class TagResolveError(Exception):
    """Tag predicate cannot be resolved against Postgres metadata."""


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


def walk_positive_tag_preds(expr: Expr, *, negated: bool = False) -> list[Pred]:
    """Tag predicates that require a match (not under NOT)."""
    if isinstance(expr, Pred):
        if negated or expr.field not in TAG_FIELDS:
            return []
        return [expr]
    if isinstance(expr, Not):
        return walk_positive_tag_preds(expr.inner, negated=not negated)
    if isinstance(expr, And | Or):
        out: list[Pred] = []
        for part in expr.parts:
            out.extend(walk_positive_tag_preds(part, negated=negated))
        return out
    return []


async def validate_tag_references(
    session: AsyncSession,
    expr: Expr,
    tag_uuid_lists: dict[tuple[str, str], list[UUID]],
) -> None:
    """Reject unknown tag names / families before ClickHouse (Postgres is source of truth)."""
    family_codes: set[str] = set()
    for pred in walk_positive_tag_preds(expr):
        if pred.field == "tag":
            if not tag_uuid_lists.get((pred.field, pred.value)):
                raise TagResolveError(f"tag does not exist: {pred.value}")
        elif pred.field == "tag.family":
            family_codes.add(pred.value.strip().upper())

    if not family_codes:
        return

    rows = (
        await session.execute(
            select(func.upper(TagFamily.code)).where(
                func.upper(TagFamily.code).in_(family_codes)
            )
        )
    ).scalars().all()
    found = set(rows)
    for code in family_codes:
        if code not in found:
            raise TagResolveError(f"tag family does not exist: {code}")


async def resolve_tag_predicates(
    session: AsyncSession, preds: list[Pred]
) -> dict[tuple[str, str], list[UUID]]:
    """Map (field, raw_value) -> matching tag UUIDs (non-deleted)."""
    out: dict[tuple[str, str], list[UUID]] = {}
    for p in preds:
        if p.field not in ("tag", "tag.family", "tag.breach_date"):
            continue
        key = (p.field, p.value)
        if key in out:
            continue
        if p.field == "tag":
            stmt = select(Tag.id).where(
                func.lower(Tag.name) == func.lower(p.value),
                Tag.deleted_at.is_(None),
            )
        elif p.field == "tag.family":
            stmt = select(Tag.id).where(
                Tag.family_id == TagFamily.id,
                Tag.deleted_at.is_(None),
                func.upper(TagFamily.code) == p.value.strip().upper(),
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
