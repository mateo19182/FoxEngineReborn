#!/usr/bin/env bash
# Create a single compressed archive (Postgres custom dump + ClickHouse native backup + S3 mirror).
# Run from repo root with the compose stack up: postgres, clickhouse, rustfs (and any container
# used to resolve the compose network, e.g. api or rustfs).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
  sed -n '1,80p' <<'EOF'
Usage: foxengine-backup-archive.sh [--output PATH]

Writes one .tar.gz containing:
  manifest.json          metadata (paths, versions, env names)
  postgres/foxengine.dump   pg_dump -Fc
  clickhouse/foxengine.zip  ClickHouse BACKUP DATABASE ... TO File(...)
  s3/<bucket>/...          aws-cli s3 sync mirror of each bucket

Environment (optional; defaults match docker-compose.yml):
  COMPOSE_FILE          default: docker-compose.yml
  POSTGRES_SERVICE      default: postgres
  POSTGRES_USER         default: fox
  POSTGRES_DB           default: foxengine
  CLICKHOUSE_SERVICE    default: clickhouse
  CLICKHOUSE_PASSWORD   default: fox
  CLICKHOUSE_DATABASE   default: foxengine
  RUSTFS_SERVICE        default: rustfs
  S3_ENDPOINT_INTERNAL  default: http://rustfs:9000
  S3_ACCESS_KEY_ID      default: rustfsadmin
  S3_SECRET_ACCESS_KEY  default: rustfsadmin
  S3_BUCKETS            default: uploads exports (space-separated)
  NETWORK_CONTAINER     read network from this compose service (default: try api, rustfs, postgres)
EOF
}

OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --output)
      OUT="${2:?}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-fox}"
POSTGRES_DB="${POSTGRES_DB:-foxengine}"
CLICKHOUSE_SERVICE="${CLICKHOUSE_SERVICE:-clickhouse}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-fox}"
CLICKHOUSE_DATABASE="${CLICKHOUSE_DATABASE:-foxengine}"
S3_ENDPOINT_INTERNAL="${S3_ENDPOINT_INTERNAL:-http://rustfs:9000}"
S3_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-rustfsadmin}"
S3_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-rustfsadmin}"
read -r -a S3_BUCKETS <<<"${S3_BUCKETS:-uploads exports}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -z "$OUT" ]]; then
  mkdir -p "${ROOT}/backups"
  OUT="${ROOT}/backups/foxengine-backup-${ts}.tar.gz"
fi

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/foxengine-backup-staging.XXXXXX")"
cleanup() {
  if [[ -n "${STAGING:-}" && -d "$STAGING" ]]; then
    rm -rf "$STAGING" || true
  fi
}
trap cleanup EXIT

mkdir -p "${STAGING}/postgres" "${STAGING}/clickhouse" "${STAGING}/s3"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

network_of_service() {
  local svc="$1"
  local cid
  cid="$(compose ps -q "$svc" 2>/dev/null | head -n1)"
  if [[ -z "$cid" ]]; then
    return 1
  fi
  docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$cid" | head -n1
}

resolve_network() {
  if [[ -n "${NETWORK_CONTAINER:-}" ]]; then
    network_of_service "$NETWORK_CONTAINER" && return
  fi
  network_of_service api && return || true
  network_of_service rustfs && return || true
  network_of_service postgres && return || true
  return 1
}

NET="$(resolve_network)" || {
  echo "Could not determine compose Docker network (start api, rustfs, or postgres)." >&2
  exit 1
}

echo "Staging backup under ${STAGING}"
echo "Postgres dump (${POSTGRES_DB})..."
compose exec -T -e "PGPASSWORD=${POSTGRES_PASSWORD:-fox}" "$POSTGRES_SERVICE" \
  pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" >"${STAGING}/postgres/foxengine.dump"

CH_INTERNAL="/var/lib/clickhouse/backups/foxengine_backup_${ts}.zip"
echo "ClickHouse BACKUP DATABASE ${CLICKHOUSE_DATABASE}..."
compose exec -T "$CLICKHOUSE_SERVICE" sh -c \
  'mkdir -p /var/lib/clickhouse/backups && chown clickhouse:clickhouse /var/lib/clickhouse/backups'
compose exec -T "$CLICKHOUSE_SERVICE" clickhouse-client \
  --user default --password "$CLICKHOUSE_PASSWORD" \
  --query "BACKUP DATABASE ${CLICKHOUSE_DATABASE} TO File('${CH_INTERNAL}') SETTINGS compression_method='zstd'"

CH_CID="$(compose ps -q "$CLICKHOUSE_SERVICE" | head -n1)"
docker cp "${CH_CID}:${CH_INTERNAL}" "${STAGING}/clickhouse/foxengine.zip"
compose exec -T "$CLICKHOUSE_SERVICE" rm -f "$CH_INTERNAL"

echo "S3 mirror (buckets: ${S3_BUCKETS[*]})..."
for b in "${S3_BUCKETS[@]}"; do
  mkdir -p "${STAGING}/s3/${b}"
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    --network "$NET" \
    -e AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
    -e AWS_EC2_METADATA_DISABLED=true \
    -v "${STAGING}/s3/${b}:/mirror:rw" \
    amazon/aws-cli \
    s3 sync "s3://${b}" "/mirror" \
    --endpoint-url "$S3_ENDPOINT_INTERNAL" \
    --only-show-errors
done

pg_ver="$(compose exec -T "$POSTGRES_SERVICE" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc 'SHOW server_version;' | tr -d '\r')"
ch_ver="$(compose exec -T "$CLICKHOUSE_SERVICE" clickhouse-client --user default --password "$CLICKHOUSE_PASSWORD" --query 'SELECT version()' | tr -d '\r')"

manifest="${STAGING}/manifest.json"
export MANIFEST_PATH="$manifest"
export TS="$ts"
export POSTGRES_SERVICE POSTGRES_USER POSTGRES_DB
export CLICKHOUSE_SERVICE CLICKHOUSE_DATABASE
export PG_VER="$pg_ver" CH_VER="$ch_ver"
export S3_ENDPOINT_INTERNAL
S3_BUCKETS_JSON="$(printf '%s\n' "${S3_BUCKETS[@]}" | python3 -c 'import json,sys; print(json.dumps([x.strip() for x in sys.stdin if x.strip()]))')"
export S3_BUCKETS_JSON
python3 <<'PY'
import json
import os

path = os.environ["MANIFEST_PATH"]
data = {
    "format": "foxengine-archive-v1",
    "created_utc": os.environ["TS"],
    "postgres": {
        "service": os.environ.get("POSTGRES_SERVICE", ""),
        "user": os.environ.get("POSTGRES_USER", ""),
        "database": os.environ.get("POSTGRES_DB", ""),
        "dump_relpath": "postgres/foxengine.dump",
        "server_version": os.environ.get("PG_VER", ""),
    },
    "clickhouse": {
        "service": os.environ.get("CLICKHOUSE_SERVICE", ""),
        "database": os.environ.get("CLICKHOUSE_DATABASE", ""),
        "user": "default",
        "backup_relpath": "clickhouse/foxengine.zip",
        "server_version": os.environ.get("CH_VER", ""),
    },
    "s3": {
        "endpoint_internal": os.environ.get("S3_ENDPOINT_INTERNAL", ""),
        "buckets": json.loads(os.environ.get("S3_BUCKETS_JSON", "[]")),
        "root_relpath": "s3",
    },
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

echo "Archiving to ${OUT}..."
mkdir -p "$(dirname "$OUT")"
tar -C "$STAGING" -czf "$OUT" manifest.json postgres clickhouse s3
echo "Wrote ${OUT}"