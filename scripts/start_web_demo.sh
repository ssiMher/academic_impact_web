#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ---------------------------
# values you may want to edit
# ---------------------------
WEB_PORT="${WEB_PORT:-18000}"
MODEL_PORT="${MODEL_PORT:-18002}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
LOG_DIR="${LOG_DIR:-$HOME/logs/academic_impact_web}"
WEB_TMUX_SESSION="${WEB_TMUX_SESSION:-aiw-web}"
MODEL_TMUX_SESSION="${MODEL_TMUX_SESSION:-aiw-model}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-}"
PYTHON_CMD="${PYTHON_CMD:-python}"

# Replace this with your actual model startup command,
# or pass it in at runtime via the MODEL_START_CMD environment variable.
# It should launch an OpenAI-compatible endpoint that matches
# ACADEMIC_IMPACT_LLM_URL in your .env.
MODEL_START_CMD="${MODEL_START_CMD:-echo 'MODEL_START_CMD is not set. Edit scripts/start_web_demo.sh or pass MODEL_START_CMD=\"<your command>\" when launching this script.'; sleep infinity}"

mkdir -p "$LOG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] .env not found: $ENV_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

echo "[info] root dir: $ROOT_DIR"
echo "[info] web host: $WEB_HOST"
echo "[info] web port: $WEB_PORT"
echo "[info] model port: $MODEL_PORT"
echo "[info] log dir: $LOG_DIR"
if [[ -n "$CONDA_ENV_NAME" ]]; then
  echo "[info] conda env: $CONDA_ENV_NAME"
fi

ACTIVATE_CMD=""
if [[ -n "$CONDA_ENV_NAME" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "[error] CONDA_ENV_NAME is set but conda command is not available"
    exit 1
  fi
  CONDA_BASE="$(conda info --base)"
  ACTIVATE_CMD="source '$CONDA_BASE/etc/profile.d/conda.sh' && conda activate '$CONDA_ENV_NAME' && "
elif [[ "$PYTHON_CMD" == "python" ]] && ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
fi

if ss -ltn | grep -q ":${WEB_PORT}\b"; then
  echo "[error] web port ${WEB_PORT} is already in use"
  exit 1
fi

if ss -ltn | grep -q ":${MODEL_PORT}\b"; then
  echo "[warn] model port ${MODEL_PORT} is already in use"
  echo "       if your model service is already running, you can keep using it."
fi

if tmux has-session -t "$MODEL_TMUX_SESSION" 2>/dev/null; then
  echo "[warn] tmux session already exists: $MODEL_TMUX_SESSION"
else
  tmux new-session -d -s "$MODEL_TMUX_SESSION" "cd '$ROOT_DIR' && ${ACTIVATE_CMD}$MODEL_START_CMD > '$LOG_DIR/model.log' 2>&1"
  echo "[ok] started tmux session: $MODEL_TMUX_SESSION"
fi

if tmux has-session -t "$WEB_TMUX_SESSION" 2>/dev/null; then
  echo "[warn] tmux session already exists: $WEB_TMUX_SESSION"
else
  tmux new-session -d -s "$WEB_TMUX_SESSION" "cd '$ROOT_DIR' && ${ACTIVATE_CMD}$PYTHON_CMD -m uvicorn app.main:app --host '$WEB_HOST' --port '$WEB_PORT' > '$LOG_DIR/web.log' 2>&1"
  echo "[ok] started tmux session: $WEB_TMUX_SESSION"
fi

echo
echo "[info] tmux sessions:"
tmux ls || true

echo
echo "[info] recent web log:"
tail -n 20 "$LOG_DIR/web.log" 2>/dev/null || true

echo
echo "[info] recent model log:"
tail -n 20 "$LOG_DIR/model.log" 2>/dev/null || true

echo
echo "[next] verify:"
echo "       curl http://127.0.0.1:${WEB_PORT}/"
echo "       curl http://127.0.0.1:${MODEL_PORT}/v1/models"
echo
echo "[hint] for group demo access, set:"
echo "       WEB_HOST=0.0.0.0 bash scripts/start_web_demo.sh"
echo "[hint] to use conda, set:"
echo "       CONDA_ENV_NAME=academic-impact-web bash scripts/start_web_demo.sh"
