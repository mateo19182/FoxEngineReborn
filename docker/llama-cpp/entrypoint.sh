#!/bin/sh
set -eu

MODEL_DIR="${LLM_MODEL_DIR:-/models}"
MODEL_FILE="${LLM_MODEL_FILE:-Qwen3-4B.Q4_K_M.gguf}"
MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
MODEL_URL="${LLM_MODEL_URL:-https://huggingface.co/mradermacher/Qwen3-4B-GGUF/resolve/main/Qwen3-4B.Q4_K_M.gguf}"
# Minimum file size (bytes) after download; 0 disables.
# Qwen3-4B Q4_K_M is ~2.3GB; require at least 2GB to catch truncated downloads.
MIN_BYTES="${LLM_MODEL_MIN_BYTES:-2000000000}"

mkdir -p "${MODEL_DIR}"

is_gguf() {
  path="$1"
  test -f "$path" || return 1
  h=$(head -c 4 "$path" 2>/dev/null || true)
  test "$h" = "GGUF"
}

# Validate GGUF header: check magic, version, and tensor count are readable
validate_gguf() {
  path="$1"
  test -f "$path" || return 1

  # Read header fields (GGUF v3 spec)
  # Offset 0: 4 bytes magic "GGUF"
  # Offset 4: 4 bytes version (little-endian uint32)
  # Offset 8: 8 bytes tensor_count (little-endian uint64)

  magic=$(head -c 4 "$path" 2>/dev/null)
  test "$magic" = "GGUF" || { echo "Not a GGUF file (bad magic)" >&2; return 1; }

  # Read version (4 bytes, little-endian, unsigned)
  version_bytes=$(dd if="$path" bs=1 skip=4 count=4 2>/dev/null | od -A n -t u4 -)
  version=$(echo "$version_bytes" | tr -d ' ')

  # Supported versions: 2, 3
  case "$version" in
    2|3) : ;;
    *) echo "Unsupported GGUF version: $version" >&2; return 1 ;;
  esac

  # Read tensor count (8 bytes, little-endian, unsigned)
  tensor_bytes=$(dd if="$path" bs=1 skip=8 count=8 2>/dev/null | od -A n -t u8 -)
  tensor_count=$(echo "$tensor_bytes" | tr -d ' ')

  # Sanity check: should have at least a few tensors for a 1.7B model
  test "$tensor_count" -gt 10 2>/dev/null || { echo "Suspicious tensor count: $tensor_count" >&2; return 1; }

  return 0
}

size_ok() {
  path="$1"
  test "${MIN_BYTES}" != "0" || return 0
  sz=$(wc -c < "$path" | tr -d ' ')
  test "$sz" -ge "${MIN_BYTES}"
}

download_once() {
  part="${MODEL_PATH}.part"
  rm -f "$part"
  echo "llama-cpp: downloading ${MODEL_FILE}…"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 10 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
      -o "$part" "${MODEL_URL}" || return 1
  elif command -v wget >/dev/null 2>&1; then
    wget -q --show-progress --tries=10 --timeout=30 -O "$part" "${MODEL_URL}" || return 1
  else
    echo "llama-cpp: need curl or wget to download the model" >&2
    return 1
  fi
  if ! is_gguf "$part"; then
    echo "llama-cpp: download is not a GGUF file (wrong URL, HTML error page, or truncated). Removing." >&2
    rm -f "$part"
    return 1
  fi
  if ! validate_gguf "$part"; then
    echo "llama-cpp: download failed GGUF validation. Removing." >&2
    rm -f "$part"
    return 1
  fi
  if ! size_ok "$part"; then
    sz=$(wc -c < "$part" | tr -d ' ')
    echo "llama-cpp: file too small (${sz} bytes, min ${MIN_BYTES}). Incomplete download — removing." >&2
    rm -f "$part"
    return 1
  fi
  mv -f "$part" "${MODEL_PATH}"
  return 0
}

ensure_model() {
  if [ -f "${MODEL_PATH}" ]; then
    if ! is_gguf "${MODEL_PATH}" || ! validate_gguf "${MODEL_PATH}" || ! size_ok "${MODEL_PATH}"; then
      echo "llama-cpp: existing ${MODEL_FILE} is invalid — re-downloading…" >&2
      rm -f "${MODEL_PATH}"
    fi
  fi
  if [ ! -f "${MODEL_PATH}" ]; then
    n=0
    while [ "$n" -lt 3 ]; do
      n=$((n + 1))
      if download_once; then
        return 0
      fi
      echo "llama-cpp: download attempt ${n}/3 failed, retrying…" >&2
      sleep 5
    done
    return 1
  fi
  return 0
}

ensure_model || exit 1

NGGL="${LLM_N_GPU_LAYERS:-0}"
if [ "${NGGL}" -gt 0 ] 2>/dev/null; then
  exec /app/llama-server \
    -m "${MODEL_PATH}" \
    --host 0.0.0.0 \
    --port 8080 \
    -c 8192 \
    -n 4096 \
    --flash-attn on \
    -ngl "${NGGL}" \
    "$@"
else
  exec /app/llama-server \
    -m "${MODEL_PATH}" \
    --host 0.0.0.0 \
    --port 8080 \
    -c 8192 \
    -n 4096 \
    --flash-attn on \
    "$@"
fi
