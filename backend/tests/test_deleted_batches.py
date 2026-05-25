from __future__ import annotations

import unittest
from typing import Any, cast
from uuid import uuid4

from foxengine.services.deleted_batches import deleted_batch_sql_clause


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)


class FakeSession:
    def __init__(self, ids):
        self._ids = ids

    async def execute(self, _stmt):
        return _ExecuteResult(self._ids)


class DeletedBatchSqlClauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_when_no_deleted_batches(self):
        clause, params = await deleted_batch_sql_clause(cast(Any, FakeSession([])))
        self.assertIn("batch_visibility", clause)
        self.assertIn("argMax(visible, version) = 0", clause)
        self.assertEqual(params, {})

    async def test_not_in_clause_for_deleted_ids(self):
        bid = uuid4()
        clause, params = await deleted_batch_sql_clause(cast(Any, FakeSession([bid])))
        self.assertIn("batch_id NOT IN", clause)
        self.assertIn("batch_visibility", clause)
        self.assertEqual(params["bd_0"], str(bid))
