# FoxEngineReborn

Self-hosted **PII / breach-data search** stack (IntelX-style MVP): ingest normalized leads into ClickHouse, organize with tags, query with a small **DSL**, authenticate with **JWT** or **API keys**. Full product scope lives in [`PLAN.md`](PLAN.md).

## Stack

| Layer        | Tech                                      |
| ------------ | ----------------------------------------- |
| API + UI     | FastAPI (Python 3.13), React (Vite + TS)  |
| Relational   | Postgres 16 (users, roles, tags, audit)   |
| Analytics    | ClickHouse (`leads` table)              |
| Object store | RustFS (S3 API)                           |
| Jobs         | Procrastinate worker (queue ready)        |
| NL → DSL     | OpenAI-compatible HTTP LLM (see [`docs/LLM.md`](docs/LLM.md)) |

## Quick start (Docker)

1. Copy `.env.example` to `.env`. Set **`FOX_MASTER_KEY`** to a Fernet key from `Fernet.generate_key().decode()` unless you omit it: Docker Compose injects a **dev-only default** when the variable is unset. If your `.env` sets `FOX_MASTER_KEY` to a non-Fernet value (for example a short placeholder), startup will fail until you fix or remove it.

2. From the repo root:

   `docker compose up --build`

   On first start, the optional **`llama-cpp`** service (default in compose) can download a small GGUF model into the `llm_models` volume (several minutes). NL translation is available once `GET /api/health` reports `"llm": "ok"`. To use **LM Studio, Ollama, vLLM, or another host** instead, set `FOX_LLM_BASE_URL` (and related vars) as described in [`docs/LLM.md`](docs/LLM.md).

3. Open **http://localhost:8000**. With the bundled **`backend/seeds/initial_admin.json`** (copied into the API image as `/app/seeds/initial_admin.json`), the first admin is created at startup (`admin` / `admin` by default); the setup wizard is skipped. Delete or edit that JSON before building if you prefer the interactive setup flow and a one-time API key. Change the password after first login.

API routes are under **`/api`** (same origin as the SPA). Health: **`GET /api/health`**.

## Docker dev (hot reload)

To change **API Python** or **React** without rebuilding images or restarting the whole stack on every edit:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Then open **http://localhost:5173**. A **`web`** service runs Vite with HMR; it proxies **`/api`** to the **`api`** container. The API runs **uvicorn `--reload`** with `./backend/src` mounted into the container.

Notes:

- **`worker`** also mounts `./backend/src` but does not auto-restart; run `docker compose restart worker` after changing task/worker code.
- Rebuild the API image when you change **`backend/pyproject.toml`**, **`Dockerfile`**, or **`alembic/`** (not for everyday edits under `backend/src`).

## Local dev (no Docker)

- **Backend:** `cd backend && uv sync && export FOX_MASTER_KEY=… && uv run alembic upgrade head` then run Procrastinate schema bootstrap and `uv run foxengine-api` (see `PLAN.md` / `docker-compose.yml` for env vars).
- **Frontend:** `cd web && npm install && npm run dev` (proxies `/api` to `http://127.0.0.1:8000` by default; set **`VITE_DEV_API_PROXY`** to point at another API URL).

## Configuration

All app settings use the **`FOX_`** prefix (see `backend/src/foxengine/config.py`). **`FOX_MASTER_KEY`** is required: it encrypts the JWT signing secret stored in Postgres.

NL → DSL uses an **OpenAI-compatible** chat API. See **[`docs/LLM.md`](docs/LLM.md)** for `FOX_LLM_BASE_URL`, optional `FOX_LLM_API_KEY`, health path, bundled model download (`LLM_MODEL_MIN_BYTES`, fixing a bad volume), and examples (bundled llama.cpp, LM Studio, Ollama, vLLM, Docker vs host).

Set **`FOX_LLM_ENABLED=false`** to turn off NL entirely (Query UI hides **Natural language**; `POST /api/query/nl` returns 400).

Compose-only model download knobs: **`LLM_MODEL_URL`**, **`LLM_MODEL_FILE`**, **`LLM_N_GPU_LAYERS`** (use `server-cuda` image and `LLM_N_GPU_LAYERS` > 0 for GPU).

## OpenAPI spec

Generate the OpenAPI document from the FastAPI app:

```bash
cd backend
uv run foxengine-openapi
```

If your environment does not already provide `FOX_MASTER_KEY`, pass one for the command:

```bash
cd backend
FOX_MASTER_KEY="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" uv run foxengine-openapi
```

This writes `docs/openapi.json` by default. You can pass a custom path:

```bash
cd backend
uv run foxengine-openapi ../docs/openapi.local.json
```

## License / scope

Single-tenant, per-instance distribution — see `PLAN.md` for phases, API surface, and acceptance goals.
