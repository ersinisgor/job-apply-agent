#!/usr/bin/env bash
# Start ONLY the LinkedIn Job Summary API (backend for the browser extension),
# without the CV poller. Use this while browsing LinkedIn: the poller scrapes
# LinkedIn job pages with a headless browser, and that automation traffic from
# your own IP keeps the account flagged (constant sign-outs).
#
# Usage:
#   ./scripts/start_api.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PY=./.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "Virtualenv not found at .venv. Create it and install deps:"
  echo "  python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Starting LinkedIn Job Summary API only (no CV poller). Press Ctrl+C to stop."
exec "$PY" scripts/run_summary_api.py
