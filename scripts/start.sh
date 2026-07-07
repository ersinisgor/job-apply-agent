#!/usr/bin/env bash
# Start everything for a job-search session with ONE command:
#   - the LinkedIn Job Summary API (backend for the browser extension)
#   - the continuous CV poller (src/applyjobs/main.py)
# Ctrl+C stops both.
#
# Usage:
#   ./scripts/start.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PY=./.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "Virtualenv not found at .venv. Create it and install deps:"
  echo "  python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Starting LinkedIn Job Summary API + CV poller. Press Ctrl+C to stop both."

"$PY" scripts/run_summary_api.py &
API_PID=$!

"$PY" -m src.applyjobs.main &
POLLER_PID=$!

# On exit (Ctrl+C / TERM), stop both child processes.
cleanup() {
  kill "$API_PID" "$POLLER_PID" 2>/dev/null || true
  wait "$API_PID" "$POLLER_PID" 2>/dev/null || true
}
trap cleanup INT TERM

# Wait until either process exits, then stop the other (bash 3.2 compatible).
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$POLLER_PID" 2>/dev/null; do
  sleep 1
done
cleanup
