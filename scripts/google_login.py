"""One-time OAuth login so the agent can create Google Docs in your Drive.

Prerequisite: download an OAuth client ID (type "Desktop app") from Google Cloud
Console and save it as credentials/oauth_client.json.

Usage:
    python scripts/google_login.py

A browser opens for you to grant access. The resulting token (with a refresh token
for unattended use) is saved to credentials/oauth_token.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from src.applyjobs.config import OAUTH_CLIENT_FILE, OAUTH_TOKEN_FILE  # noqa: E402
from src.applyjobs.drive_docs import SCOPES  # noqa: E402


def main() -> None:
    if not OAUTH_CLIENT_FILE.exists():
        raise SystemExit(
            f"Missing {OAUTH_CLIENT_FILE}.\n"
            f"Create an OAuth client ID (Desktop app) in Google Cloud Console, "
            f"download the JSON, and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    OAUTH_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved OAuth token to {OAUTH_TOKEN_FILE}")


if __name__ == "__main__":
    main()
