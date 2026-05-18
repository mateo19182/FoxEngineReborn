"""Natural language → DSL via local llama.cpp; output validated with the real parser."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Tag, TagFamily
from foxengine.dsl.parser import parse_dsl
from foxengine.services.llm_client import LlmError, LlmUnavailableError, chat_completion

CANONICAL_FIELDS = (
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
)

TAG_FIELDS = ("tag", "tag.family", "tag.breach_date")

_SYSTEM_TEMPLATE = """You translate natural-language search requests into FoxEngine DSL.

Output ONLY one DSL expression on a single line. No markdown, no quotes, no explanation.

Grammar:
- Predicates: field:value (lowercase field; components use dots, e.g. email.domain:outlook.com)
- Wildcards in values: * (e.g. email:*@example.com, username:john*)
- Boolean: AND OR NOT with parentheses for grouping
- Tag filters: tag:Name, tag.family:DATA_LEAK,
  tag.breach_date:YYYY or YYYY-MM-DD (no wildcards on tags)

Lead fields (use only these): {fields}

Tag predicate fields: {tag_fields}

Known tags (use exact names for tag:...):
{tag_lines}

Examples:
- emails ending with outlook.com → email.domain:outlook.com
- phone numbers in Spain → phone.country:+34
- john usernames → username:john*
- ticketmaster leak tagged → tag:Ticketmaster-VM
"""


async def _tag_lines(session: AsyncSession) -> str:
    rows = (
        await session.execute(
            select(Tag.name, Tag.type, Tag.breach_date, TagFamily.code)
            .select_from(Tag)
            .outerjoin(TagFamily, Tag.family_id == TagFamily.id)
            .where(Tag.deleted_at.is_(None))
            .order_by(Tag.name)
            .limit(200)
        )
    ).all()
    if not rows:
        return "(none)"
    lines: list[str] = []
    for name, typ, breach, family_code in rows:
        bits = [str(name)]
        if typ:
            bits.append(f"type={typ}")
        if family_code:
            bits.append(f"family={family_code}")
        if breach:
            bits.append(f"breach_date={breach}")
        lines.append("- " + ", ".join(bits))
    return "\n".join(lines)


def build_system_prompt(tag_block: str) -> str:
    fields = ", ".join(CANONICAL_FIELDS)
    tag_fields = ", ".join(TAG_FIELDS)
    return _SYSTEM_TEMPLATE.format(
        fields=fields,
        tag_fields=tag_fields,
        tag_lines=tag_block,
    )


def extract_dsl(raw: str) -> str:
    t = raw.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()

    # Look for a line that looks like DSL (field:value pattern)
    # or take the last non-empty line if no clear DSL pattern found
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]

    # DSL pattern: field:value (field has no spaces, contains only lowercase, dots, underscores)
    dsl_pattern = re.compile(r"^[a-z_][a-z0-9_.]*:[^\s]+")

    for line in reversed(lines):  # Check from last line (after thinking)
        if dsl_pattern.match(line):
            return line.strip('"').strip("'")

    # Fallback: take last non-empty line
    if lines:
        return lines[-1].strip('"').strip("'")

    return t.strip('"').strip("'")


def _sanitize_attempted(dsl: str) -> str:
    return re.sub(r"\s+", " ", dsl).strip()[:500]


async def translate_nl_to_dsl(session: AsyncSession, nl: str) -> dict[str, str | bool | None]:
    tag_block = await _tag_lines(session)
    system = build_system_prompt(tag_block)
    try:
        raw = await chat_completion(system=system, user=nl.strip())
    except LlmUnavailableError:
        raise
    except LlmError as e:
        return {
            "ok": False,
            "dsl": None,
            "error": str(e),
            "attempted": None,
        }

    print(f"[NL_TO_DSL] RAW LLM RESPONSE: {raw!r}", flush=True)
    attempted = extract_dsl(raw)
    print(f"[NL_TO_DSL] EXTRACTED DSL: {attempted!r}", flush=True)
    if not attempted:
        return {
            "ok": False,
            "dsl": None,
            "error": "The model returned an empty DSL string.",
            "attempted": _sanitize_attempted(raw),
        }
    try:
        parse_dsl(attempted)
    except Exception as e:
        return {
            "ok": False,
            "dsl": None,
            "error": f"Translated DSL is invalid: {e}",
            "attempted": _sanitize_attempted(attempted),
        }
    return {"ok": True, "dsl": attempted, "error": None, "attempted": attempted}
