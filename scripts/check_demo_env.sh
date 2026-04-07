#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_WEB_PORT="${WEB_PORT:-18000}"
DEFAULT_MODEL_PORT="${MODEL_PORT:-18002}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-}"

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
if [[ -n "$CONDA_ENV_NAME" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "[error] CONDA_ENV_NAME is set but conda command is not available"
    exit 1
  fi
  if conda run -n "$CONDA_ENV_NAME" python --version >/dev/null 2>&1; then
    echo "[ok] conda env is runnable: $CONDA_ENV_NAME"
  else
    echo "[error] failed to run python in conda env: $CONDA_ENV_NAME"
    exit 1
  fi
else
  if command -v python >/dev/null 2>&1; then
    echo "[ok] current python is available: $(python --version 2>&1)"
  else
    echo "[error] python command not found"
    exit 1
  fi
fi

echo
echo "[next] if everything looks correct, run:"
echo "       bash scripts/start_web_demo.sh"
if [[ -n "$CONDA_ENV_NAME" ]]; then
  echo "       (using conda env: $CONDA_ENV_NAME)"
fi
