from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException

from foxengine.db.models import Batch
from foxengine.routes import batch_delete_preview, delete_batch, list_batches


def _request():
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


def _principal(*roles: str, user_id=None):
    return SimpleNamespace(
        user_id=user_id or uuid4(),
        username="admin",
        roles=list(roles),
        api_key_id=None,
    )


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, *, execute_rows=None, scalar_row=None):
        self.execute_rows = execute_rows or []
        self.scalar_row = scalar_row

    async def execute(self, stmt):
        return _ExecuteResult(self.execute_rows)

    async def scalar(self, stmt):
        return self.scalar_row

    async def flush(self):
        pass

    async def commit(self):
        pass


class BatchDeleteRoutesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import foxengine.routes as routes_module

        self._routes_module = cast(Any, routes_module)
        self._orig_schedule_audit = routes_module.schedule_audit
        self._orig_get_ch = routes_module.get_ch_client
        self._orig_tag_names = routes_module._tag_names_for_batch
        self._orig_schedule_purge = routes_module.schedule_batch_purge
        self._orig_purge_defer = routes_module.foxengine_purge_batch.defer_async
        self.deferred_job_ids: list[str] = []
        setattr(self._routes_module, "schedule_audit", lambda **_: None)
        setattr(self._routes_module, "_tag_names_for_batch", self._fake_tag_names)
        setattr(self._routes_module, "schedule_batch_purge", self._fake_schedule_purge)
        setattr(
            self._routes_module.foxengine_purge_batch,
            "defer_async",
            self._fake_defer_async,
        )

        class _Ch:
            async def query(self, _sql, *, parameters=None):
                return SimpleNamespace(first_row=[0])

        async def _get_ch():
            return _Ch()

        setattr(self._routes_module, "get_ch_client", _get_ch)

    def tearDown(self) -> None:
        setattr(self._routes_module, "schedule_audit", self._orig_schedule_audit)
        setattr(self._routes_module, "get_ch_client", self._orig_get_ch)
        setattr(self._routes_module, "_tag_names_for_batch", self._orig_tag_names)
        setattr(self._routes_module, "schedule_batch_purge", self._orig_schedule_purge)
        setattr(
            self._routes_module.foxengine_purge_batch,
            "defer_async",
            self._orig_purge_defer,
        )

    async def _fake_tag_names(self, _session, _batch_id):
        return ["tag-a"]

    async def _fake_schedule_purge(self, *_args, **_kwargs):
        return "job-1"

    async def _fake_defer_async(self, *, job_id: str):
        self.deferred_job_ids.append(job_id)

    def _batch(self, *, deleted: bool = False) -> Batch:
        return Batch(
            id=uuid4(),
            name="test-batch",
            source_filename="leads.csv",
            source_sha256="abc",
            accepted_rows=10,
            rejected_rows=1,
            duplicate_rows=0,
            ingest_ts=datetime.now(UTC),
            deleted_at=datetime.now(UTC) if deleted else None,
        )

    async def test_list_batches_include_deleted_requires_admin(self):
        session = FakeSession()
        with self.assertRaises(HTTPException) as ctx:
            await list_batches(
                cast(Any, session),
                cast(Any, _principal("viewer")),
                include_deleted=True,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_delete_batch_not_found(self):
        session = FakeSession(execute_rows=[])
        with self.assertRaises(HTTPException) as ctx:
            await delete_batch(
                _request(),
                uuid4(),
                cast(Any, session),
                cast(Any, _principal("admin")),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_delete_batch_queues_purge(self):
        batch = self._batch()
        session = FakeSession(execute_rows=[batch])
        out = await delete_batch(
            _request(),
            batch.id,
            cast(Any, session),
            cast(Any, _principal("admin")),
        )
        self.assertEqual(out.status, "ok")
        self.assertEqual(out.job_id, "job-1")
        self.assertEqual(self.deferred_job_ids, ["job-1"])

    async def test_delete_preview_returns_counts(self):
        batch = self._batch()

        class _ChWithRows:
            async def query(self, sql, *, parameters=None):
                if "leads" in sql:
                    return SimpleNamespace(first_row=[5])
                return SimpleNamespace(first_row=[0])

        async def _get_ch():
            return _ChWithRows()

        setattr(self._routes_module, "get_ch_client", _get_ch)
        session = FakeSession(execute_rows=[batch])
        preview = await batch_delete_preview(
            batch.id,
            cast(Any, session),
            cast(Any, _principal("admin")),
        )
        self.assertEqual(preview.clickhouse_rows["leads"], 5)
        self.assertEqual(preview.tag_names, ["tag-a"])
