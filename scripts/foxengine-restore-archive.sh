#!/usr/bin/env bash
# Restore from a foxengine-backup-archive.sh .tar.gz (Postgres + ClickHouse + S3).
# Stop api and worker before running to avoid open DB connections.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
  sed -n '1,90p' <<'EOF'
Usage: foxengine-restore-archive.sh --archive PATH

Extracts the archive and restores:
  postgres/foxengine.dump   -> pg_restore into POSTGRES_DB
  clickhouse/foxengine.zip  -> DROP DATABASE + RESTORE FROM File(...)
  s3/<bucket>/...           -> aws s3 sync to RustFS/S3

Environment (optional; defaults match docker-compose.yml):
  COMPOSE_FILE, POSTGRES_SERVICE, POSTGRES_PASSWORD
  CLICKHOUSE_SERVICE, CLICKHOUSE_PASSWORD
  S3_ENDPOINT_INTERNAL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY
  NETWORK_CONTAINER       (optional; same resolution as backup script)

Postgres user and database name, ClickHouse database name, and S3 bucket list are read from manifest.json inside the archive.

Requires: docker compose stack with postgres, clickhouse, rustfs running.
EOF
}

ARCHIVE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --archive)
      ARCHIVE="${2:?}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "Missing or invalid --archive" >&2
  usage >&2
  exit 2
fi

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-fox}"
CLICKHOUSE_SERVICE="${CLICKHOUSE_SERVICE:-clickhouse}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-fox}"
S3_ENDPOINT_INTERNAL="${S3_ENDPOINT_INTERNAL:-http://rustfs:9000}"
S3_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-rustfsadmin}"
S3_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-rustfsadmin}"

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

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/foxengine-restore-staging.XXXXXX")"
cleanup() {
  if [[ -n "${STAGING:-}" && -d "$STAGING" ]]; then
    rm -rf "$STAGING" || true
  fi
}
trap cleanup EXIT

echo "Extracting ${ARCHIVE}..."
tar -xzf "$ARCHIVE" -C "$STAGING"

if [[ ! -f "${STAGING}/manifest.json" ]]; then
  echo "Archive missing manifest.json" >&2
  exit 1
fi

read -r POSTGRES_USER POSTGRES_DB CLICKHOUSE_DATABASE <<<"$(
  python3 -c "import json,sys; m=json.load(open(sys.argv[1])); p=m['postgres']; c=m['clickhouse']; print(p['user'], p['database'], c['database'])" "${STAGING}/manifest.json"
)"
if [[ ! "$POSTGRES_USER" =~ ^[a-zA-Z0-9_]+$ || ! "$POSTGRES_DB" =~ ^[a-zA-Z0-9_]+$ || ! "$CLICKHOUSE_DATABASE" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "Refusing manifest postgres user or database names with unexpected characters." >&2
  exit 1
fi

mapfile -t S3_BUCKETS < <(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print('\n'.join(m.get('s3',{}).get('buckets',[])))" "${STAGING}/manifest.json")
if [[ ${#S3_BUCKETS[@]} -eq 0 ]]; then
  mapfile -t S3_BUCKETS < <(find "${STAGING}/s3" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
fi

echo "Terminating connections to ${POSTGRES_DB}..."
compose exec -T -e "PGPASSWORD=${POSTGRES_PASSWORD}" "$POSTGRES_SERVICE" \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();" \
  >/dev/null || true

echo "Postgres pg_restore..."
compose exec -i -e "PGPASSWORD=${POSTGRES_PASSWORD}" "$POSTGRES_SERVICE" \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl \
  <"${STAGING}/postgres/foxengine.dump"

CH_INTERNAL="/var/lib/clickhouse/backups/foxengine_restore_${RANDOM}.zip"
echo "ClickHouse RESTORE (${CLICKHOUSE_DATABASE})..."
compose exec -T "$CLICKHOUSE_SERVICE" sh -c \
  'mkdir -p /var/lib/clickhouse/backups && chown clickhouse:clickhouse /var/lib/clickhouse/backups'
CH_CID="$(compose ps -q "$CLICKHOUSE_SERVICE" | head -n1)"
docker cp "${STAGING}/clickhouse/foxengine.zip" "${CH_CID}:${CH_INTERNAL}"
compose exec -T "$CLICKHOUSE_SERVICE" clickhouse-client \
  --user default --password "$CLICKHOUSE_PASSWORD" \
  --query "DROP DATABASE IF EXISTS ${CLICKHOUSE_DATABASE} SYNC"
compose exec -T "$CLICKHOUSE_SERVICE" clickhouse-client \
  --user default --password "$CLICKHOUSE_PASSWORD" \
  --query "RESTORE DATABASE ${CLICKHOUSE_DATABASE} FROM File('${CH_INTERNAL}')"
compose exec -T "$CLICKHOUSE_SERVICE" rm -f "$CH_INTERNAL"

echo "S3 upload (buckets: ${S3_BUCKETS[*]} )..."
for b in "${S3_BUCKETS[@]}"; do
  if [[ ! -d "${STAGING}/s3/${b}" ]]; then
    echo "Skipping missing bucket directory s3/${b}" >&2
    continue
  fi
  docker run --rm \
    --network "$NET" \
    -e AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
    -e AWS_EC2_METADATA_DISABLED=true \
    -v "${STAGING}/s3/${b}:/mirror:ro" \
    amazon/aws-cli \
    s3 mb "s3://${b}" --endpoint-url "$S3_ENDPOINT_INTERNAL" 2>/dev/null || true
  docker run --rm \
    --network "$NET" \
    -e AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
    -e AWS_EC2_METADATA_DISABLED=true \
    -v "${STAGING}/s3/${b}:/mirror:ro" \
    amazon/aws-cli \
    s3 sync "/mirror" "s3://${b}" \
    --endpoint-url "$S3_ENDPOINT_INTERNAL" \
    --only-show-errors
done

echo "Restore finished."
