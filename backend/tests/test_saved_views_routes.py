from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from foxengine import schemas
from foxengine.db.models import SavedView
from foxengine.routes import (
    create_saved_view,
    delete_saved_view,
    list_saved_views,
    patch_saved_view,
)


def _request():
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


def _principal(user_id):
    return SimpleNamespace(
        user_id=user_id,
        username="viewer",
        roles=["viewer"],
        api_key_id=None,
    )


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
    def __init__(self, *, execute_rows=None, scalar_row=None, fail_commit=False):
        self.execute_rows = execute_rows or []
        self.scalar_row = scalar_row
        self.fail_commit = fail_commit
        self.last_execute_stmt = None
        self.last_scalar_stmt = None
        self.added = []
        self.deleted = []
        self.rolled_back = False

    async def execute(self, stmt):
        self.last_execute_stmt = stmt
        return _ExecuteResult(self.execute_rows)

    async def scalar(self, stmt):
        self.last_scalar_stmt = stmt
        return self.scalar_row

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        if self.fail_commit:
            raise IntegrityError("duplicate", None, Exception("duplicate"))

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        now = datetime.now(UTC)
        if getattr(row, "created_at", None) is None:
            row.created_at = now
        if getattr(row, "updated_at", None) is None:
            row.updated_at = now

    async def delete(self, row):
        self.deleted.append(row)


class SavedViewsRoutesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import foxengine.routes as routes_module

        self._routes_module = cast(Any, routes_module)
        self._orig_schedule_audit = routes_module.schedule_audit
        setattr(self._routes_module, "schedule_audit", lambda **_: None)

    def tearDown(self) -> None:
        setattr(self._routes_module, "schedule_audit", self._orig_schedule_audit)

    async def test_saved_views_list_scoped_to_current_user(self):
        user_id = uuid4()
        row = SavedView(
            id=uuid4(),
            user_id=user_id,
            name="recent leaks",
            dsl="email:*@example.com",
            view="rows",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session = FakeSession(execute_rows=[row])

        out = await list_saved_views(cast(Any, session), cast(Any, _principal(user_id)))

        self.assertEqual([item.name for item in out], ["recent leaks"])
        self.assertEqual(out[0].view, "rows")
        self.assertIsNotNone(session.last_execute_stmt)
        stmt = cast(Any, session.last_execute_stmt)
        compiled = stmt.compile()
        self.assertIn(user_id, compiled.params.values())

    async def test_saved_views_create_trim_name_and_conflict(self):
        user_id = uuid4()
        body = schemas.SavedViewCreateRequest(
            name="  triage  ",
            dsl="email:*@x.com",
            view="related",
        )

        session_ok = FakeSession()
        out = await create_saved_view(
            cast(Any, _request()),
            body,
            cast(Any, session_ok),
            cast(Any, _principal(user_id)),
        )
        self.assertEqual(out.name, "triage")
        self.assertEqual(out.view, "related")
        self.assertEqual(session_ok.added[0].user_id, user_id)

        session_conflict = FakeSession(fail_commit=True)
        with self.assertRaises(HTTPException) as exc:
            await create_saved_view(
                cast(Any, _request()),
                body,
                cast(Any, session_conflict),
                cast(Any, _principal(user_id)),
            )
        self.assertEqual(exc.exception.status_code, 409)
        self.assertTrue(session_conflict.rolled_back)

    async def test_saved_views_patch_and_delete_owner_scoped(self):
        user_id = uuid4()
        row = SavedView(
            id=uuid4(),
            user_id=user_id,
            name="mine",
            dsl="email:*@example.com",
            view="rows",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        patch_session = FakeSession(scalar_row=row)
        patch_body = schemas.SavedViewPatchRequest(name="renamed", dsl="phone:*", view="related")
        out = await patch_saved_view(
            cast(Any, _request()),
            row.id,
            patch_body,
            cast(Any, patch_session),
            cast(Any, _principal(user_id)),
        )
        self.assertEqual(out.name, "renamed")
        self.assertEqual(out.dsl, "phone:*")
        self.assertEqual(out.view, "related")
        self.assertIsNotNone(patch_session.last_scalar_stmt)
        stmt = cast(Any, patch_session.last_scalar_stmt)
        self.assertIn(user_id, stmt.compile().params.values())

        delete_session = FakeSession(scalar_row=row)
        deleted = await delete_saved_view(
            cast(Any, _request()),
            row.id,
            cast(Any, delete_session),
            cast(Any, _principal(user_id)),
        )
        self.assertEqual(deleted, {"status": "ok"})
        self.assertEqual(delete_session.deleted, [row])

    async def test_saved_views_patch_not_found(self):
        body = schemas.SavedViewPatchRequest(name="x")
        session = FakeSession(scalar_row=None)
        with self.assertRaises(HTTPException) as exc:
            await patch_saved_view(
                cast(Any, _request()),
                uuid4(),
                body,
                cast(Any, session),
                cast(Any, _principal(uuid4())),
            )
        self.assertEqual(exc.exception.status_code, 404)
