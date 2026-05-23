import hashlib
import json
from typing import Any

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


def normalize_email(raw: str | None) -> tuple[str, str]:
    if not raw or not str(raw).strip():
        return "", ""
    s = str(raw).strip().lower()
    return s, raw.strip()


def normalize_phone(
    raw: str | None, default_region: str | None = None
) -> tuple[str, str]:
    if not raw or not str(raw).strip():
        return "", ""
    raw_s = str(raw).strip()
    try:
        parsed = phonenumbers.parse(raw_s, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return "", raw_s
        e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        return e164, raw_s
    except NumberParseException:
        return "", raw_s


def identity_facet_tuples(
    phone_norm: str, email_norm: str, username: str, id_card: str
) -> list[tuple[str, str]]:
    """Return (identity_kind, identity_value) pairs for lead_identities indexing."""
    facets: list[tuple[str, str]] = []
    if email_norm:
        facets.append(("email", email_norm))
    if phone_norm:
        facets.append(("phone", phone_norm))
    u = (username or "").strip()
    if u:
        facets.append(("username", u.lower()))
    c = (id_card or "").strip()
    if c:
        facets.append(("id_card", c))
    return facets


def row_dedup_key(row: dict[str, Any]) -> str:
    keys = (
        "phone_norm",
        "email_norm",
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
    base = {k: row.get(k) for k in keys}
    extras = row.get("extras") or {}
    base["extras"] = json.dumps(extras, sort_keys=True)
    blob = json.dumps(base, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def has_any_identity(
    phone_norm: str, email_norm: str, username: str, id_card: str
) -> bool:
    return bool(phone_norm or email_norm or (username or "").strip() or (id_card or "").strip())
