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

missing=0

check_required_var() {
  local var="$1"
  if [[ -z "${!var:-}" ]]; then
    echo "[error] missing env var: $var"
    missing=1
  else
    echo "[ok] $var is set"
  fi
}

analysis_mode="${ACADEMIC_IMPACT_ANALYSIS_MODE:-single_model}"
if [[ -z "$analysis_mode" ]]; then
  analysis_mode="single_model"
fi
echo "[check] analysis mode: $analysis_mode"

check_required_var ACADEMIC_IMPACT_DOWNLOAD_DIR

if [[ "$analysis_mode" == "legacy_two_stage" ]]; then
  check_required_var ACADEMIC_IMPACT_LOCAL_LLM_URL
  check_required_var ACADEMIC_IMPACT_LOCAL_MODEL
  check_required_var DEEPSEEK_API_KEY
elif [[ "$analysis_mode" == "single_model" ]]; then
  effective_llm_url="${ACADEMIC_IMPACT_LLM_URL:-${ACADEMIC_IMPACT_LOCAL_LLM_URL:-}}"
  effective_llm_model="${ACADEMIC_IMPACT_LLM_MODEL:-${ACADEMIC_IMPACT_LOCAL_MODEL:-}}"
  if [[ -z "$effective_llm_url" ]]; then
    echo "[error] missing env var: ACADEMIC_IMPACT_LLM_URL or ACADEMIC_IMPACT_LOCAL_LLM_URL"
    missing=1
  else
    echo "[ok] effective LLM URL is set"
  fi
  if [[ -z "$effective_llm_model" ]]; then
    echo "[error] missing env var: ACADEMIC_IMPACT_LLM_MODEL or ACADEMIC_IMPACT_LOCAL_MODEL"
    missing=1
  else
    echo "[ok] effective LLM model is set"
  fi

  if [[ "$effective_llm_url" == *"deepseek.com"* ]]; then
    if [[ -z "${ACADEMIC_IMPACT_LLM_API_KEY:-}" && -z "${DEEPSEEK_API_KEY:-}" ]]; then
      echo "[error] missing API key for DeepSeek: ACADEMIC_IMPACT_LLM_API_KEY or DEEPSEEK_API_KEY"
      missing=1
    else
      echo "[ok] LLM API key is set"
    fi
  elif [[ "$effective_llm_url" == *"dashscope.aliyuncs.com"* ]]; then
    if [[ -z "${ACADEMIC_IMPACT_LLM_API_KEY:-}" ]]; then
      echo "[error] missing API key for DashScope: ACADEMIC_IMPACT_LLM_API_KEY"
      missing=1
    else
      echo "[ok] LLM API key is set"
    fi
  fi
else
  echo "[error] invalid ACADEMIC_IMPACT_ANALYSIS_MODE: $analysis_mode"
  echo "        expected single_model or legacy_two_stage"
  missing=1
fi

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
