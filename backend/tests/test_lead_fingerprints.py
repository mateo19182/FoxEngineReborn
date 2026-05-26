from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any
from uuid import uuid4

from foxengine.services.lead_fingerprints import prepare_new_lead_inserts


class _QueryResult:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self.result_rows = rows


class _FakeClickHouse:
    def __init__(self, existing_hashes: set[str]) -> None:
        self.existing_hashes = existing_hashes

    async def query(
        self,
        _sql: str,
        *,
        parameters: dict[str, Any],
    ) -> _QueryResult:
        requested = set(parameters["row_hashes"])
        return _QueryResult([(h,) for h in sorted(requested & self.existing_hashes)])


class LeadFingerprintTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_new_lead_inserts_skips_existing_hashes(self) -> None:
        batch_id = uuid4()
        ts = datetime(2026, 1, 1, 0, 0, 0)
        row_existing = [
            str(batch_id),
            0,
            ts,
            "",
            "",
            "dupe@example.com",
            "dupe@example.com",
            "",
            "",
        ] + [""] * 16 + [{}]
        row_new = [
            str(batch_id),
            0,
            ts,
            "",
            "",
            "new@example.com",
            "new@example.com",
            "",
            "",
        ] + [""] * 16 + [{}]

        prepared = await prepare_new_lead_inserts(
            _FakeClickHouse({"existing-hash"}),
            [(row_existing, "existing-hash"), (row_new, "new-hash")],
            batch_id=batch_id,
            next_row_in_batch=7,
            tag_id_strs=[],
            assigned_at=ts,
            tag_source="test",
        )

        self.assertEqual(prepared.duplicate_rows, 1)
        self.assertEqual(prepared.next_row_in_batch, 8)
        self.assertEqual(len(prepared.ch_rows), 1)
        self.assertEqual(prepared.ch_rows[0][1], 8)
        self.assertEqual(prepared.fingerprint_rows[0][0], "new-hash")


if __name__ == "__main__":
    unittest.main()
