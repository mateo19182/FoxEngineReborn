# Operations Functionalities

Single reference for all FoxEngine runtime functionality.

## Platform Scope

FoxEngine is a self-hosted lead-search platform for:

- ingesting datasets into normalized records
- tagging and organizing records
- querying with a DSL (and optional NL-to-DSL)
- running exports and bulk operations as background jobs
- auditing user/API activity

## System Components

- API: FastAPI backend (`/api/*`)
- UI: React SPA served from same origin
- Relational store: Postgres (users, roles, tags, jobs, batches, settings, audit)
- Search store: ClickHouse (leads + identity/tag relations)
- Object storage: S3-compatible buckets (`uploads`, `exports`)
- Queue: Procrastinate worker (`ingest_file`, `export`, `bulk_tag`)
- Optional LLM endpoint: OpenAI-compatible chat API

## Startup and Readiness

At API startup, the service:

- starts audit batching
- ensures ClickHouse schema exists
- ensures Procrastinate schema exists
- seeds first admin from `backend/seeds/initial_admin.json` when present
- loads encrypted JWT signing secret from settings
- opens queue app context
- ensures required object-storage buckets exist

Health endpoint: `GET /api/health` reports Postgres, ClickHouse, object store, and LLM status.

## Identity, Access, and Setup

- First-run setup flow:
  - `GET /api/setup/status`
  - `POST /api/setup/complete`
- User auth:
  - `POST /api/auth/login` returns JWT
  - `GET /api/auth/me` returns user identity + roles + LLM feature flag
  - `POST /api/auth/password` rotates password
- API keys:
  - create/list/revoke flows
  - key secret shown once at creation
- Role model:
  - admin: full administration
  - manager/operator: ingest and operational write flows
  - viewer: read/query flows

## Data Ingestion

Ingest supports JSONL, CSV, combo lines, and archives containing those formats.

Primary flow:

1. Preview upload (`POST /api/ingest/preview`)
2. Detect per-file format + CSV headers/guesses
3. Optional column-map suggestions (`POST /api/ingest/suggest-column-map`)
4. Queue ingest from staged upload (`POST /api/ingest/file/from-upload`); staged objects under `uploads/staged/{upload_id}/` are deleted after a successful commit for the parts that were ingested

Also supported:

- one-step direct ingest queue (`POST /api/ingest/file`)
- synchronous JSON payload ingest (`POST /api/index`)

Runtime ingest behavior:

- source file streamed from object storage (no full local copy for line-oriented formats)
- exact duplicate source files are detected by SHA-256 and rejected by default at queue time
- parse + normalize into canonical lead fields
- deduplicate within ingest run
- write leads, identities, and tag links to ClickHouse in chunks (parallel inserts per flush)
- persist rejected rows in Postgres for CSV download
- update batch/job counters and completion state

Tuning (`FOX_` env, see `config.py`): `FOX_INGEST_FLUSH_ROWS`, `FOX_INGEST_PROGRESS_EVERY`,
`FOX_WORKER_CONCURRENCY`. Run multiple worker containers with
`docker compose up -d --scale worker=N`.

## Query, Related View, and Export

- DSL query execution: `POST /api/query`
- Result modes:
  - `rows`: direct matches
  - `related`: extends rows by shared identity values
- Natural language translation: `POST /api/query/nl` (when enabled)
- Export queue: `POST /api/export` (CSV or JSONL)

Export runtime behavior:

- compile DSL into ClickHouse SQL
- prefer one-shot ClickHouse `INSERT INTO FUNCTION s3(...)` when enabled (`FOX_EXPORT_USE_CH_S3`, default true)
- on failure or resume, keyset-batched `SELECT` (cursor on `ingest_ts`, `batch_id`, `row_in_batch`) with multipart upload to object storage
- artifacts under `exports/<job-id>/result.csv` or `result.jsonl`
- mark job done with `result_uri` for download

## Tags and Taxonomy

- Tag taxonomy read endpoint (`/api/tags/taxonomy`)
- Tag CRUD:
  - list/create/update
  - admin-only delete (soft delete)
- Bulk apply tags from CSV:
  - upload + queue via `/api/tags/bulk-apply`
- Tag all rows in a completed ingest batch:
  - `POST /api/batches/{batch_id}/tags` with JSON `tag_names` (queues `batch_tag` job)

## Jobs, Batches, and Downloads

- Jobs list/detail endpoints with ownership checks
- Batch list/detail endpoints
- Admin batch delete: preview (`GET /api/batches/{id}/delete-preview`) and delete (`DELETE /api/batches/{id}`) — hides batch from search/export and queues ClickHouse row removal (`batch_purge` job, lightweight `DELETE FROM`)
- Download endpoints:
  - `/api/jobs/{id}/download` for completed artifacts
  - `/api/batches/{id}/rejections.csv` for ingest rejects
- Worker executes:
  - `foxengine_ingest_file`
  - `foxengine_export`
  - `foxengine_bulk_tag`
  - `foxengine_batch_tag`

## Storage Browser

- Browse object storage by prefix: `/api/storage/browse`
- Generate signed download URLs: `/api/storage/presign`
- Roots:
  - `uploads/` for ingest/staged files
  - `exports/` for export artifacts

## Assistant and LLM Features

LLM-dependent capabilities:

- NL-to-DSL translation
- CSV column mapping suggestions
- in-app assistant chat (sync + SSE stream)

Assistant can call read-only backend tools for jobs, batches, and tags.

LLM features can be disabled with `FOX_LLM_ENABLED=false`.

## Admin and Audit

Admin capabilities:

- create users (viewer/manager)
- manage API keys
- delete ingest batches (with preview; queues ClickHouse purge)
- inspect audit log with filters (action, actor, date range)

Audit captures auth, query, ingestion, export, and key events with actor metadata and request context.

## Frontend Functional Behavior

SPA routes and access:

- `/login`, `/query`, `/jobs`
- `/ingest`, `/storage` (ingest-capable roles)
- `/admin` (admin only)
- `/account` (non-admin account operations)

UI functional modules:

- query editor + DSL help + tags modal + export modal
- ingest preview/mapping/queue workflow
- job monitoring with auto-refresh
- storage prefix browser + multi-download
- account/admin password and key management
- floating assistant widget with local transcript persistence

## Deployment Modes

- Docker Compose full stack (default)
- Docker dev overlay for hot-reload API + Vite frontend
- Local non-Docker backend/frontend development
