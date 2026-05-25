from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException

from foxengine.db.models import Batch
from foxengine.routes import _check_duplicate_upload_allowed


class _ExecuteResult:
    def __init__(self, row: Batch | None):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeSession:
    def __init__(self, row: Batch | None):
        self.row = row

    async def execute(self, _stmt: object):
        return _ExecuteResult(self.row)


def _batch() -> Batch:
    return Batch(
        id=uuid4(),
        name="Existing import",
        source_filename="leads.csv",
        source_sha256="abc",
        accepted_rows=1,
        rejected_rows=0,
        duplicate_rows=0,
        ingest_ts=datetime.now(UTC),
    )


class IngestDuplicateUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_upload_rejected_by_default(self) -> None:
        session = FakeSession(_batch())

        with self.assertRaises(HTTPException) as ctx:
            await _check_duplicate_upload_allowed(
                cast(Any, session),
                source_sha256="abc",
                inner_name="leads.csv",
                allow_duplicate_upload=False,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("duplicate upload", str(ctx.exception.detail))

    async def test_duplicate_upload_can_be_explicitly_allowed(self) -> None:
        batch = _batch()
        session = FakeSession(batch)

        match = await _check_duplicate_upload_allowed(
            cast(Any, session),
            source_sha256="abc",
            inner_name="leads.csv",
            allow_duplicate_upload=True,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.existing_batch_id, str(batch.id))

    async def test_new_upload_has_no_duplicate_match(self) -> None:
        session = FakeSession(None)

        match = await _check_duplicate_upload_allowed(
            cast(Any, session),
            source_sha256="def",
            inner_name="new.csv",
            allow_duplicate_upload=False,
        )

        self.assertIsNone(match)
