# FoxEngineReborn — Manual test plan

Use this checklist on a **fresh** stack (`docker compose up --build` from repo root). Mark each row as you go:

| Symbol | Meaning |
| ------ | ------- |
| ⬜ | Not tested yet |
| ✅ | Test passed |
| ❌ | Test failed (note in *Notes*) |
| — | Not implemented (skip until built) |

**Default credentials (seeded admin):** `admin` / `admin` (see `backend/seeds/initial_admin.json`). Change password after first login.

**API base:** `http://localhost:8000/api` · **UI:** `http://localhost:8000`

---

## 0. Environment smoke

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | E0.1 | `curl -s http://localhost:8000/api/health \| jq` | `postgres`, `clickhouse`, `object_store` all `"ok"` |
| ⬜ | E0.2 | Open UI `/` | Redirects to login or query (not blank / 5xx) |
| ⬜ | E0.3 | `docker compose ps` | `api`, `worker`, `postgres`, `clickhouse`, `rustfs` running |
| ⬜ | E0.4 | `cd backend && uv run ruff check && uv run ty check` | Clean (static gate before deeper testing) |

---

## 1. Auth & setup (Phase 1 — **built**)

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | A1.1 | **Fresh DB:** remove volumes, unset seed, hit `/api/setup/status` | `needs_setup: true` |
| ⬜ | A1.2 | Complete setup wizard (UI `/` or `POST /api/setup/complete`) | Admin created; one-time API key shown |
| ⬜ | A1.3 | Login `POST /api/auth/login` | JWT returned |
| ⬜ | A1.4 | `GET /api/auth/me` with Bearer | Roles include `admin` |
| ⬜ | A1.5 | Account → change password | `POST /api/auth/password` succeeds; old password fails |
| ⬜ | A1.6 | Account → create API key | Secret shown once; listed in `/api/api-keys` |
| ⬜ | A1.7 | `POST /api/index` with `Authorization: Bearer <api_key>` | 200 + `batch_id` |
| ⬜ | A1.8 | Revoke key → repeat index | **401** |
| ⬜ | A1.9 | Logout / clear token → protected route | Redirect or 401 |

**§13 flow mapping:** 1 ✅ · 3 ✅ · 16 ✅ (when A1.7–A1.8 done)

---

## 2. Users & RBAC (partial — **built with gaps**)

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | R2.1 | Admin → Admin page → create **viewer** | Appears in user list; can log in |
| ⬜ | R2.2 | Admin → create **manager** | Can access Ingest + Tags write; cannot open Admin |
| ⬜ | R2.3 | Viewer: no Ingest nav; `POST /api/ingest/file` | **403** |
| ⬜ | R2.4 | Viewer: `POST /api/tags` | **403** |
| ⬜ | R2.5 | Viewer: `POST /api/query` | **200** |
| ⬜ | R2.6 | Manager: ingest + tag create | **200** |
| ⬜ | R2.7 | Admin creates **operator** via API `POST /api/users` `roles:["operator"]` | Works via API (not in Admin UI dropdown) |
| — | R2.8 | Admin UI: create **operator** user | **—** UI only offers viewer/manager (`AdminPage.tsx`) |
| — | R2.9 | `PATCH /api/users/:id` disable user | **—** endpoint not implemented |
| — | R2.10 | `DELETE /api/users/:id` | **—** endpoint not implemented |

**§13 flow mapping:** 2 partial (viewer/manager yes; operator via API only)

---

## 3. Tags (Phase 1 + bulk — **built**)

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | T3.1 | Tags → create tag | `POST /api/tags`; appears in list |
| ⬜ | T3.2 | Query `tag:YourTagName` | Rows with that tag |
| ⬜ | T3.3 | Query `tag.type:LEAK` (if type set) | Matches |
| ⬜ | T3.4 | Admin → delete tag | `DELETE /api/tags/:id`; gone from list |
| ⬜ | T3.5 | Manager tries delete tag | **403** (admin only) |
| ⬜ | T3.6 | Tags → bulk apply CSV + pick tag names → Jobs | Job `foxengine_bulk_tag` completes; download unmatched if offered |
| ⬜ | T3.7 | Re-query after bulk apply | New tags visible on leads |

**§13 flow mapping:** 7 ✅ · 11 partial (delete admin-only)

---

## 4. API ingest — `POST /api/index` (Phase 1 — **built**)

Prepare `sample-index.json`:

```json
{
  "batch_name": "api-smoke",
  "tag_names": ["smoke-tag"],
  "leads": [
    {"email": "alice@example.com", "full_name": "Alice"},
    {"email": "bob@example.com", "phone": "+15551234567"},
    {"full_name": "no-id"},
    {"email": "alice@example.com", "full_name": "Alice dup"}
  ]
}
```

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | I4.1 | POST body as operator/manager API key or JWT | `accepted_rows` ≥ 2, `rejected_rows` ≥ 1 (no identity) |
| ⬜ | I4.2 | Batches page | Batch listed with counts |
| ⬜ | I4.3 | Query `email:alice@example.com` | At least one row |
| ⬜ | I4.4 | Ingest 1000+ rows (script loop or JSONL file) | Completes; audit `batch.ingest.done` |

**§13 flow mapping:** 3 ✅ · 12 partial (rejections via batch stats; CSV download via file ingest)

---

## 5. File ingest & archives (Phase 2 — **built**, SQL parser **not**)

Create fixtures under `test-fixtures/` (not in repo yet — add locally):

| File | Purpose |
| ---- | ------- |
| `leads.csv` | Headers `email,phone,full_name` + 5 rows |
| `leads.jsonl` | One JSON object per line |
| `combo.txt` | Lines `user@mail.com:secret123` |
| `mixed.zip` | Contains `inner.csv` |
| `bad-rows.csv` | Rows with no email/phone/username/id_card |

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | I5.1 | Ingest → preview `leads.csv` | JSON shows detected columns + confidence |
| ⬜ | I5.2 | Ingest file with `format=auto`, tags, optional `column_map` JSON | Job queued; worker logs `foxengine_ingest_file` |
| ⬜ | I5.3 | Jobs → job **done**; Batches shows accepted/rejected | Counts > 0 |
| ⬜ | I5.4 | Download rejections CSV on batch | Rows explain reject reason |
| ⬜ | I5.5 | Ingest `combo.txt` `format=combo` | Password field populated |
| ⬜ | I5.6 | Ingest `mixed.zip`, `merge_archive=false` | Multiple batches/jobs (one per inner file) |
| ⬜ | I5.7 | Ingest archive `merge_archive=true` | Single merged inner stream |
| ⬜ | I5.8 | Formats: `.tar.gz`, `.7z`, `.gz` (single member) | Unpack + ingest without crash |
| — | I5.9 | SQL dump file (`INSERT INTO ... VALUES`) | **—** `format_detect` supports jsonl/csv/combo only |
| — | I5.10 | Restart API **mid-ingest**; job resumes | **—** export has `resume_offset`; file ingest does **not** resume |

**§13 flow mapping:** 4 ✅ · 5 ✅ · 6 ✅ · 12 ✅ (rejections) · 13 **—** not implemented

---

## 6. Query DSL (Phase 1 + merged — **built**)

Use data from §4–5. For each mode, run in UI Query or `POST /api/query` `{"dsl":"…","limit":50,"view":"rows"}`.

| Status | ID | DSL example | Mode |
| ------ | -- | ----------- | ---- |
| ⬜ | Q6.1 | `email:alice@example.com` | exact |
| ⬜ | Q6.2 | `email:alice*` | prefix |
| ⬜ | Q6.3 | `email:*@example.com` | suffix |
| ⬜ | Q6.4 | `email:*alice*` | substring |
| ⬜ | Q6.5 | `email.domain:example.com` | component |
| ⬜ | Q6.6 | `email:a* AND tag:smoke-tag` | boolean |
| ⬜ | Q6.7 | `view=merged` same DSL | Aggregated identity row + `_merged_sources` |
| ⬜ | Q6.8 | Invalid DSL `@@@` | **400** `invalid dsl` |
| ⬜ | Q6.9 | Viewer runs all above | Same results as operator |
| ⬜ | Q6.10 | Optional: record p95 latency (§15) | exact <2s on small dataset (informal) |

**§13 flow mapping:** 8 ✅ (functional; perf informal)

---

## 7. Export jobs (Phase 2 — **built**)

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | X7.1 | Query with hits → Export CSV | Job queued `foxengine_export` |
| ⬜ | X7.2 | Export JSONL | Second job; `format` in checkpoint |
| ⬜ | X7.3 | Jobs → download when `state=done` | File downloads; row count plausible |
| ⬜ | X7.4 | Export empty DSL match | Job completes; small/empty file |
| ⬜ | X7.5 | Viewer can export; operator cannot see admin-only jobs | Scoped job list |

**§13 flow mapping:** 10 ✅

---

## 8. Batches & soft-delete (partial)

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | B8.1 | `GET /api/batches`, `GET /api/batches/:id` | Metadata matches ingest |
| ⬜ | B8.2 | Soft-deleted batch excluded from query | Queries filter `Batch.deleted_at` in SQL compile |
| — | B8.3 | Admin `DELETE /api/batches/:id` | **—** route not implemented |
| — | B8.4 | After delete, rows invisible in query | **—** needs B8.3 + ClickHouse mutation job |

**§13 flow mapping:** 14 **—** not implemented

---

## 9. Audit log (Phase 1 reader — **built**)

| Status | ID | What to do | Expected |
| ------ | -- | ---------- | -------- |
| ⬜ | U9.1 | After login, ingest, query, export, user create | Admin → Audit shows rows |
| ⬜ | U9.2 | Check `action` values | e.g. `auth.login`, `query.run`, `batch.ingest.done`, `user.create` |
| ⬜ | U9.3 | Pagination next/prev | `total` > `limit` works |
| ⬜ | U9.4 | Non-admin `GET /api/audit-log` | **403** |

**§13 flow mapping:** 15 ✅

---

## 10. UI coverage (sanity)

| Status | ID | Page | Check |
| ------ | -- | ---- | ----- |
| ⬜ | UI10.1 | Login | Error on bad password |
| ⬜ | UI10.2 | Query | Table columns, merged toggle, export buttons |
| ⬜ | UI10.3 | Tags | Create + bulk form |
| ⬜ | UI10.4 | Batches | Rejection download link |
| ⬜ | UI10.5 | Ingest | Preview + submit (operator/manager) |
| ⬜ | UI10.6 | Jobs | Poll/refresh; download |
| ⬜ | UI10.7 | Account | Password + API keys |
| ⬜ | UI10.8 | Admin | Users + audit (admin only) |

---

## 11. Not in codebase yet (Phase 3–4 — **remaining product work**)

Do not spend manual QA time here until implemented:

| ID | Feature | PLAN reference |
| -- | ------- | -------------- |
| — | NL → DSL (`POST /api/query/nl`, Ollama) | §13 #9, Phase 3 |
| — | Settings API + admin Settings UI | §10 |
| — | User PATCH/DELETE | §10 |
| — | Batch soft-delete API + CH mutation | §9, §13 #14 |
| — | SQL dump ingest parser | Phase 2 |
| — | Ingest checkpoint resume on worker/API restart | §13 #13 |
| — | CI pipeline + automated `pytest` suite | Phase 1 gap |
| — | Backup / restore command | §13 #17, Phase 3 |
| — | Cluster compose, performance gates (§15), install doc | Phase 4 |

---

## Summary: what is **remaining**

### A. Manual testing you should still run (implemented, ⬜ above)

Priority order:

1. **E0** — health + stack up  
2. **A1** — auth, API keys, `/index`  
3. **I4** — small API ingest + rejections  
4. **Q6** — all DSL modes + merged view  
5. **I5** — file ingest, archives, combo, rejections CSV  
6. **X7** — export CSV/JSONL via Jobs  
7. **R2** — viewer vs manager vs admin gates  
8. **T3** — tags + bulk apply  
9. **U9** — audit trail completeness  
10. **UI10** — page sweep  

### B. Product / engineering gaps (not testable yet)

| Area | Gap |
| ---- | --- |
| Users | No PATCH/DELETE; Admin UI cannot create `operator` (API can) |
| Ingest | No SQL format; no mid-ingest resume |
| Batches | No delete endpoint; soft-delete filter exists in queries only |
| Query | No NL / LLM path |
| Ops | No backup/restore; health has no LLM probe |
| Quality | No `backend/tests/`; no CI |

### C. §13 acceptance flows — scorecard

| # | Flow | Testable now? |
| - | ---- | ------------- |
| 1 | First-run setup | ✅ (or skip if using seed admin) |
| 2 | Admin creates users | ⚠️ viewer/manager only in UI |
| 3 | API key + `/index` | ✅ |
| 4 | Structured file UI ingest | ✅ |
| 5 | Combo list UI | ✅ |
| 6 | Archive ingest | ✅ |
| 7 | Bulk tag CSV | ✅ |
| 8 | Viewer query all modes | ✅ |
| 9 | NL query | — |
| 10 | Export CSV/JSONL jobs | ✅ |
| 11 | Tag CRUD in queries | ✅ (delete admin-only) |
| 12 | Rejection reporting | ✅ (file path) |
| 13 | Restart mid-ingest resume | — |
| 14 | Admin soft-delete batch | — |
| 15 | Audit log | ✅ |
| 16 | Revoke API key | ✅ |
| 17 | Backup restore | — |

---

## Quick API cheat sheet

```bash
BASE=http://localhost:8000/api
TOKEN=$(curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" "$BASE/health" | jq
curl -s -H "Authorization: Bearer $TOKEN" -X POST "$BASE/query" \
  -H 'Content-Type: application/json' \
  -d '{"dsl":"email:*@example.com","limit":10,"view":"rows"}' | jq
```

---

*Last aligned with codebase: 2026-05-15. Update Status column as you test; open issues for any ❌ row.*
