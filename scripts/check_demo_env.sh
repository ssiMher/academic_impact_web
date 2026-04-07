#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_WEB_PORT="${WEB_PORT:-18000}"
DEFAULT_MODEL_PORT="${MODEL_PORT:-18002}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"

echo "[check] project root: $ROOT_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] .env not found at: $ENV_FILE"
  echo "        please create it first."
  exit 1
fi

echo "[check] using env file: $ENV_FILE"

set -a
source "$ENV_FILE"
set +a

required_vars=(
  DEEPSEEK_API_KEY
  ACADEMIC_IMPACT_LOCAL_LLM_URL
  ACADEMIC_IMPACT_LOCAL_MODEL
  ACADEMIC_IMPACT_DOWNLOAD_DIR
)

missing=0
for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "[error] missing env var: $var"
    missing=1
  else
    echo "[ok] $var is set"
  fi
done

if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

mkdir -p "$ACADEMIC_IMPACT_DOWNLOAD_DIR"
echo "[ok] download dir ready: $ACADEMIC_IMPACT_DOWNLOAD_DIR"

for cmd in python3 ss tmux curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[error] required command not found: $cmd"
    exit 1
  fi
done

echo "[check] port usage"
if ss -ltn | grep -q ":${DEFAULT_WEB_PORT}\b"; then
  echo "[warn] web port ${DEFAULT_WEB_PORT} is already in use"
else
  echo "[ok] web port ${DEFAULT_WEB_PORT} looks free"
fi

if ss -ltn | grep -q ":${DEFAULT_MODEL_PORT}\b"; then
  echo "[warn] model port ${DEFAULT_MODEL_PORT} is already in use"
else
  echo "[ok] model port ${DEFAULT_MODEL_PORT} looks free"
fi

echo "[check] python env"
if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "[warn] .venv/bin/python not found; please create/install venv first"
else
  echo "[ok] found virtualenv python: $ROOT_DIR/.venv/bin/python"
fi

echo
echo "[next] if everything looks correct, run:"
echo "       bash scripts/start_web_demo.sh"
