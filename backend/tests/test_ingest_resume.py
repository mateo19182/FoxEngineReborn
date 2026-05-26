"""Tests for ingest resume helpers."""

from foxengine.services.identity import row_dedup_key
from foxengine.services.ingest_resume import (
    checkpoint_int,
    ingest_needs_resume,
    lead_dict_from_ch_row,
)


def test_checkpoint_int_parses_values() -> None:
    assert checkpoint_int({"rib": 10}, "rib") == 10
    assert checkpoint_int({"rib": "42"}, "rib") == 42
    assert checkpoint_int({}, "rib") == 0
    assert checkpoint_int({"rib": True}, "rib") == 0


def test_ingest_needs_resume() -> None:
    assert not ingest_needs_resume({})
    assert ingest_needs_resume({"rib": 1})
    assert ingest_needs_resume({"resume_line_index": 0})


def test_lead_dict_from_ch_row_matches_row_dedup_key() -> None:
    built = {
        "phone": "+15551234567",
        "email": "a@b.com",
        "username": "alice",
        "id_card": "",
        "full_name": "Alice",
        "first_name": "",
        "last_name": "",
        "dob": None,
        "gender": "",
        "address": "",
        "city": "",
        "country": "",
        "zip": "",
        "ip": "",
        "user_agent": "",
        "isp": "",
        "phone_carrier": "",
        "password": "secret",
        "password_hash": "",
        "last_seen": None,
        "extras": {"k": "v"},
    }
    key_from_built = row_dedup_key(built)
    ch_row = {
        **built,
        "extras": {"k": "v"},
    }
    key_from_ch = row_dedup_key(lead_dict_from_ch_row(ch_row))
    assert key_from_built == key_from_ch
