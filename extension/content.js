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
      // guest (logged-out) view
      ".show-more-less-html__markup",
      ".description__text",
    ],
    // Right-hand details pane; used as a raw-text fallback when the description
    // selectors above stop matching (LinkedIn changes its DOM often). The backend
    // LLM tolerates the extra chrome text around the description.
    detailsPane: [
      ".jobs-search__job-details--wrapper",
      ".jobs-search__job-details",
      ".scaffold-layout__detail",
      ".jobs-details",
      ".job-view-layout",
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

  // Panel field order and labels. Deliberately minimal: one glance should be
  // enough to decide whether the job fits. "work" is composed client-side from
  // work_type + work_type_note (single row, e.g. "on-site — İstanbul tercihli").
  const FIELDS = [
    { key: "role_summary", label: "Özet" },
    { key: "work", label: "Çalışma" },
    { key: "stack", label: "Stack" },
    { key: "min_experience", label: "Deneyim" },
    { key: "visa_sponsorship", label: "Vize / Sponsorluk" }, // shown only when present
  ];

  let lastJobId = null; // most recently shown job id
  let pendingJobId = null; // job waiting for its description to load
  let lastShownDescription = ""; // description of the shown job (stale guard)
  let requestSeq = 0; // request sequence to avoid race conditions
  let lastBodyHtml = `<div class="jobsum-status">Ready — click a job on the left.</div>`;
  let lastHeader = { title: "Job Summary", company: "" }; // panel header state
  let userClosed = false; // don't reopen if the user closed the panel
  let warnedNoSelectorFor = null; // log the missing-description warning once per job

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

  // Fallback: when no description selector matches, take the whole details
  // pane's text (capped) — resilient to LinkedIn DOM changes.
  function fallbackDescription() {
    for (const sel of SELECTORS.detailsPane) {
      const el = document.querySelector(sel);
      if (el) {
        const text = el.innerText.trim();
        if (text.length >= 200) return text.slice(0, 15000);
      }
    }
    return "";
  }

  // Last-resort fallback for unknown layouts (e.g. the new /jobs/search-results
  // UI): find the longest VISIBLE text node on the page (almost always a job
  // description paragraph), then climb to the largest container that still looks
  // like a content pane (not the whole page). LinkedIn hides JSON blobs in
  // <code> tags, so hidden nodes must be skipped.
  function findLongestVisibleTextEl() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let best = null;
    let bestLen = 0;
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent) continue;
      const len = node.textContent.trim().length;
      if (len <= bestLen) continue;
      if (parent.closest("#jobsum-panel,code,script,style,noscript,template")) continue;
      if (parent.checkVisibility && !parent.checkVisibility()) continue;
      best = parent;
      bestLen = len;
    }
    return { el: best, len: bestLen };
  }

  function heuristicDescription() {
    const { el: start, len } = findLongestVisibleTextEl();
    if (!start || len < 150) return ""; // no paragraph-sized visible text yet
    let el = start;
    while (el.parentElement && el.parentElement !== document.body) {
      const parentLen = (el.parentElement.innerText || "").trim().length;
      if (parentLen > 12000) break; // don't swallow the whole page
      el = el.parentElement;
    }
    const text = (el.innerText || "").trim();
    return text.length >= 300 ? text.slice(0, 15000) : "";
  }

  // Log the DOM around the longest visible text so failing selectors can be
  // fixed from a pasted console dump (one shot per job).
  function logDomDiagnosis() {
    const { el: best, len } = findLongestVisibleTextEl();
    if (!best) {
      console.warn(LOG, "DIAG: no visible text node found at all");
    } else {
      console.warn(
        LOG,
        `DIAG longest visible text: ${len} chars:`,
        best.textContent.trim().slice(0, 100)
      );
      let el = best;
      const chain = [];
      while (el && el !== document.body && chain.length < 10) {
        const cls = String(
          el.className && el.className.baseVal !== undefined
            ? el.className.baseVal
            : el.className || ""
        ).slice(0, 100);
        const textLen = (el.innerText || "").trim().length;
        chain.push(
          `<${el.tagName.toLowerCase()}> id=${el.id || "-"} class=${cls || "-"} len=${textLen}`
        );
        el = el.parentElement;
      }
      console.warn(LOG, "DIAG ancestor chain:\n" + chain.join("\n"));
    }
    let shadows = 0;
    document.querySelectorAll("*").forEach((e) => {
      if (e.shadowRoot) shadows += 1;
    });
    console.warn(
      LOG,
      `DIAG iframes=${document.querySelectorAll("iframe").length} shadowRoots=${shadows}`
    );
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
        <div id="jobsum-heading">
          <span id="jobsum-title">${escapeHtml(lastHeader.title)}</span>
          <span id="jobsum-company">${escapeHtml(lastHeader.company)}</span>
        </div>
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

  // Header: position title on top, company underneath (like LinkedIn's top card).
  // Falls back to the static "Job Summary" label until a job is summarized.
  function setHeader(title, company) {
    lastHeader = {
      title: (title || "").trim() || "Job Summary",
      company: (company || "").trim(),
    };
    const panel = ensurePanel();
    if (!panel) return;
    panel.querySelector("#jobsum-title").textContent = lastHeader.title;
    panel.querySelector("#jobsum-company").textContent = lastHeader.company;
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
    // Prefer what Claude extracted from the posting; fall back to the DOM
    // selectors (which only match LinkedIn's old UI).
    setHeader(
      data.job_title || firstMatchText(SELECTORS.title),
      data.company || firstMatchText(SELECTORS.company)
    );
    // Compose the single-row work field: "on-site — İstanbul tercihli".
    const workType =
      data.work_type && data.work_type !== "unspecified" ? data.work_type : "";
    data = { ...data, work: [workType, data.work_type_note].filter(Boolean).join(" — ") };
    const rows = FIELDS.map((field) => {
      const rendered = renderValue(data[field.key]);
      if (rendered === null) return "";
      return `
        <div class="jobsum-row">
          <div class="jobsum-label">${escapeHtml(field.label)}</div>
          <div class="jobsum-value">${rendered}</div>
        </div>`;
    }).join("");
    setBody(
      renderFit(data.fit_score, data.fit_reason) +
        (rows || `<div class="jobsum-status">No information to summarize.</div>`)
    );
  }

  // Fit badge at the top: colored %NN + one-line reason. Hidden when no score.
  function renderFit(score, reason) {
    const n = Math.round(Number(score) || 0);
    if (n <= 0) return "";
    const band = n >= 70 ? "high" : n >= 40 ? "mid" : "low";
    const reasonHtml = reason
      ? `<span class="jobsum-fit-reason">${escapeHtml(String(reason))}</span>`
      : "";
    return `
      <div class="jobsum-fit jobsum-fit--${band}">
        <div class="jobsum-label">Uygunluk</div>
        <div class="jobsum-fit-body">
          <span class="jobsum-fit-score">%${n}</span>
          ${reasonHtml}
        </div>
      </div>`;
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
      setHeader("", ""); // drop the previous job's title while loading
      showLoading(); // clear the old summary immediately
    }

    // Summarize once the pending job's description has loaded.
    if (pendingJobId) {
      let description = firstMatchText(SELECTORS.description);
      if (!description) {
        description = fallbackDescription();
        if (description && warnedNoSelectorFor !== pendingJobId) {
          warnedNoSelectorFor = pendingJobId;
          console.warn(
            LOG,
            "description selectors matched nothing; using details-pane fallback"
          );
        }
      }
      if (!description) {
        description = heuristicDescription();
        if (warnedNoSelectorFor !== pendingJobId) {
          warnedNoSelectorFor = pendingJobId;
          console.warn(
            LOG,
            description
              ? "selectors + pane fallback empty; using longest-text heuristic"
              : "no description found yet (selectors + fallbacks empty)"
          );
          logDomDiagnosis();
        }
      }
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
