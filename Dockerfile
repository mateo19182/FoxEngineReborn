# Build context: repository root (FoxEngineReborn/)
FROM node:22-bookworm AS web
WORKDIR /w
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM python:3.13-bookworm
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/seeds /app/seeds
COPY docker/wait-for-postgres.py /app/docker/wait-for-postgres.py
COPY --from=web /w/dist /web/dist
ENV PYTHONPATH=/app/src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["/bin/sh", "-c", "cd /app && python /app/docker/wait-for-postgres.py && alembic upgrade head && python -c 'from foxengine.bootstrap import ensure_procrastinate_schema; ensure_procrastinate_schema()' && uvicorn foxengine.main:app --host 0.0.0.0 --port 8000"]
