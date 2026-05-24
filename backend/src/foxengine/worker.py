"""Procrastinate worker: registers tasks from foxengine.tasks."""

import asyncio
import logging

import foxengine.tasks  # noqa: F401 -- register procrastinate tasks
from foxengine.services.job_recovery import run_worker_recovery
from foxengine.tasks import pg_app

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def run_worker() -> None:
    async def main() -> None:
        async with pg_app.open_async():
            await run_worker_recovery()
            await pg_app.run_worker_async()

    asyncio.run(main())
