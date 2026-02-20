#!/usr/bin/env bash
# With venv already activated: use the same Python to run uvicorn (avoids wrong interpreter).
# Run from backend/:  ./start_server.sh
set -e
cd "$(dirname "$0")"
python -m pip install -q -r requirements.txt
exec python -m uvicorn app.main:app --reload --port 8000
