# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two cooperating subsystems for a personal job search:

1. **CV-generation poller** (`src/applyjobs/`, run as `python -m src.applyjobs.main`) — watches a job-application list and produces an ATS-optimized English CV per new job.
2. **LinkedIn Job Summary extension** (`extension/` + `src/applyjobs/summary_api.py`) — a Chrome MV3 extension that reads the selected LinkedIn posting and shows a terse **Turkish** summary + fit score in a side panel, via a local FastAPI backend.

The primary docs (`README.md`, `KULLANIM.md`) are in Turkish. Code identifiers, comments, and commit messages are English; user-facing panel/summary values and sheet-status strings are Turkish.

## Commands

```bash
# Setup
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium

# Full session: summary API + CV poller together (Ctrl+C stops both)
./scripts/start.sh

# Summary API ONLY — use this while browsing LinkedIn (see "Do not automate LinkedIn")
./scripts/start_api.sh
# or directly: ./.venv/bin/python scripts/run_summary_api.py   # uvicorn on :8000

# CV poller (continuous)
./.venv/bin/python -m src.applyjobs.main

# One-shot scan (cron/test)
./.venv/bin/python scripts/run_once.py --dry-run    # list candidates, write nothing
./.venv/bin/python scripts/run_once.py --limit 1    # process at most 1 (first test)
./.venv/bin/python scripts/run_once.py --row 430    # only sheet row 430

# Regenerate a CV-No range from SAVED job descriptions (no re-scrape); override model per-run
CLAUDE_MODEL=claude-opus-4-8 CLAUDE_EFFORT=high ./.venv/bin/python scripts/regenerate.py --from 200 --to 219

# One-time interactive logins (open a browser, then confirm in terminal)
./.venv/bin/python scripts/linkedin_login.py   # -> credentials/linkedin_state.json (scraper guest view; see caveat)
./.venv/bin/python scripts/google_login.py     # -> credentials/oauth_token.json  (Google Doc export)
./.venv/bin/python scripts/huntr_login.py      # -> credentials/huntr_profile/    (only if HUNTR_BOARD_URL set)
```

There is **no test suite and no linter configured**. To sanity-check the extension after edits: `node --check extension/content.js`. The backend cache/scoring logic is verified ad-hoc by importing `src.applyjobs.summary_api` with a stubbed Anthropic client.

**Load the extension:** `chrome://extensions` → Developer mode → Load unpacked → select `extension/`. After changing `extension/*`, click **Reload** there and refresh the LinkedIn tab.

## CV poller architecture (`src/applyjobs/`)

Flow: `main.py` (poll loop) → optional `sync_huntr_to_sheet()` → `run_scan()` in `pipeline.py` → `scraper.py` (Playwright) → `generator.py` (Anthropic) → `docx_builder.py` → `drive_docs.py`, with sheet I/O through `sheets.py`. `config.py` owns all settings/paths (`settings` singleton loaded from `.env`); `reporting.py` logs to `state/agent.log`, appends one-liners to `state/failures.log`, and fires a macOS notification per failure.

Cross-cutting facts that aren't obvious from any single file:

- **The "Google Sheet" is really an `.xlsx` file in Drive.** `sheets.py` downloads it via the Drive API (service account), edits it with **openpyxl**, and re-uploads over the same file id. The openpyxl round-trip drops the user's dropdowns, so `sheets.py` **recreates the data-validation dropdowns** on write. Share the file with the service-account email as Editor.
- **Column N (CV No) is the single source of truth**: filled = done, empty = to do. Deleting a row and re-adding the same job works because the fresh row has an empty N. A candidate needs a link (K), empty N, and a Başvuru (B) not in `SKIP_BASVURU_VALUES`.
- **Per-posting identity / dedup** is the LinkedIn job id parsed from the link (`_job_key`, `.../jobs/view/<id>`), **not** column M — M is a spreadsheet formula, so openpyxl returns the formula text. Each distinct posting yields exactly one CV even if the link appears twice.
- **`CV_GENERATION` off ("info-only")**: new/imported rows still get their scraped fields (C/F/H/J/L) written and column N set to the marker `"Yok"` — the row is handled once and never retro-generated when the switch flips back on.
- **`CV_REVIEW`** (default off) adds a second expert-QA Anthropic pass over each draft.
- **CORE SKILLS is the one CV block with a variable line count.** `ats_prompt.md` lets the model drop the `**Frontend:**` line for a pure back-end posting and keep it for anything front-end-facing, so `_fill_core_skills()` grows/shrinks the template's paragraph slots (like the bullet lists) and takes the **bold label from the markdown** — filling only the content, as it used to, silently shifted every line under the template's original label as soon as a line was added or removed.
- **Huntr import** (only when `HUNTR_BOARD_URL` is set): `huntr.py` drives the logged-in web app and captures the board JSON. State is a persisted set of handled job keys in `state/huntr_seen.json`; the **first run baselines** (imports nothing) to avoid a backlog dump.
- **Google Doc export uses OAuth, not the service account** — a service account can't create files in a personal My Drive. The `.docx` (built from `config/cv_template.docx`) is uploaded with a Google-Doc mimeType so Drive converts it, then exported back as a PDF. Failure here is best-effort and never undoes the already-saved Markdown CV.

### Do not automate the user's LinkedIn session

`scraper.py` reads LinkedIn only in **public guest view**. Never load the user's LinkedIn session cookie (`linkedin_state.json`) into the automated/headless browser: LinkedIn flags the account and invalidates all sessions (constant sign-outs). This is why `start_api.sh` exists — run the summary API alone (no poller/scraper) while actively browsing LinkedIn.

## Summary extension + API

- **`extension/content.js`** injects the panel on `linkedin.com`, extracts the posting text (piercing **open shadow roots + same-origin iframes** via `collectRoots`/`deepQuery`, since the new `/jobs/search-results` UI has hashed CSS classes), and posts it to the backend through `background.js`. Supports both `/jobs/search-results` and standalone `/jobs/view/<id>` pages. A `DEBUG` flag gates all `[JobSum] DIAG` output. "Reviewed" (`İncelendi`) and "Maybe" (`Olabilir`) are two independent `makeMarkerStore` instances persisted in `chrome.storage.local`.
  - **LinkedIn's own dismiss (X) button marks the job reviewed**, matched by `aria-label` (the classes are hashed) in `onDocClick`. The click is read off `event.composedPath()`, which also sees a button inside a shadow root.
  - **A new-UI job card identifies itself only through `componentkey="job-card-component-ref-<id>"`** — it has no `data-job-id` and, crucially, **no `/jobs/view/` link inside the card**. `CARD_SELECTOR` covers both shapes. `cardFrom()`'s last-resort link scan must stop as soon as an ancestor holds **more than one** posting link: without that guard it climbed out of the card into the results list and marked whichever job happened to be first in the DOM.
  - **Description-load timeout**: `content.js` waits for the posting's description to appear in the DOM before calling the backend. If none of the selectors / details-pane fallback / longest-visible-text heuristic yield text within `DESC_LOAD_TIMEOUT_MS` (12s), it stops the spinner, shows a Turkish "scroll + Yenile" hint, and prints **one DIAG dump unconditionally** (the routine per-job DIAG stays gated behind `DEBUG`) — paste that dump to fix the failing layout's selectors. Without this the panel spun forever on a job whose description our selectors all miss.
  - **The longest-visible-text heuristic skips left-list cards** (`LIST_CARD_SELECTOR` — the `data-job-id`-free subset of `CARD_SELECTOR`, since the right-hand details pane can carry `data-job-id`). On a search-results page the longest single text node is otherwise some *other* job's card title, and the heuristic climbs into the wrong posting. Its seed threshold is low (50 chars) because the new UI splits a description into many short lines; the 300-char floor on the assembled container is the real guard against grabbing junk.
  - **`seenOnly`**: a job dismissed from the list before any summary existed is marked so, and is then **never summarized** — re-encountering it shows the ⚠ banner over an explanatory body, costing no model call. Cleared by "Yenile" (an explicit override) and never set when a summary is already cached.
- **`summary_api.py`** calls Claude (model `SUMMARY_MODEL`, default Haiku — separate from the CV `CLAUDE_MODEL`) with **`temperature=0`** and returns the `JobSummary` schema (`summary_schema.py`) as plain JSON (not structured outputs — the 14-field schema exceeded the grammar-compile budget).
  - **`fit_score` compares required technologies ONLY and ignores experience/seniority entirely.** The candidate profile is CV (`config/cv_base.md`) **+ past projects** (`config/projects.md`): a tech counts as known if it appears in either (e.g. Next.js from a project even if absent from the CV).
  - **`stack` is a list of alternative-GROUPS, not a flat list**: `[["Python","Go","Rust"], ["Docker"]]`. An inner list holds options the posting accepts interchangeably ("or", "veya", "or similar"); a one-element group is a hard requirement — most groups are. Within one option string, `/` couples a language to its framework (`"Java / Spring Boot"` — both needed). A `field_validator` re-wraps a flat list if the model regresses to one. `renderStack` gives each multi-option group its own *veya* row and collects **all one-element groups into a single wrapping row** at the bottom.
  - **`stack_known` (parallel `list[list[bool]]`) is filled by the server, never the model**, and drives the green/red chips in the panel. An option counts as known when EVERY `/`-part of it is in the profile; a group is met when ANY option is known. `_profile_mentions()` matches through spelling variants — a trailing version/`.js` is stripped and `_SYNONYM_GROUPS` equates e.g. `REST API`/`RESTful API`, `React`/`React.js`, `Vector Database`/`pgvector`/`Vector Search`, `MSSQL`/`SQL Server` — because a literal-only match kept flagging skills the candidate clearly has (postings and the model word the same tech differently).
  - **`fit_reason` below the green band (score 1-69) is built in Python, not by the model.** `_annotate_stack()` diffs `stack` against the profile and writes the gaps alone (`"Java, Spring Boot ve Kafka deneyimi yok."`) — the user wants no praise and no "ama adayın stack'i X ağırlıklı" clause when the panel paints the score yellow/red. The model handles `stack` well but not the diff (it called PostgreSQL missing while the CV lists it), and prompt-only fixes kept regressing. The model's own clause survives at 70+, at 0, and when nothing is missing. The 70 threshold mirrors `renderFit` in `content.js` — **change both together**.
  - **Result cache** is keyed by LinkedIn `job_id` (not text — the two page types yield slightly different text), LRU-bounded, and mirrored to `state/summary_cache.json` (survives restart). The file is stamped with `_CACHE_VERSION`: **bump it whenever the scoring rubric (`SYSTEM_PROMPT`), the `JobSummary` schema, or the candidate profile (`cv_base.md` / `projects.md`) changes** so stale scores are dropped on load.

## Configuration

All via `.env` (see `.env.example`). Notable: `ANTHROPIC_API_KEY`, `SPREADSHEET_ID` (the Drive `.xlsx` id), `SHEET_NAME` (tab, default `Sayfa1`), `CLAUDE_MODEL` (CV, default `claude-sonnet-4-6`) / `CLAUDE_EFFORT`, `SUMMARY_MODEL` (extension, default `claude-haiku-4-5`), feature flags `CV_GENERATION` / `CV_REVIEW` / `HUNTR_BOARD_URL`, and the output dirs. `credentials/` and `state/` are gitignored.
