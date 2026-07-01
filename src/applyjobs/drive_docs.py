"""Upload the generated .docx to Drive as a native Google Doc, via OAuth.

A service account cannot create files in a personal My Drive (storageQuotaExceeded),
so Google Doc creation uses the user's own OAuth credentials. The .docx bytes are
uploaded with the target mimeType `application/vnd.google-apps.document`, which makes
Drive convert it to a real Google Doc inside the "Resumes Based on Jobs" folder.

The same client can then export that Doc back as a PDF (`export_as_pdf`) so a local
PDF copy can be saved.
"""
from __future__ import annotations

import io
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from .config import OAUTH_TOKEN_FILE, settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GDOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _load_credentials() -> Credentials:
    if not OAUTH_TOKEN_FILE.exists():
        raise RuntimeError(
            f"OAuth token not found at {OAUTH_TOKEN_FILE}. "
            f"Run: python scripts/google_login.py"
        )
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_FILE), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            OAUTH_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "OAuth token invalid/expired and cannot refresh. "
                "Re-run: python scripts/google_login.py"
            )
    return creds


class DriveDocsClient:
    def __init__(self) -> None:
        self._drive = build("drive", "v3", credentials=_load_credentials(), cache_discovery=False)

    def _find_folder_id(self) -> str:
        if settings.resumes_folder_id:
            return settings.resumes_folder_id
        name = settings.resumes_folder_name.replace("'", "\\'")
        q = (
            f"name = '{name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        )
        resp = self._drive.files().list(
            q=q, fields="files(id,name)", spaces="drive", pageSize=10
        ).execute()
        files = resp.get("files", [])
        if not files:
            raise RuntimeError(
                f"Drive folder '{settings.resumes_folder_name}' not found. "
                f"Create it or set RESUMES_FOLDER_ID in .env."
            )
        return files[0]["id"]

    def _find_existing(self, name: str, folder_id: str) -> str | None:
        safe = name.replace("'", "\\'")
        q = f"name = '{safe}' and '{folder_id}' in parents and trashed = false"
        resp = self._drive.files().list(
            q=q, fields="files(id,name)", spaces="drive", pageSize=10
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def export_as_pdf(self, file_id: str) -> bytes:
        """Export a Google Doc as PDF bytes (Google's own Doc->PDF conversion).

        Uses files().export, which is fine for the small CV Docs (the export endpoint
        caps at ~10 MB of exported content).
        """
        return self._drive.files().export(
            fileId=file_id, mimeType="application/pdf"
        ).execute()

    def upload_as_google_doc(self, docx_bytes: bytes, name: str) -> str:
        """Create (or update) a Google Doc named `name` from the .docx. Returns file id."""
        folder_id = self._find_folder_id()
        media = MediaIoBaseUpload(io.BytesIO(docx_bytes), mimetype=DOCX_MIME, resumable=True)

        existing = self._find_existing(name, folder_id)
        if existing:
            file = self._drive.files().update(
                fileId=existing, media_body=media, fields="id,webViewLink"
            ).execute()
            logger.info("Updated Google Doc '%s' (%s)", name, file.get("webViewLink", ""))
        else:
            metadata = {"name": name, "mimeType": GDOC_MIME, "parents": [folder_id]}
            file = self._drive.files().create(
                body=metadata, media_body=media, fields="id,webViewLink"
            ).execute()
            logger.info("Created Google Doc '%s' (%s)", name, file.get("webViewLink", ""))
        return file["id"]


def upload_as_google_doc(docx_bytes: bytes, name: str) -> str:
    """Convenience wrapper."""
    return DriveDocsClient().upload_as_google_doc(docx_bytes, name)
