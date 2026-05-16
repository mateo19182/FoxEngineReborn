# FoxEngineReborn — Build Plan

Self-hosted, single-tenant **PII search engine** (IntelX-style MVP).
Operator persona: a customer who ingests breach/lead dumps and queries them with tag-based organization and AI-assisted NL queries.
Distribution: per-instance license. Install = `docker compose up`. No SaaS, no cross-customer data.

> This document supersedes the original scope plan PDF. Architectural decisions are settled — what follows is the buildable plan plus the risks the developer should design around.

---

## 1. Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                         React SPA (Vite + TS)                          │
│  Ingest wizard · Query (DSL + NL) · Tags · Exports · Users · Audit    │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼ (HTTP · JWT bearer or API key)
┌────────────────────────────────────────────────────────────────────────┐
│                   FastAPI (Python 3.12, async)                         │
│  Auth (JWT + RBAC) · DSL parser · NL→DSL bridge ·                      │
│  Job orchestrator · Tag CRUD · Audit logger                            │
└────────────────────────────────────────────────────────────────────────┘
   │                    │                          │
   ▼                    ▼                          ▼
┌──────────┐ ┌──────────────────────┐ ┌──────────────────┐ ┌───────────┐
│ClickHouse│ │      Postgres        │ │  RustFS          │ │  LLM      │
│ (leads)  │ │ users/roles/api_keys │ │ (S3-compatible:  │ │  Ollama   │
│          │ │ tags/batches/jobs    │ │  uploads, export │ │  + opt-in │
│          │ │ audit_log/settings   │ │  artifacts)      │ │  hosted   │
│          │ │ (also: job queue via │ │                  │ │           │
│          │ │  procrastinate)      │ │                  │ │           │
└──────────┘ └──────────────────────┘ └──────────────────┘ └───────────┘
```

**Components**

| Component         | Tech                                                          | Why                                                                                            |
| ----------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| API service       | **Python 3.12 + FastAPI + Pydantic v2**, Uvicorn workers       | Async I/O fits ClickHouse / RustFS / LLM streaming; Pydantic gives free request validation.    |
| ORM / migrations  | **SQLAlchemy 2.x + Alembic** (Postgres only)                  | ClickHouse access goes through `clickhouse-connect` (async), not the ORM.                       |
| Background jobs   | **Procrastinate** (Postgres-backed, async, LISTEN/NOTIFY)      | No extra broker; reuses Postgres for queue + state. Replaces Celery/arq.                        |
| Web UI            | **React 18 + Vite + TypeScript**, TanStack Query, shadcn/ui    | Modern SPA stack; Vite for fast dev; shadcn for accessible components.                          |
| Static asset host | Uvicorn (mounts the built SPA from the API container)         | One process serves API + SPA. No reverse proxy needed unless the operator wants one upstream.   |
| Data plane        | **ClickHouse**                                                | Columnar, compressed, scales single-node → cluster; n-gram skip indexes for wildcard queries.  |
| Relational store  | **Postgres 16**                                               | Users, roles, API keys, tags, batches, jobs, audit log, settings, **and** the job queue.       |
| Object store      | **RustFS** (S3-compatible API)                                | Stores raw uploads and export artifacts. Self-hosted from day one.                              |
| LLM (default)     | Ollama + small instruct model                                 | Runs locally, no data egress. Replaceable.                                                     |
| LLM (opt-in)      | Anthropic / OpenAI                                            | Better translation quality; admin must accept "NL strings leave the box".                       |
| Containerization  | Docker + docker compose v2                                    | Single command to bring everything up.                                                          |

**Why Postgres-only (no Redis):** Procrastinate uses Postgres `LISTEN/NOTIFY` for the job queue; the audit-log async writer batches in-process memory; brute-force protection and rate limiting are explicitly out of MVP. Adding Redis would buy nothing here.

**TLS:** intentionally not handled by the app. If the instance is exposed to the public internet, the customer puts a TLS terminator (their load balancer, Cloudflare, an nginx in front, whatever) upstream. Most operators will run this on a LAN/VPN/Tailscale and not need TLS at all. Documented expectation, not a feature.

---

## 2. Data model

### 2.1 Identity rules

A **lead** = one row about a person/account. Every lead **must contain at least one** of:

- `phone` — normalized digits-only + country code (E.164 via libphonenumber). Raw also stored.
- `email` — normalized lowercased. Raw also stored. Domain + local-part queryable independently.
- `username` — free string.
- `id_card` — free string. No per-country validation in MVP.

Rows missing all four are **rejected at ingest** and counted in the batch report.

### 2.2 Canonical extended fields (16, typed)

| Group     | Fields                                                                                       |
| --------- | -------------------------------------------------------------------------------------------- |
| Person    | `full_name`, `first_name`, `last_name`, `dob` (Date), `gender` (LowCardinality)              |
| Location  | `address`, `city`, `country` (LowCardinality), `zip`                                         |
| Network   | `ip` (IPv4/IPv6), `user_agent`, `isp`, `phone_carrier`                                       |
| Auth      | `password`, `password_hash`                                                                  |
| Activity  | `last_seen` (DateTime)                                                                       |

Anything else lives in `extras` (key/value bag, slower but searchable).

### 2.3 Tags

First-class entities, **not** strings.

| Field         | Notes                                          |
| ------------- | ---------------------------------------------- |
| `tag_id`      | UUID, primary key.                             |
| `name`        | e.g. `Ticketmaster-VM`. Unique per instance.   |
| `source_url`  | Origin URL.                                    |
| `breach_date` | Date.                                          |
| `type`        | `LOGIN` / `VM` / `LEAK` / extensible.          |
| `notes`       | Free text.                                     |

Many-to-many with leads. Tags are global to the instance.

### 2.4 Identity merging (Hybrid)

- **Storage** stays per-batch: each ingested row is its own ClickHouse row tagged with `batch_id`, `ingest_ts`, `row_in_batch`.
- **Profile view** is a query-time concern: results can be returned either `view=rows` (default; per-batch rows) or `view=merged` (aggregated by normalized identity). Merged view shows the union of canonical fields, all extras, and all tags, with each constituent row labeled by source batch + ingest date.
- An `identity_key` column (string: `email_norm` || `phone_norm` || `username` || `id_card`, chosen by priority) is computed at ingest and **used as the ClickHouse `ORDER BY` key prefix** so merged-profile aggregation is range-scan friendly.

### 2.5 ClickHouse schema (sketch)

```sql
CREATE TABLE leads (
    batch_id           UUID,
    row_in_batch       UInt64,
    ingest_ts          DateTime DEFAULT now(),
    identity_key       String,                     -- chosen normalized identity (see §2.4)

    phone_norm         String,                     -- E.164, empty if none
    phone_raw          String,
    email_norm         LowCardinality(String),     -- lowercased, empty if none
    email_raw          String,
    email_local        String MATERIALIZED splitByChar('@', email_norm)[1],
    email_domain       LowCardinality(String) MATERIALIZED splitByChar('@', email_norm)[2],
    username           String,
    id_card            String,

    full_name          String,
    first_name         String,
    last_name          String,
    dob                Nullable(Date),
    gender             LowCardinality(String),
    address            String,
    city               LowCardinality(String),
    country            LowCardinality(String),
    zip                String,
    ip                 String,
    user_agent         String,
    isp                LowCardinality(String),
    phone_carrier      LowCardinality(String),
    password           String,
    password_hash      String,
    last_seen          Nullable(DateTime),

    extras             Map(String, String),
    tag_ids            Array(UUID),                -- denormalized for query speed (see §2.7)

    INDEX idx_phone_ngram     phone_norm    TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_email_ngram     email_norm    TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_username_ngram  username      TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_idcard_ngram    id_card       TYPE ngrambf_v1(3, 2048, 3, 0) GRANULARITY 4,
    INDEX idx_tags            tag_ids       TYPE bloom_filter()            GRANULARITY 1
)
ENGINE = MergeTree
ORDER BY (identity_key, batch_id, row_in_batch)
PARTITION BY toYYYYMM(ingest_ts)
SETTINGS index_granularity = 8192;
```

### 2.6 Postgres schema (sketch)

```sql
-- Auth & RBAC (stateless JWT; no sessions table)
CREATE TABLE users (
    id            UUID PRIMARY KEY,
    username      CITEXT UNIQUE NOT NULL,
    email         CITEXT UNIQUE,
    password_hash TEXT NOT NULL,            -- argon2id
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    UUID REFERENCES users(id)
);

CREATE TABLE roles (
    id   UUID PRIMARY KEY,
    name TEXT UNIQUE NOT NULL              -- admin | operator | viewer (seeded)
);

CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE RESTRICT,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE api_keys (
    id            UUID PRIMARY KEY,
    name          TEXT NOT NULL,
    key_hash      TEXT NOT NULL UNIQUE,    -- sha256 of the opaque token
    owner_user_id UUID NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);

-- Audit log (append-only)
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id    UUID REFERENCES users(id),       -- null = API key or system
    actor_kind  TEXT NOT NULL,                   -- user | api_key | system
    api_key_id  UUID REFERENCES api_keys(id),
    action      TEXT NOT NULL,
    target_kind TEXT,
    target_id   TEXT,
    details     JSONB NOT NULL DEFAULT '{}',
    ip          INET,
    user_agent  TEXT
);
CREATE INDEX ON audit_log (ts DESC);
CREATE INDEX ON audit_log (actor_id, ts DESC);
CREATE INDEX ON audit_log (action, ts DESC);

-- Domain
CREATE TABLE tags (
    id          UUID PRIMARY KEY,
    name        CITEXT UNIQUE NOT NULL,
    source_url  TEXT,
    breach_date DATE,
    type        TEXT,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID REFERENCES users(id),
    deleted_at  TIMESTAMPTZ
);

CREATE TABLE batches (
    id              UUID PRIMARY KEY,
    name            TEXT,
    source_filename TEXT,
    upload_uri      TEXT,
    accepted_rows   BIGINT NOT NULL DEFAULT 0,
    rejected_rows   BIGINT NOT NULL DEFAULT 0,
    duplicate_rows  BIGINT NOT NULL DEFAULT 0,
    ingest_ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_by     UUID REFERENCES users(id),
    deleted_at      TIMESTAMPTZ
);

CREATE TABLE jobs (
    id              UUID PRIMARY KEY,
    type            TEXT NOT NULL,               -- ingest | export | bulk_tag | tag_purge
    state           TEXT NOT NULL,               -- queued | running | done | failed | canceled
    batch_id        UUID,
    owner_user_id   UUID REFERENCES users(id),
    total_rows      BIGINT,
    processed_rows  BIGINT NOT NULL DEFAULT 0,
    failed_rows     BIGINT NOT NULL DEFAULT 0,
    checkpoint      JSONB NOT NULL DEFAULT '{}',
    started_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    result_uri      TEXT,
    error           TEXT
);

CREATE TABLE ingest_rejections (
    id         BIGSERIAL PRIMARY KEY,
    batch_id   UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    line_no    BIGINT,
    reason     TEXT NOT NULL,
    raw_line   TEXT NOT NULL
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID REFERENCES users(id)
);
```

Procrastinate adds its own tables (`procrastinate_jobs`, `procrastinate_events`) via its migration; the application `jobs` table above mirrors business state so the UI doesn't need to read internal queue tables.

### 2.7 Tag join strategy

ClickHouse is bad at frequent joins. Strategy:

- `leads.tag_ids` is an `Array(UUID)` — filter via `has(tag_ids, X)` or `hasAny(tag_ids, [...])`. Bloom-filter index makes this fast.
- Tag metadata (`name`, `source_url`, `breach_date`, `type`, `notes`) lives only in Postgres. Result rendering enriches with metadata at the API layer.
- Adding a tag to a lead = `ALTER TABLE leads UPDATE tag_ids = arrayPushBack(...)` — slow but rare and operator-initiated.
- Removing/renaming a tag does not touch leads (only metadata changes).
- Deleting a tag = mark deleted in Postgres + lazy purge from arrays via a scheduled `ALTER ... UPDATE` mutation.

---

## 3. Ingestion

### 3.1 Inputs

- **Structured:** CSV, JSON, JSONL, SQL dumps (`INSERT INTO ... VALUES (...)` parsing for MySQL/Postgres/SQLite dialects).
- **Semi-structured:** TXT with `:`, `|`, `;`, `,`, tab delimiters; combo lists (`email:password`, `user:pass:ip`, …).
- **Compressed archives:** `.zip`, `.gz`, `.7z`, `.tar.gz`. Default: each contained file = sub-batch. Operator can override to "merge all".
- **Out of MVP:** PDFs, free-text logs, scraped HTML.

### 3.2 UI-driven bulk ingest

1. Upload file/archive. Stored to **RustFS** under `uploads/{batch_id}/{filename}`.
2. Auto-detect: format, delimiter, columns, candidate identity fields, per-column type guess.
3. Preview screen: 20–50 sample rows in parsed form + proposed column→field mapping with **confidence per column** (so the operator can spot the weak guesses).
4. Operator remaps columns: drag/edit, mark skip, mark "extras with key X". For phone-only batches, operator can set a **default country code** here.
5. Operator picks/creates tags (applied to whole batch). Optional batch display name.
6. Confirm → Procrastinate job enqueued. Progress + per-step status visible.
7. Validation: rows missing all 4 identity fields dropped; counts of accepted/rejected/duplicate rows shown.

Audit events: `batch.upload`, `batch.ingest.start`, `batch.ingest.done`, `batch.ingest.failed`.

### 3.3 API ingest

`POST /api/index`
Body:
```json
{
  "leads": [{ "phone": "+34...", "email": "x@y.com", "extras": { "...": "..." } }],
  "tag_names": ["Ticketmaster-VM"],
  "batch_name": "checker-2026-05-14"
}
```
Same identity-field requirement. Same normalization. Auth: API key in `Authorization: Bearer …` (or JWT for UI-side ingest). Requires role `operator` or `admin`.

### 3.4 Bulk tag update

- Operator uploads CSV with at least one identity field per row + selects tags.
- Match by normalized identity against existing leads.
- Output: tags applied to all matches + **downloadable CSV of unmatched rows** (CSV materialized to RustFS).
- Unmatched rows are not inserted (operator can re-upload via §3.2 if they want them stored).

### 3.5 Ingest hygiene

- Phone/email normalized at write time; both raw and normalized stored.
- libphonenumber (`phonenumbers` Python package) for phone parsing (per-batch default country falls in here).
- Skip duplicates **within the same batch**: dedup key = `(phone_norm, email_norm, username, id_card, canonical fields hash)`.
- No cross-batch dedup at storage time (merged-profile view handles cross-batch).
- Rejected rows: written to `ingest_rejections` in Postgres with reason + raw line. Downloadable as CSV from the batch detail screen.

### 3.6 Idempotency

Every batch has a UUID. Rows are addressed by `(batch_id, row_in_batch)`. If a job restarts mid-ingest, it resumes from the last checkpoint (see §6). Re-running an already-completed batch is a no-op.

---

## 4. Query layer

### 4.1 DSL

| Match mode       | Example                                                       | Implementation                                                  |
| ---------------- | ------------------------------------------------------------- | --------------------------------------------------------------- |
| Exact            | `email:john@outlook.com`                                      | Direct `email_norm = ?`.                                        |
| Prefix wildcard  | `username:john*`                                              | `startsWith(username, ?)` — fast with ORDER BY when on prefix.  |
| Suffix wildcard  | `phone:*7434`                                                 | `endsWith(phone_norm, ?)` — n-gram skip index helps.            |
| Substring        | `email:*outlook*`                                             | `position(email_norm, ?)` — n-gram skip index does the heavy.   |
| Component        | `email.domain:outlook.com`, `phone.country:+34`               | Hits materialized columns (`email_domain`, etc.).               |
| Tag filter       | `tag:Ticketmaster-VM`, `tag.type:LOGIN`, `tag.breach_date:Y`  | Resolve tag predicate → tag_id set in Postgres → `hasAny(...)`. |
| Boolean compose  | `… AND … OR NOT …`                                            | DSL parser builds an AST → ClickHouse `WHERE`.                  |

**DSL is a real parser** (Lark or pyparsing — pick at start of Phase 1), not regex on user input. Pagination: default 50, max 1000. Default sort: `ingest_ts DESC`. The parser emits a parameterized ClickHouse query — no string interpolation of user values, ever.

### 4.2 NL→DSL

- Single text box. LLM translates NL → DSL string.
- The translated DSL is **displayed to the user before execution** — they confirm or edit. (Doubles as DSL tutorial.)
- Default LLM: **bundled local Ollama** with a small instruct model (3-7B class). Admin can opt into hosted (Anthropic/OpenAI) in Settings — first enable shows a clear "NL strings leave this instance" confirmation.
- Prompt is constrained to the DSL grammar + the canonical field list + the tag list to minimize hallucinated fields/tags.
- Failed translations fall back to "I couldn't translate this, here's what I tried" — never silently execute.

### 4.3 Export

- Any result set → CSV or JSONL.
- Large exports run as **Procrastinate jobs**; UI shows status; download link available when ready.
- Export streams from ClickHouse → RustFS → time-limited presigned URL (or proxied download via the API).
- Export file naming: `{query_hash}_{ts}.{csv|jsonl}` under `exports/` bucket.
- Audit events: `export.start`, `export.done`.

### 4.4 Result rows

Every result row contains: all populated canonical fields, all extras, all tags (with metadata), source batch (id + display name + ingest date).

---

## 5. Auth & RBAC (MVP)

**Three seeded roles:**

| Role       | Can do                                                                                                                                     |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `admin`    | Everything: users/roles CRUD, settings, API keys, audit log read, tags, batches, ingest, query, export, batch soft-delete.                 |
| `operator` | Tags CRUD, ingest (UI + API), bulk-tag-update, query, export. **Cannot** manage users/roles/settings/API keys. **Cannot** read audit log.  |
| `viewer`   | Query and export only. **Cannot** ingest, **cannot** modify tags, **cannot** manage anything.                                              |

A user can have multiple roles; effective permissions are the union.

### 5.1 Tokens

Two token types, both sent as `Authorization: Bearer <token>`:

- **JWT** — for UI users. Issued by `POST /api/auth/login` after username + password. Signed HS256 with a server-side secret (generated at first start, stored in `settings` table encrypted with an instance master key from env). Payload includes `sub` (user_id), `roles`, `iat`, `exp`. Default TTL: **12 hours**. No refresh tokens — re-login on expiry. **Stateless: no sessions table, no DB hit per request.**
- **API key** — for scripts/integrations. Opaque random string with a distinguishing prefix (e.g. `fox_…`); only the sha256 hash is stored in `api_keys`. Each key is owned by a user and inherits that user's roles. **Revocable** (sets `revoked_at`); the auth middleware checks `revoked_at IS NULL` and bumps `last_used_at` (cheap single-row write, async-flushed alongside audit events).

The API distinguishes the two by token format: JWTs are dotted base64; API keys carry the `fox_` prefix.

### 5.2 Passwords

argon2id via `argon2-cffi`. Sensible defaults; tuned for ~100 ms verify on tier-1 hardware.

### 5.3 Audit log

**Logged actions** (non-exhaustive; final list pinned in `API.md`):

- `auth.login.success`, `auth.login.failure`, `auth.password_change`
- `user.create`, `user.update`, `user.disable`, `user.delete`, `user.role_grant`, `user.role_revoke`
- `api_key.create`, `api_key.revoke`
- `tag.create`, `tag.update`, `tag.delete`
- `batch.upload`, `batch.ingest.start`, `batch.ingest.done`, `batch.ingest.failed`, `batch.delete`
- `query.run` (DSL + duration + result count; **no raw result rows**)
- `export.start`, `export.done`, `export.download`
- `settings.update`, `llm.provider_switch`

Each row: `ts`, `actor_id` / `api_key_id`, `actor_kind`, `action`, `target_kind`, `target_id`, `details` (JSONB), `ip`, `user_agent`.

**Append-only** at the application level (no UPDATE/DELETE on `audit_log` in code paths) and reinforced via Postgres role permissions on the API DB role.

**Performance:** writes are non-blocking — audit rows go through an in-process asyncio queue and flush in batches to Postgres. A queue-full condition logs to stderr and falls back to synchronous write rather than block the request.

---

## 6. Background jobs (resumable)

Jobs: **ingest**, **export**, **bulk-tag-update**, **tag-delete-purge**.

- Implemented with **Procrastinate** on Postgres. No external broker; the queue is a Postgres table polled via `LISTEN/NOTIFY`.
- Workers run as a separate container (`fox-worker`) sharing the API codebase.
- Application `jobs` table mirrors business state (so the UI lists/filters without reading Procrastinate's internal tables).
- **Checkpoint** = byte offset in the source object (or row index for already-parsed input). Stored in `jobs.checkpoint` JSONB. Updated every N rows.
- On worker startup, jobs left in `running` state are requeued: parser opens the RustFS object, seeks to `checkpoint`, resumes.
- Ingest dedup against partial inserts uses `(batch_id, row_in_batch)` — re-inserting the same row is a no-op given deterministic `row_in_batch` per source line and single-threaded worker per batch.
- Worker concurrency is bounded (e.g. 2 ingest workers, 1 export worker on tier-1; configurable via env).

---

## 7. UI

React 18 + Vite + TypeScript SPA. TanStack Query for server state. Responsive web only — no native mobile.

Screens:

1. **Login** — username + password.
2. **Dashboard** — recent batches, total leads, total tags, disk usage, queued jobs. (Scoped by role.)
3. **Ingest wizard** — upload → preview/remap → tags → confirm → progress. (Operator + admin.)
4. **Query** — DSL box + NL box. Side panel showing the translated DSL when NL is used. Result table with pagination, view toggle (rows / merged profile), per-result tag chips, export button.
5. **Batches** — list, detail (counts, rejections CSV, soft-delete). Delete = admin only.
6. **Tag manager** — CRUD, bulk-apply launcher. (Operator + admin.)
7. **Jobs** — list + detail for ingest/export jobs. Users see their own jobs; admins see all.
8. **Users & Roles** — admin only. CRUD users, assign roles, manage API keys per user.
9. **Audit log** — admin only. Filterable by user, action, target, time range. Exportable.
10. **Settings** — admin only. LLM provider config, default phone country, retention/backup hooks, audit retention policy, JWT TTL.
11. **Account** — every user. Change own password, list and revoke own API keys.

JWT stored client-side in `localStorage` (or in an `HttpOnly` cookie set by the login endpoint — developer's call; either is fine since we're stateless). Logout = client drops the token.

---

## 8. Install & deployment

### 8.1 Single-server (tiers 1–2)

`docker compose up` brings up: ClickHouse · Postgres · RustFS · API (FastAPI/Uvicorn serving SPA + API on one port) · Worker (Procrastinate) · Ollama (with model pulled on first start).

**First-run flow:**
1. Compose start.
2. Setup page in browser: operator creates the **first admin account** (username + password). System generates an initial API key and shows it once.
3. Alembic runs Postgres migrations idempotently; ClickHouse schema applied via the API's startup hook.
4. RustFS buckets `uploads/` and `exports/` provisioned.
5. JWT signing secret generated and persisted (encrypted via instance master key from env).
6. Done.

### 8.2 Cluster (tiers 3–4)

A separate compose file (`compose.cluster.yaml`) brings up:

- ClickHouse cluster (multi-shard, configurable replicas) via Keeper for replication coordination.
- Postgres (single primary, optional read replica).
- RustFS in multi-node mode (erasure-coded layout).
- API service horizontally scaled (multiple Uvicorn instances behind whatever load balancer the operator already runs).
- Workers scaled out per-shard ingest load.

### 8.3 Sizing tiers

| Tier | Data size | Layout                                | Approx hardware (per node)                          |
| ---- | --------- | ------------------------------------- | --------------------------------------------------- |
| 1    | ≤ 100 GB  | Single node, single-shard ClickHouse  | 4 vCPU · 16 GB RAM · 500 GB NVMe                    |
| 2    | ≤ 1 TB    | Single node, larger                   | 8 vCPU · 64 GB RAM · 4 TB NVMe                      |
| 3    | ≤ 10 TB   | 2–4 shards, 1 replica each            | 16 vCPU · 128 GB RAM · 8 TB NVMe per node           |
| 4    | ≤ 100 TB  | 6–10 shards, 2 replicas each, Keeper  | 32 vCPU · 256 GB RAM · 16 TB NVMe per node          |

(Numbers are starting recommendations; install doc will refine with benchmark data.)

### 8.4 Backup / restore

- **MVP backup:** `clickhouse-backup` (open-source) + `pg_dump` + RustFS object sync, invoked by `docker compose run backup`. Stored to a configurable local path or remote S3-compatible target.
- **MVP restore:** documented manual procedure.
- Out of MVP: scheduled backups, retention policies, PITR.

---

## 9. Observability & ops

- `/api/health` returns per-dependency status (ClickHouse, Postgres, RustFS, LLM reachability).
- `query.run` audit rows give you the full query history without standing up Prometheus.
- Disk usage gauge in the UI dashboard (per-component: ClickHouse data, RustFS, Postgres).
- Per-job logs accessible from the Jobs screen.
- **Query resource limits** (mandatory): set ClickHouse `max_execution_time`, `max_memory_usage`, `max_result_rows` per profile to prevent a single wildcard query from melting the box.
- Soft-delete a batch (`DELETE /api/batches/:id`, admin only): marks the batch deleted in Postgres; a scheduled mutation removes rows from ClickHouse.

---

## 10. API surface

Auth: JWT bearer (UI) **or** API-key bearer. Role required is noted per endpoint.

| Method | Path                            | Role          | Purpose                                          |
| ------ | ------------------------------- | ------------- | ------------------------------------------------ |
| POST   | `/api/auth/login`               | —             | Username + password → JWT.                       |
| POST   | `/api/auth/password`            | any           | Change own password.                             |
| GET    | `/api/auth/me`                  | any           | Current user + roles.                            |
| GET    | `/api/users`                    | admin         | List users.                                      |
| POST   | `/api/users`                    | admin         | Create user.                                     |
| PATCH  | `/api/users/:id`                | admin         | Update user / assign roles / disable.            |
| DELETE | `/api/users/:id`                | admin         | Delete user.                                     |
| GET    | `/api/api-keys`                 | admin / self  | List API keys (admin: all; user: own).           |
| POST   | `/api/api-keys`                 | any           | Create API key (own). Returned **once**.         |
| DELETE | `/api/api-keys/:id`             | admin / owner | Revoke API key.                                  |
| POST   | `/api/index`                    | operator+     | API ingest (§3.3).                               |
| POST   | `/api/query`                    | viewer+       | Run DSL query.                                   |
| POST   | `/api/query/nl`                 | viewer+       | NL→DSL translation only.                         |
| POST   | `/api/export`                   | viewer+       | Kick off export job.                             |
| GET    | `/api/jobs`                     | any (scoped)  | Own jobs (operator/viewer); all (admin).         |
| GET    | `/api/jobs/:id`                 | any (scoped)  | Job status + download link.                      |
| GET    | `/api/batches`                  | viewer+       | List batches.                                    |
| GET    | `/api/batches/:id`              | viewer+       | Batch detail.                                    |
| DELETE | `/api/batches/:id`              | admin         | Soft-delete batch.                               |
| GET    | `/api/tags`                     | viewer+       | List tags.                                       |
| POST   | `/api/tags`                     | operator+     | Create tag.                                      |
| PATCH  | `/api/tags/:id`                 | operator+     | Update tag.                                      |
| DELETE | `/api/tags/:id`                 | admin         | Delete tag.                                      |
| POST   | `/api/tags/bulk-apply`          | operator+     | Bulk-tag-update CSV.                             |
| GET    | `/api/audit`                    | admin         | Audit log (filter + paginate).                   |
| GET    | `/api/settings`                 | admin         | Read settings.                                   |
| PATCH  | `/api/settings`                 | admin         | Update settings.                                 |
| GET    | `/api/health`                   | —             | Per-dependency health.                           |

A standalone `API.md` will pin payload shapes once schemas stabilize.

---

## 11. Implementation phases

Four phases, ~10 weeks. Each phase ends with a runnable system on `docker compose up`.

### Phase 1 — Foundation + Auth + Core query (weeks 1-3)

**Status (implemented, 2026-05):** Repo has FastAPI + Vite/React, `docker compose` (Postgres, ClickHouse, RustFS, API, worker), Alembic + Procrastinate schema, ClickHouse `leads` DDL on API startup, JWT + API keys, batched audit writes, first-run setup, `POST /api/index`, Lark DSL + `POST /api/query`, tag CRUD, minimal UI (setup / login / query / account), `ruff` + `ty`. **Not done vs original Phase 1 bullets:** CI pipeline, automated test suite, `GET /api/audit` reader, full exit-criteria polish (e.g. admin user-creation UI, ingest-from-UI at 1k rows).

- Repo scaffolding (Python + React), CI, lint, type-check, tests.
- Compose skeleton: ClickHouse · Postgres · RustFS · API · Worker.
- Alembic migrations for the full Postgres schema (§2.6) + Procrastinate's own.
- ClickHouse schema applied on API startup.
- Auth: users, roles (seeded `admin` / `operator` / `viewer`), JWT issuance + verification middleware, API keys, audit log infrastructure (writer + reader).
- First-run setup page → first admin user.
- `POST /api/index` end-to-end (validation, normalization, ClickHouse write) — synchronous mode for small bodies.
- DSL parser (exact, prefix, suffix, substring, component, boolean) emitting parameterized ClickHouse queries.
- `POST /api/query` end-to-end with pagination.
- Tag CRUD (Postgres only).
- Minimal React UI: login, query screen with DSL box and result table, account screen.

**Exit criteria:** an admin can create a user, that user can log in (JWT issued), ingest 1k rows via the API key path, and run all match modes from the UI. Every action shows up in the audit log.

### Phase 2 — Bulk ingest + Tags + Export (weeks 4-6)

- Format auto-detection (CSV, JSON, JSONL, SQL dumps, combo lists) with confidence scoring per column.
- Archive unpack (zip/gz/7z/tar.gz) into RustFS, sub-batch by default.
- Ingest wizard UI: upload → preview/remap → tag selection → confirm → progress.
- Procrastinate worker with resumable checkpoints; rejection report download.
- Tag manager UI; bulk-tag-update flow + unmatched CSV.
- Export jobs (CSV, JSONL) streaming to RustFS.
- Merged-profile view at the query layer.

**Exit criteria:** all §13 acceptance flows 1–7 pass on a fresh install with a synthetic 10 GB dataset.

### Phase 3 — NL + Admin + Hardening (weeks 7-8)

- Ollama bundled with first-run model pull.
- NL→DSL translator (grammar-constrained prompt, parser-validated output, "show before execute" UX).
- Hosted LLM opt-in (Anthropic/OpenAI) with egress-warning UX.
- Admin UI: Users & Roles screen, API key management, Settings screen, Audit log viewer with filters.
- Soft-delete batch flow (admin).
- Cluster compose file (tier 3-4) with Keeper + RustFS multi-node.
- Backup/restore command + documented procedure.

**Exit criteria:** an admin can manage users/roles/keys, run an NL query, opt into hosted LLM with warning, and complete a backup → restore on a synthetic 100 GB dataset.

### Phase 4 — Verification + Performance + Install doc (weeks 9-10)

- Run all §13 acceptance flows on fresh installs at tier 1 and tier 3 layouts.
- Performance pass against §15 latency targets; if substring p95 misses target at tier 3, integrate a Tantivy/Meilisearch sidecar (decision point — see §16).
- Sizing benchmarks against synthetic 1 TB / 10 TB datasets; finalize sizing table.
- Install doc covering all four tiers, backup/restore, password/key rotation, audit retention.
- Security pass: argon2id parameters, JWT TTL defaults, audit append-only verification.
- Bug bash.

**Exit criteria:** every §13 flow passes; every §15 performance target met or has a documented mitigation.

---

## 12. Tech stack summary

| Layer            | Tech                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------- |
| Backend language | Python 3.12                                                                           |
| Web framework    | FastAPI + Pydantic v2 + Uvicorn                                                       |
| ORM              | SQLAlchemy 2.x async + Alembic (Postgres)                                             |
| ClickHouse       | `clickhouse-connect` (async)                                                          |
| Background jobs  | Procrastinate (Postgres LISTEN/NOTIFY)                                                |
| Auth crypto      | `argon2-cffi` (passwords), `pyjwt` (JWT), `cryptography` (settings encryption)        |
| Phone parsing    | `phonenumbers`                                                                        |
| DSL parser       | Lark or pyparsing (pick at Phase 1 start)                                              |
| Frontend         | React 18 + Vite + TypeScript + TanStack Query + React Router + shadcn/ui + Tailwind   |
| LLM (local)      | Ollama                                                                                |
| LLM (hosted)     | `anthropic` + `openai` SDKs                                                            |
| Object store     | RustFS (S3 API; client: `aioboto3` or `boto3`)                                         |
| Containerization | Docker + docker compose v2                                                            |

---

## 13. Acceptance verification

End-to-end flows the operator must be able to perform on a fresh install:

1. First-run setup: create first admin user, receive initial API key.
2. Admin creates an operator user and a viewer user. Each can log in (JWT issued).
3. Operator creates a personal API key; ingests via `POST /api/index` with that key.
4. Operator ingests a structured file (CSV/JSON/JSONL/SQL) via UI with column remap + tags applied.
5. Operator ingests a semi-structured combo list (`email:password`, etc.) via UI.
6. Operator ingests a compressed archive (zip/gz/7z/tar.gz) and picks sub-batch vs merged.
7. Operator bulk-tag-updates existing leads from a CSV and downloads the unmatched-rows CSV.
8. Viewer runs each match mode (exact, prefix, suffix, substring, component, tag, boolean) and meets the §15 speed targets; **cannot** create tags or ingest.
9. Viewer runs an NL query, sees the translated DSL, edits it, executes.
10. Viewer exports a result set to CSV and to JSONL via the background job flow.
11. Operator creates/edits/deletes a tag; changes reflected in queries.
12. Rows missing all four identity fields are rejected with a clear count + downloadable rejection CSV.
13. API service is restarted mid-ingest; the job resumes from checkpoint.
14. Admin soft-deletes a batch; its rows disappear from query results.
15. Admin opens the audit log; finds all of the above as audit events with correct actor + IP.
16. Admin revokes an API key; the next request with that key returns 401.
17. Admin runs the backup command; restores onto a fresh install and verifies the data.

---

## 14. Out of MVP (explicit)

- Per-record GDPR takedown endpoint (batch-level soft-delete is in scope; per-row is not).
- PDF / unstructured text extraction.
- Regex queries.
- Semantic / embedding search on free-text fields.
- Cross-instance federation / sharing between customers.
- Native mobile UI (responsive web is enough).
- Scheduled backups / retention policies / PITR.
- SSO / SAML / OIDC.
- 2FA / WebAuthn.
- Fine-grained per-tag or per-batch ACLs (roles are global).
- TLS termination by the app.
- Rate limiting.
- JWT refresh tokens / revocation list (12h TTL + re-login is enough).
- Brute-force login backoff.

---

## 15. Performance targets

| Scenario                                 | Target                          | Notes                                              |
| ---------------------------------------- | ------------------------------- | -------------------------------------------------- |
| Exact filter, tier 1-2                   | < 200 ms (p95)                  | ORDER BY hits + LowCardinality.                    |
| Component / prefix filter, tier 1-2      | < 500 ms (p95)                  |                                                    |
| Substring (`*foo*`), tier 1-2            | < 2 s (p95)                     | n-gram skip index.                                 |
| Any filtered query, multi-TB (tier 3-4)  | < 5 s (p95)                     | Wildcards may exceed; explicitly allowed slower.   |
| Ingest throughput, single node           | ≥ 30k rows/s sustained          | CSV path, typical 16-column rows. Python + async.  |
| NL→DSL translation (local LLM, tier 1-2) | < 3 s (p95)                     | Acceptable for an interactive box.                 |
| Audit-log write overhead per request     | < 5 ms added p95                | Batched async writer.                              |
| JWT verify per request                   | < 1 ms                          | Stateless HS256.                                   |

---

## 16. Risks & technical concerns

In rough order of likelihood × impact.

1. **Wildcard substring queries at scale.** ClickHouse n-gram skip indexes help but at 10–100 TB they can still be slow on rare substrings. **Mitigation:** Phase 4 benchmark; if substring p95 misses §15 target at tier 3, add Tantivy or Meilisearch as a sidecar text index. Treat as a known fallback.

2. **Merged-profile view explosion.** A common phone (`+34000000000`) may appear in thousands of batches. **Mitigation:** cap merged-profile aggregation to N rows per identity (e.g. 500) with a "truncated" indicator; or pre-materialize an `identity_summary` table via ClickHouse `MaterializedView` keyed on `identity_key`.

3. **Python ingest throughput.** Async helps for I/O but parsing 50k+ rows/s in pure Python may not hit target. **Mitigation:** use C-backed CSV parsing (`pyarrow.csv` or stdlib `csv` with batching); insert via ClickHouse native protocol in 10-50k row chunks; offload SQL-dump parsing to a small Rust helper if benchmarks miss. Scale workers horizontally before optimizing.

4. **SQL dump parsing reliability.** `INSERT INTO ... VALUES (...)` across MySQL / Postgres / SQLite has subtle differences. **Mitigation:** target the top three dialects explicitly; clear "couldn't parse this file" error path.

5. **Combo list auto-detection accuracy.** **Mitigation:** preview/remap UI with confidence scores; never auto-confirm a low-confidence guess.

6. **Phone normalization without country.** **Mitigation:** per-batch default country setting at the preview step; fall back to "store raw, leave normalized empty".

7. **Local LLM quality for NL→DSL.** **Mitigation:** strict system prompt with full DSL grammar + canonical field list + tag list; **always parse the LLM output through the real DSL parser** before showing it; clear error if it doesn't parse.

8. **Bundled LLM disk footprint.** **Mitigation:** pull the LLM model on first start via a one-shot container; one-time download, documented.

9. **ClickHouse + frequent tag re-assignment is expensive.** `ALTER ... UPDATE` on `tag_ids` is a heavy mutation. **Mitigation:** batch tag updates (one mutation per bulk-apply, not per row).

10. **Audit log write amplification.** Every query/ingest/login writes audit rows. **Mitigation:** async batched writer (§5.3); audit table partitioned monthly; optional retention policy.

11. **Audit log integrity.** Without append-only enforcement, an attacker with DB access can edit history. **Mitigation:** application-layer append-only + Postgres role permissions denying UPDATE/DELETE on `audit_log` to the API role. Hash-chained / signed log is out of MVP.

12. **JWT has no revocation.** Until the 12 h TTL expires, a stolen JWT keeps working. **Mitigation:** short TTL (12 h default, configurable down to 1 h); disabling a user prevents new logins but doesn't kill outstanding tokens. If the operator needs immediate kill, **rotating the JWT signing secret invalidates all tokens** — that's the emergency lever, documented. Long-lived API keys (the real attack surface) are revocable per-key.

13. **Docker compose vs. real cluster.** Tier 4 (100 TB) isn't really `docker compose up`. **Mitigation:** explicit `compose.cluster.yaml` + install doc that says: *for tier 3+, expect to provision N nodes and run the cluster compose on each*.

14. **Export of very large result sets.** **Mitigation:** stream from ClickHouse straight to RustFS; max-rows-per-export config (default 10M); show estimated size before kickoff.

15. **Backup story for 10+ TB.** **Mitigation:** manual backup/restore tooling in MVP (§8.4). Honest RTO/RPO expectations.

16. **Schema evolution.** Adding a canonical field later requires migrating existing deployments. **Mitigation:** Alembic + numbered ClickHouse schema migrations applied at startup; canonical fields additive only in MVP; extras absorb anything new mid-cycle.

17. **Roles are global, not per-batch.** A viewer sees every batch. **Mitigation:** explicit in §14 as out-of-scope. Per-batch ACLs is a v2 conversation.

---

## 17. Improvements proposed (delta vs. scope PDF)

- **Idempotent batch ingestion** via `(batch_id, row_in_batch)`.
- **Confidence scores on column auto-detection** — operator sees weak guesses.
- **Default country code per batch** for phone normalization (preview step).
- **Resource limits per query** (ClickHouse `max_execution_time`, `max_memory_usage`).
- **`/api/health`** covering ClickHouse / Postgres / RustFS / LLM.
- **Soft-delete a batch** — admin recovery lever without per-record takedown.
- **Manual backup/restore tooling** in MVP.
- **Max-rows-per-export config** — prevents disk exhaustion.
- **Per-user, multi, revocable API keys** instead of a single instance-wide token.
- **Append-only audit log via DB role permissions** — minimal-cost tamper resistance.
- **First-run setup page** to create the first admin user.
- **Self-service account screen** (password change + manage own API keys) for every user.
- **JWT signing-secret rotation as emergency kill switch** — invalidates all UI sessions at once when needed.
