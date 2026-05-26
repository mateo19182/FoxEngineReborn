"""Procrastinate worker: registers tasks from foxengine.tasks."""

import asyncio
import logging

import foxengine.tasks  # noqa: F401 -- register procrastinate tasks
from foxengine.config import get_settings
from foxengine.services.job_recovery import run_worker_recovery
from foxengine.tasks import pg_app

logging.basicConfig(level=logging.INFO)


def run_worker() -> None:
    concurrency = get_settings().worker_concurrency

    async def main() -> None:
        async with pg_app.open_async():
            await run_worker_recovery()
            await pg_app.run_worker_async(concurrency=concurrency)

    asyncio.run(main())
