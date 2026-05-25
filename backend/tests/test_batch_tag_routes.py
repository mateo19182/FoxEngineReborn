from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException

from foxengine.db.models import Batch
from foxengine.routes import apply_batch_tags
from foxengine.schemas import BatchTagRequest


def _request():
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


def _principal(*roles: str, user_id=None):
    return SimpleNamespace(
        user_id=user_id or uuid4(),
        username="op",
        roles=list(roles),
        api_key_id=None,
    )


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, *, batch: Batch | None, scalars: list[Any] | None = None):
        self.batch = batch
        self.scalars = scalars or []
        self._scalar_idx = 0
        self.added: list[Any] = []

    async def execute(self, stmt):
        return _ExecuteResult([self.batch] if self.batch else [])

    async def scalar(self, stmt):
        if self._scalar_idx < len(self.scalars):
            val = self.scalars[self._scalar_idx]
            self._scalar_idx += 1
            return val
        return None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


class BatchTagRoutesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import foxengine.routes as routes_module

        self._routes_module = cast(Any, routes_module)
        self._orig_schedule_audit = routes_module.schedule_audit
        self._orig_defer = routes_module.foxengine_batch_tag.defer_async
        self.deferred: list[str] = []
        setattr(self._routes_module, "schedule_audit", lambda **_: None)
        setattr(
            self._routes_module.foxengine_batch_tag,
            "defer_async",
            self._fake_defer,
        )

    def tearDown(self) -> None:
        setattr(self._routes_module, "schedule_audit", self._orig_schedule_audit)
        setattr(
            self._routes_module.foxengine_batch_tag,
            "defer_async",
            self._orig_defer,
        )

    async def _fake_defer(self, *, job_id: str):
        self.deferred.append(job_id)

    def _batch(self, *, owner_id, accepted: int = 10) -> Batch:
        return Batch(
            id=uuid4(),
            name="batch",
            source_filename="a.csv",
            accepted_rows=accepted,
            rejected_rows=0,
            duplicate_rows=0,
            ingest_ts=datetime.now(UTC),
            ingested_by=owner_id,
        )

    async def test_queues_job_for_owner(self) -> None:
        owner = uuid4()
        batch = self._batch(owner_id=owner)
        session = FakeSession(batch=batch)
        principal = _principal("manager", user_id=owner)

        res = await apply_batch_tags(
            _request(),
            batch.id,
            BatchTagRequest(tag_names=["alpha", "beta"]),
            session,
            principal,
        )

        self.assertEqual(len(session.added), 1)
        job = session.added[0]
        self.assertEqual(job.type, "batch_tag")
        self.assertEqual(job.checkpoint["tag_names"], ["alpha", "beta"])
        self.assertEqual(res.job_id, str(job.id))
        self.assertEqual(self.deferred, [str(job.id)])

    async def test_not_found_for_other_user(self) -> None:
        batch = self._batch(owner_id=uuid4())
        session = FakeSession(batch=batch)
        principal = _principal("manager", user_id=uuid4())

        with self.assertRaises(HTTPException) as ctx:
            await apply_batch_tags(
                _request(),
                batch.id,
                BatchTagRequest(tag_names=["x"]),
                session,
                principal,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_rejects_empty_tag_names(self) -> None:
        owner = uuid4()
        batch = self._batch(owner_id=owner)
        session = FakeSession(batch=batch)
        principal = _principal("manager", user_id=owner)

        with self.assertRaises(HTTPException) as ctx:
            await apply_batch_tags(
                _request(),
                batch.id,
                BatchTagRequest(tag_names=["  "]),
                session,
                principal,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_rejects_active_ingest(self) -> None:
        owner = uuid4()
        batch = self._batch(owner_id=owner)
        session = FakeSession(batch=batch, scalars=[uuid4()])
        principal = _principal("manager", user_id=owner)

        with self.assertRaises(HTTPException) as ctx:
            await apply_batch_tags(
                _request(),
                batch.id,
                BatchTagRequest(tag_names=["t"]),
                session,
                principal,
            )
        self.assertEqual(ctx.exception.status_code, 409)
