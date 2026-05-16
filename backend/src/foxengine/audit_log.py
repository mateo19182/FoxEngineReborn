import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foxengine.db.models import AuditLog

log = logging.getLogger(__name__)


class AuditBatcher:
    def __init__(self, max_queue: int = 8000, flush_interval: float = 0.2, batch_size: int = 64):
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue)
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None
        self._factory: async_sessionmaker[AsyncSession] | None = None

    def configure(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="audit-batcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._drain_all()

    def emit(self, row: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            log.warning("audit queue full; dropping event %s", row.get("action"))

    async def _run(self) -> None:
        assert self._factory is not None
        batch: list[dict[str, Any]] = []
        while True:
            try:
                if batch:
                    row = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval)
                    batch.append(row)
                else:
                    batch.append(await self._queue.get())
            except TimeoutError:
                pass
            while len(batch) < self._batch_size and not self._queue.empty():
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if batch:
                await self._flush(batch)
                batch.clear()

    async def _drain_all(self) -> None:
        batch: list[dict[str, Any]] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._flush(batch)

    async def _flush(self, rows: list[dict[str, Any]]) -> None:
        assert self._factory is not None
        async with self._factory() as session:
            await session.execute(insert(AuditLog), rows)
            await session.commit()


audit_batcher = AuditBatcher()


def schedule_audit(
    *,
    actor_id: UUID | None,
    actor_kind: str,
    api_key_id: UUID | None,
    action: str,
    target_kind: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    audit_batcher.emit(
        {
            "actor_id": actor_id,
            "actor_kind": actor_kind,
            "api_key_id": api_key_id,
            "action": action,
            "target_kind": target_kind,
            "target_id": target_id,
            "details": details or {},
            "ip": ip,
            "user_agent": user_agent,
        }
    )
