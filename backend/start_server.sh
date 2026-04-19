#!/usr/bin/env bash
# Run from backend/: ./start_server.sh
# Prefers ./venv/bin/python when present so Conda/base Python is not used by mistake.
set -e
cd "$(dirname "$0")"
PY="python"
if [ -x "./venv/bin/python" ]; then
  PY="./venv/bin/python"
fi
"$PY" -m pip install -q -r requirements.txt
exec "$PY" -m uvicorn app.main:app --reload --port 8000
