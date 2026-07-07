// Reads the selected job on the LinkedIn jobs page, gets a Turkish summary from the
// Python backend, and shows it in a side panel. The panel updates as the job changes.
//
// SECURITY NOTE: this script makes NO extra network requests to LinkedIn. It only
// reads the job text already visible on the page and sends it, for summarization,
// SOLELY to its own localhost backend. (An earlier version had a hover/prefetch that
// called LinkedIn's internal API; that was detected as automation and caused sign-outs,
// so it was removed.)

(() => {
  "use strict";

  const LOG = "[JobSum]";
  console.log(LOG, "content script loaded:", location.href);

  // --- LinkedIn DOM selectors (brittle; tried in order, first match wins) ---
  const SELECTORS = {
    description: [
      "#job-details",
      ".jobs-description__content .jobs-box__html-content",
      ".jobs-description-content__text",
      "article.jobs-description__container",
      ".jobs-description__container",
      ".jobs-box__html-content",
    ],
    title: [
      ".job-details-jobs-unified-top-card__job-title",
      ".jobs-unified-top-card__job-title",
      ".job-details-jobs-unified-top-card__job-title h1",
    ],
    company: [
      ".job-details-jobs-unified-top-card__company-name",
      ".jobs-unified-top-card__company-name",
    ],
    location: [
      ".job-details-jobs-unified-top-card__primary-description-container",
      ".jobs-unified-top-card__primary-description",
      ".job-details-jobs-unified-top-card__tertiary-description-container",
    ],
  };

  // Panel field order and labels (labels English; values come from Claude in Turkish).
  const FIELDS = [
    { key: "role_summary", label: "Role Summary" },
    { key: "work_type", label: "Work Type" },
    { key: "work_type_note", label: "Work Type Note" },
    { key: "visa_sponsorship", label: "Visa / Sponsorship" },
    { key: "primary_language", label: "Primary Language" },
    { key: "secondary_language", label: "Secondary Language (Bonus)" },
    { key: "tools", label: "Tools" },
    { key: "frameworks", label: "Frameworks" },
    { key: "libraries", label: "Libraries" },
    { key: "min_experience", label: "Min. Experience" },
  ];

  let lastJobId = null; // most recently shown job id
  let pendingJobId = null; // job waiting for its description to load
  let lastShownDescription = ""; // description of the shown job (stale guard)
  let requestSeq = 0; // request sequence to avoid race conditions
  let lastBodyHtml = `<div class="jobsum-status">Ready — click a job on the left.</div>`;
  let userClosed = false; // don't reopen if the user closed the panel

  // Per-job summary cache: returning to a job shows it instantly.
  const CACHE = new Map(); // jobId -> { summary, description }
  const CACHE_LIMIT = 60;

  function cacheSet(jobId, summary, description) {
    CACHE.set(jobId, { summary, description });
    if (CACHE.size > CACHE_LIMIT) {
      CACHE.delete(CACHE.keys().next().value); // drop oldest
    }
  }

  // --- Helpers ---

  function firstMatchText(selectorList) {
    for (const sel of selectorList) {
      const el = document.querySelector(sel);
      if (el) {
        const text = el.innerText.trim();
        if (text) return text;
      }
    }
    return "";
  }

  function getCurrentJobId() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("currentJobId");
    if (fromUrl) return fromUrl;

    const selected = document.querySelector(
      ".jobs-search-results-list__list-item--active [data-job-id], li.jobs-search-results__list-item.active [data-occludable-job-id], .job-card-container--active [data-job-id]"
    );
    if (selected) {
      return (
        selected.getAttribute("data-job-id") ||
        selected.getAttribute("data-occludable-job-id")
      );
    }
    return null;
  }

  // --- Panel: appended under <html>, re-created if removed ---

  function buildPanel() {
    const panel = document.createElement("div");
    panel.id = "jobsum-panel";
    panel.innerHTML = `
      <div id="jobsum-header">
        <span id="jobsum-title">Job Summary</span>
        <button id="jobsum-close" title="Close" aria-label="Close">×</button>
      </div>
      <div id="jobsum-body">${lastBodyHtml}</div>
    `;
    panel.querySelector("#jobsum-close").addEventListener("click", () => {
      userClosed = true;
      panel.remove();
    });
    return panel;
  }

  function ensurePanel() {
    if (userClosed) return null;
    let panel = document.getElementById("jobsum-panel");
    if (!panel) {
      panel = buildPanel();
      document.documentElement.appendChild(panel);
      console.log(LOG, "panel added");
    }
    return panel;
  }

  function setBody(html) {
    lastBodyHtml = html;
    const panel = ensurePanel();
    if (!panel) return;
    panel.querySelector("#jobsum-body").innerHTML = html;
  }

  function showLoading() {
    setBody(`<div class="jobsum-status">Preparing summary…</div>`);
  }

  function showError(message) {
    setBody(`<div class="jobsum-status jobsum-error">${escapeHtml(message)}</div>`);
  }

  function renderSummary(data) {
    const rows = FIELDS.map((field) => {
      const rendered = renderValue(data[field.key]);
      if (rendered === null) return "";
      return `
        <div class="jobsum-row">
          <div class="jobsum-label">${escapeHtml(field.label)}</div>
          <div class="jobsum-value">${rendered}</div>
        </div>`;
    }).join("");
    setBody(rows || `<div class="jobsum-status">No information to summarize.</div>`);
  }

  function renderValue(value) {
    if (value === null || value === undefined) return null;
    if (Array.isArray(value)) {
      if (value.length === 0) return null;
      return value
        .map((v) => `<span class="jobsum-chip">${escapeHtml(String(v))}</span>`)
        .join(" ");
    }
    const str = String(value).trim();
    if (!str || str.toLowerCase() === "unspecified") return null;
    return escapeHtml(str);
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // --- Main flow ---

  // Summary call to the backend (only to our own localhost service).
  function callBackend(payload) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "SUMMARIZE", payload }, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error("Extension messaging error. Reload the page."));
          return;
        }
        if (!response) {
          reject(new Error("No response from backend."));
          return;
        }
        if (!response.ok) {
          reject(new Error(response.error || "Unknown error."));
          return;
        }
        resolve(response.data);
      });
    });
  }

  function requestSummary(jobId, description) {
    const payload = {
      text: description,
      title: firstMatchText(SELECTORS.title) || null,
      company: firstMatchText(SELECTORS.company) || null,
      location: firstMatchText(SELECTORS.location) || null,
    };

    const seq = ++requestSeq;
    console.log(LOG, "requesting summary:", payload.title || "(no title)");

    callBackend(payload)
      .then((data) => {
        cacheSet(jobId, data, description);
        if (seq !== requestSeq || jobId !== lastJobId) return; // switched jobs meanwhile
        console.log(LOG, "summary received");
        renderSummary(data);
      })
      .catch((err) => {
        if (seq !== requestSeq || jobId !== lastJobId) return;
        console.warn(LOG, "error:", err.message);
        showError(err.message);
      });
  }

  function maybeUpdate() {
    ensurePanel(); // re-add the panel if it was removed

    const jobId = getCurrentJobId();
    if (!jobId) return;

    // Switched to a new job: give instant feedback first.
    if (jobId !== lastJobId) {
      lastJobId = jobId;
      const cached = CACHE.get(jobId);
      if (cached) {
        console.log(LOG, "from cache:", jobId);
        pendingJobId = null;
        lastShownDescription = cached.description;
        renderSummary(cached.summary); // instant
        return;
      }
      console.log(LOG, "new job detected:", jobId);
      pendingJobId = jobId;
      showLoading(); // clear the old summary immediately
    }

    // Summarize once the pending job's description has loaded.
    if (pendingJobId) {
      const description = firstMatchText(SELECTORS.description);
      if (
        description &&
        description.length >= 40 &&
        description !== lastShownDescription // don't summarize stale (old) text
      ) {
        const targetJob = pendingJobId;
        pendingJobId = null;
        lastShownDescription = description;
        requestSummary(targetJob, description);
      }
    }
  }

  // --- Change detection ---

  let debounceTimer = null;
  function scheduleUpdate() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(maybeUpdate, 120);
  }

  const observer = new MutationObserver(scheduleUpdate);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  setInterval(maybeUpdate, 700);

  ensurePanel();
  scheduleUpdate();
})();
