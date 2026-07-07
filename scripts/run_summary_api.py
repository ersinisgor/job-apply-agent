"""Run the LinkedIn Job Summary API (backend for the browser extension).

Usage:
    python scripts/run_summary_api.py
    SUMMARY_API_PORT=8001 python scripts/run_summary_api.py

The extension expects the API on http://localhost:8000 by default. If you change
the port, update extension/background.js (BACKEND_URL) and manifest.json
(host_permissions) accordingly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from src.applyjobs.summary_api import app  # noqa: E402


def main() -> None:
    port = int(os.getenv("SUMMARY_API_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
