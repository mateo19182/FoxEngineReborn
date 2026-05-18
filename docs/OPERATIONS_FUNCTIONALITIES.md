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
4. Queue ingest from staged upload (`POST /api/ingest/file/from-upload`)

Also supported:

- one-step direct ingest queue (`POST /api/ingest/file`)
- synchronous JSON payload ingest (`POST /api/index`)

Runtime ingest behavior:

- source file read from object storage
- parse + normalize into canonical lead fields
- deduplicate within ingest run
- write leads, identities, and tag links to ClickHouse in chunks
- persist rejected rows in Postgres for CSV download
- update batch/job counters and completion state

## Query, Related View, and Export

- DSL query execution: `POST /api/query`
- Result modes:
  - `rows`: direct matches
  - `related`: extends rows by shared identity values
- Natural language translation: `POST /api/query/nl` (when enabled)
- Export queue: `POST /api/export` (CSV or JSONL)

Export runtime behavior:

- compile DSL into ClickHouse SQL
- stream result batches up to configured cap
- serialize to CSV/JSONL
- upload artifact to object storage (`exports/<job-id>/...`)
- mark job done with `result_uri` for download

## Tags and Taxonomy

- Tag taxonomy read endpoint (`/api/tags/taxonomy`)
- Tag CRUD:
  - list/create/update
  - admin-only delete (soft delete)
- Bulk apply tags from CSV:
  - upload + queue via `/api/tags/bulk-apply`

## Jobs, Batches, and Downloads

- Jobs list/detail endpoints with ownership checks
- Batch list/detail endpoints
- Download endpoints:
  - `/api/jobs/{id}/download` for completed artifacts
  - `/api/batches/{id}/rejections.csv` for ingest rejects
- Worker executes:
  - `foxengine_ingest_file`
  - `foxengine_export`
  - `foxengine_bulk_tag`

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
