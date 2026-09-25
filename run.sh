#!/usr/bin/env bash
# Start Wander. Checks Ollama is up and the model is pulled before serving.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
MODEL="${WANDER_MODEL:-llama3.1:8b}"

if ! curl -sf http://localhost:11434/api/version >/dev/null; then
  echo "Ollama is not running. Start it with:  brew services start ollama"
  exit 1
fi

if ! ollama list | grep -q "${MODEL%%:*}"; then
  echo "Model $MODEL is not pulled. Run:  ollama pull $MODEL"
  exit 1
fi

echo "Wander on http://localhost:$PORT  (model: $MODEL, no cloud, no billing)"
exec env -u PYTHONPATH .venv/bin/python -m uvicorn server.app:app \
  --host 127.0.0.1 --port "$PORT"
