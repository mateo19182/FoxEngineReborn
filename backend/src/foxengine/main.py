from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import aioboto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from foxengine.audit_log import audit_batcher
from foxengine.bootstrap import ensure_procrastinate_schema
from foxengine.clickhouse import ensure_clickhouse_schema
from foxengine.config import get_settings
from foxengine.db.session import get_session_factory
from foxengine.routes import router
from foxengine.seed_admin import ensure_admin_from_seed
from foxengine.settings_store import read_jwt_secret

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from foxengine.tasks import pg_app

    s = get_settings()
    factory = get_session_factory()
    audit_batcher.configure(factory)
    audit_batcher.start()
    await ensure_clickhouse_schema()
    await asyncio.to_thread(ensure_procrastinate_schema)
    async with factory() as session:
        await ensure_admin_from_seed(session)
        app.state.jwt_secret = await read_jwt_secret(session)
    async with pg_app.open_async():
        session_boto = aioboto3.Session()
        try:
            async with session_boto.client(
                "s3",
                endpoint_url=s.s3_endpoint_url,
                aws_access_key_id=s.s3_access_key_id,
                aws_secret_access_key=s.s3_secret_access_key,
                region_name=s.s3_region,
            ) as c:
                for bucket in (s.s3_bucket_uploads, s.s3_bucket_exports):
                    try:
                        await c.create_bucket(Bucket=bucket)
                    except ClientError as e:
                        code = e.response.get("Error", {}).get("Code", "")
                        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                            continue
                        raise
        except Exception as e:
            log.warning("object store bucket init skipped: %s", e)
        yield
    await audit_batcher.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="FoxEngine", lifespan=lifespan)
    app.include_router(router, prefix="/api")

    repo_root = Path(__file__).resolve().parents[3]
    static_root = repo_root / "web" / "dist"
    assets = static_root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        index = static_root / "index.html"
        if not index.is_file():
            raise HTTPException(404, "frontend not built")
        return FileResponse(index)

    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api"):
            raise HTTPException(404)
        index = static_root / "index.html"
        if not index.is_file():
            raise HTTPException(404, "frontend not built")
        return FileResponse(index)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("foxengine.main:app", host="0.0.0.0", port=8000, reload=False)
