"""Canonical DSL predicate fields and ingest column names (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DslFieldSpec:
    name: str
    detail: str


# CSV / JSONL header mapping targets (unmapped columns land in ClickHouse `extras`).
INGEST_CANONICAL_FIELDS: tuple[str, ...] = (
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

TAG_FIELDS: tuple[str, ...] = ("tag", "tag.family", "tag.breach_date")

DSL_FIELD_SPECS: tuple[DslFieldSpec, ...] = (
    DslFieldSpec("phone", "Phone identity; wildcards: *7434, +34*"),
    DslFieldSpec("email", "Email identity; e.g. john@outlook.com or *@domain*"),
    DslFieldSpec("username", "Username identity; e.g. john*"),
    DslFieldSpec("id_card", "National ID / document number"),
    DslFieldSpec("full_name", "Full name on the lead row"),
    DslFieldSpec("first_name", "Given name"),
    DslFieldSpec("last_name", "Family name"),
    DslFieldSpec("dob", "Date of birth"),
    DslFieldSpec("gender", "Gender"),
    DslFieldSpec("address", "Street address"),
    DslFieldSpec("city", "City"),
    DslFieldSpec("country", "Country"),
    DslFieldSpec("zip", "Postal code"),
    DslFieldSpec("ip", "IP address"),
    DslFieldSpec("user_agent", "Browser user agent"),
    DslFieldSpec("isp", "ISP name"),
    DslFieldSpec("phone_carrier", "Mobile carrier"),
    DslFieldSpec("password", "Plain password (if stored)"),
    DslFieldSpec("password_hash", "Password hash"),
    DslFieldSpec("last_seen", "Last seen timestamp"),
    DslFieldSpec(
        "extras",
        "Search unmapped CSV / JSON extras values; wildcards: *needle*, prefix*",
    ),
    DslFieldSpec("email.domain", "Email domain only, e.g. outlook.com"),
    DslFieldSpec("email.local", "Local part before @"),
    DslFieldSpec("phone.country", "Country calling code prefix, e.g. +34"),
    DslFieldSpec("tag", "Filter by tag name (no wildcards)"),
    DslFieldSpec("tag.family", "Filter by tag family code"),
    DslFieldSpec("tag.breach_date", "Breach year YYYY or date YYYY-MM-DD"),
)


def dsl_query_field_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in DSL_FIELD_SPECS)
