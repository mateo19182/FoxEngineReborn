# NL to DSL: OpenAI-compatible LLM

The API translates natural language to the query DSL via **`POST /api/query/nl`**. The backend calls an **OpenAI-compatible** HTTP API:

- **`POST {FOX_LLM_BASE_URL}/v1/chat/completions`** (non-streaming JSON)
- Optional **`GET`** health probe (configurable path)

Output is always validated with the real DSL parser before the UI runs a query.

## Environment variables (`FOX_` prefix)

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `FOX_LLM_ENABLED` | `true` | Set `false` to disable NL translation (`/api/health` → `llm: disabled`; Query UI hides **Natural language**; `POST /api/query/nl` returns **400**). |
| `FOX_LLM_BASE_URL` | `http://localhost:8080` | **API root**: scheme + host + port only. Do **not** append `/v1`; the app adds `/v1/chat/completions`. |
| `FOX_LLM_MODEL` | `local` | `model` field in the chat request. Use the id your server expects (LM Studio model name, Ollama model tag, OpenAI model name, etc.). |
| `FOX_LLM_API_KEY` | *(empty)* | If set, requests send `Authorization: Bearer <value>`. Use for cloud APIs or gated local gateways. |
| `FOX_LLM_HEALTH_PATH` | `health` | Path appended to `FOX_LLM_BASE_URL` for **`GET /api/health`** → `llm` status. For servers without `/health`, use `v1/models` (OpenAI-style). Set to `off` to skip the HTTP probe (`llm` reports `skipped`). |
| `FOX_LLM_TIMEOUT_S` | `30` | Chat completion timeout (seconds). |
| `FOX_LLM_HEALTH_TIMEOUT_S` | `3` | Health request timeout (seconds). |

### Bundled `llama-cpp` download (`LLM_*` in Compose)

The `docker/llama-cpp/entrypoint.sh` script:

- Downloads to a **`.part`** file, then **`mv`** into place (no half-written final path).
- Verifies the **GGUF** header (`GGUF`) so HTML error pages or wrong content are rejected.
- Enforces a **minimum file size** with **`LLM_MODEL_MIN_BYTES`** (default `400000000` for the bundled Qwen 1.5B quant). Set to **`0`** to skip when you point `LLM_MODEL_URL` at a smaller GGUF.
- Retries the download up to **three** times.

If you still see **corrupt / incomplete** errors from `llama-server`, remove the bad file or drop the volume and recreate:

```bash
docker compose down
docker volume rm foxenginereborn_llm_models
docker compose up --build
```

(Volume name may differ; use `docker volume ls`.)

### Compose: API and `.env`

To use a **different** endpoint, set in `.env` for example:

```bash
FOX_LLM_BASE_URL=http://host.docker.internal:1234
FOX_LLM_MODEL=my-model
FOX_LLM_HEALTH_PATH=v1/models
```

On Linux, if `host.docker.internal` is missing, add under the `api` service in an override file:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Or point `FOX_LLM_BASE_URL` at a **reachable IP** (LAN, Tailscale, another compose network service name).

If you run an LLM only on the host and want to **avoid** starting the bundled `llama-cpp` container, start the stack without that service, for example:

```bash
docker compose up -d postgres clickhouse rustfs api worker
```

and set `FOX_LLM_BASE_URL` to your host listener (with `extra_hosts` as above when needed).

## Compatible servers (examples)

Base URL is always the **origin** (no `/v1` suffix).

| Where | Example `FOX_LLM_BASE_URL` | `FOX_LLM_HEALTH_PATH` | `FOX_LLM_MODEL` |
| ----- | ---------------------------- | ---------------------- | --------------- |
| Bundled **llama.cpp** (compose) | `http://llama-cpp:8080` | `health` | `local` (llama-server ignores name for single model) |
| **llama.cpp** on host | `http://127.0.0.1:8080` | `health` | `local` |
| **LM Studio** | `http://127.0.0.1:1234` | `v1/models` | Model name shown in LM Studio |
| **Ollama** (OpenAI compatibility) | `http://127.0.0.1:11434` | `v1/models` | e.g. `llama3.2` |
| **vLLM** | `http://vllm:8000` | `v1/models` | Served model id |
| **OpenAI** (hosted; data leaves the instance) | `https://api.openai.com` | `v1/models` | e.g. `gpt-4o-mini` |

For OpenAI and other hosted APIs, set **`FOX_LLM_API_KEY`**. Prefer a local endpoint for this product unless you explicitly accept egress of NL strings.

## Verify

- **`GET /api/health`** → `llm` should be `ok` (or `skipped` if health probe is off).
- Query page → **Natural language** (opens the translator modal) after the model is healthy.
