"""Central configuration: loads .env and resolves project paths.

All other modules import `settings` from here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root = two levels up from this file (src/applyjobs/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

CONFIG_DIR = PROJECT_ROOT / "config"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
STATE_DIR = PROJECT_ROOT / "state"

# Config asset files
CV_BASE_FILE = CONFIG_DIR / "cv_base.md"
PROJECTS_LIST_FILE = CONFIG_DIR / "projects.md"
ATS_PROMPT_FILE = CONFIG_DIR / "ats_prompt.md"
ATS_REVIEW_PROMPT_FILE = CONFIG_DIR / "ats_review_prompt.md"

# Config asset: the .docx template for the Google Docs output
CV_TEMPLATE_FILE = CONFIG_DIR / "cv_template.docx"

# Credential files
SERVICE_ACCOUNT_FILE = CREDENTIALS_DIR / "service_account.json"
LINKEDIN_STATE_FILE = CREDENTIALS_DIR / "linkedin_state.json"
# Huntr login is Google-SSO gated, which blocks automated browsers. We therefore use
# a persistent real-Chrome profile (not a storage_state file) so the session sticks
# and Google's "browser not secure" block is avoided.
HUNTR_PROFILE_DIR = CREDENTIALS_DIR / "huntr_profile"
# OAuth (user) credentials for creating Google Docs in Drive
OAUTH_CLIENT_FILE = CREDENTIALS_DIR / "oauth_client.json"
OAUTH_TOKEN_FILE = CREDENTIALS_DIR / "oauth_token.json"

# State
PROCESSED_STATE_FILE = STATE_DIR / "processed.json"
# Highest Huntr job createdAt we've already accounted for (ISO-8601 string).
HUNTR_CURSOR_FILE = STATE_DIR / "huntr_cursor.txt"

# Values in the "Başvuru" (B) column that should NOT trigger CV generation.
SKIP_BASVURU_VALUES = {"Geçmiş", "Vazgeçildi", "Başvurulmuş", "✓"}


def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "on", "yes", "evet", "açık")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    claude_model: str
    claude_effort: str
    cv_review: bool
    spreadsheet_id: str
    sheet_name: str
    poll_interval: int
    output_dir: Path
    analysis_dir: Path
    job_description_dir: Path
    resumes_folder_name: str
    resumes_folder_id: str
    huntr_board_url: str
    huntr_poll_interval: int

    @classmethod
    def load(cls) -> "Settings":
        default_output = "~/Desktop/İş Arama/Job Applications/2026/CVs"
        default_analysis = "~/Desktop/İş Arama/Job Applications/2026/CV_Analysis"
        default_jd = "~/Desktop/İş Arama/Job Applications/2026/Job Description"
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
            # Reasoning effort: none / low / medium / high (extended thinking budget).
            claude_effort=os.getenv("CLAUDE_EFFORT", "none").strip().lower(),
            # Second expert QA pass on each CV (OFF by default: the verify/fix
            # checklist is folded into the single generation prompt, STEP 12).
            cv_review=_env_bool("CV_REVIEW", False),
            spreadsheet_id=os.getenv("SPREADSHEET_ID", ""),
            sheet_name=os.getenv("SHEET_NAME", "Sayfa1"),
            poll_interval=int(os.getenv("POLL_INTERVAL", "60")),
            output_dir=_expand(os.getenv("OUTPUT_DIR", default_output)),
            analysis_dir=_expand(os.getenv("ANALYSIS_DIR", default_analysis)),
            job_description_dir=_expand(os.getenv("JOB_DESCRIPTION_DIR", default_jd)),
            resumes_folder_name=os.getenv("RESUMES_FOLDER_NAME", "Resumes Based on Jobs"),
            resumes_folder_id=os.getenv("RESUMES_FOLDER_ID", ""),
            # Huntr is OFF unless a board URL is provided (feature flag).
            huntr_board_url=os.getenv("HUNTR_BOARD_URL", ""),
            huntr_poll_interval=int(os.getenv("HUNTR_POLL_INTERVAL", "30")),
        )

    def validate(self) -> None:
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.spreadsheet_id:
            missing.append("SPREADSHEET_ID")
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill them in."
            )
        if not SERVICE_ACCOUNT_FILE.exists():
            raise RuntimeError(
                f"Service account key not found at {SERVICE_ACCOUNT_FILE}. "
                f"Create one in Google Cloud and share the sheet with its email."
            )

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.job_description_dir.mkdir(parents=True, exist_ok=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings.load()
