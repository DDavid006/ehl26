#!/usr/bin/env bash
# Start the patentability analyser locally on http://localhost:8000
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
./.venv/bin/pip install -q -r requirements.txt

if [ -f frontend/package.json ]; then
  (cd frontend && npm install && npm run build)
fi

exec ./.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
