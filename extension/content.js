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
  let showingList = false; // panel is showing the reviewed-jobs list instead of a summary

  // Per-job summary cache: returning to a job shows it instantly.
  const CACHE = new Map(); // jobId -> { summary, description }
  const CACHE_LIMIT = 60;

  function cacheSet(jobId, summary, description) {
    CACHE.set(jobId, { summary, description });
    if (CACHE.size > CACHE_LIMIT) {
      CACHE.delete(CACHE.keys().next().value); // drop oldest
    }
  }

  // --- Persistent "reviewed" memory -----------------------------------------
  // LinkedIn's dismiss (X) state is per-search, so the same posting reappears
  // un-dismissed in other job-alert lists. We keep our own memory keyed by the
  // canonical posting id (stable across searches) in chrome.storage.local, and
  // warn when a reviewed posting shows up again.

  const STORE_KEY = "jobsum_reviewed";
  const REVIEWED_LIMIT = 3000; // cap; prune oldest by timestamp on write
  let reviewedMap = {}; // jobId -> { t, title, company, fit }

  function loadReviewed() {
    try {
      chrome.storage.local.get(STORE_KEY, (res) => {
        if (chrome.runtime.lastError) return;
        reviewedMap = res && res[STORE_KEY] ? res[STORE_KEY] : {};
        scheduleUpdate(); // reflect loaded state in the list/panel
      });
    } catch (_) {
      /* storage unavailable; feature just stays inert */
    }
  }

  // Keep in sync if another tab changes the store.
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes[STORE_KEY]) {
        reviewedMap = changes[STORE_KEY].newValue || {};
        scheduleUpdate();
      }
    });
  } catch (_) {
    /* ignore */
  }

  function persistReviewed() {
    // Prune to the newest REVIEWED_LIMIT entries by timestamp.
    const ids = Object.keys(reviewedMap);
    if (ids.length > REVIEWED_LIMIT) {
      ids
        .sort((a, b) => (reviewedMap[a].t || 0) - (reviewedMap[b].t || 0))
        .slice(0, ids.length - REVIEWED_LIMIT)
        .forEach((id) => delete reviewedMap[id]);
    }
    try {
      chrome.storage.local.set({ [STORE_KEY]: reviewedMap });
    } catch (_) {
      /* ignore */
    }
  }

  function isReviewed(jobId) {
    return !!(jobId && reviewedMap[jobId]);
  }

  function markReviewed(jobId, meta) {
    if (!jobId) return;
    const existing = reviewedMap[jobId];
    reviewedMap[jobId] = {
      t: existing && existing.t ? existing.t : Date.now(), // keep first-seen time
      title: (meta && meta.title) || (existing && existing.title) || "",
      company: (meta && meta.company) || (existing && existing.company) || "",
      fit: meta && meta.fit != null ? meta.fit : existing ? existing.fit : null,
    };
    persistReviewed();
    console.log(LOG, "marked reviewed:", jobId);
    scheduleUpdate();
  }

  function unmarkReviewed(jobId) {
    if (!jobId || !reviewedMap[jobId]) return;
    delete reviewedMap[jobId];
    persistReviewed();
    console.log(LOG, "unmarked:", jobId);
    scheduleUpdate();
  }

  // Turkish relative time for "you saw this N ago".
  function relativeTime(t) {
    const mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
    if (mins < 1) return "az önce";
    if (mins < 60) return `${mins} dk önce`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} saat önce`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} gün önce`;
    const weeks = Math.floor(days / 7);
    return `${weeks} hafta önce`;
  }

  // --- Helpers ---

  // LinkedIn's newer jobs UI renders the job pane inside open shadow roots and
  // same-origin iframes, which plain document.querySelector / TreeWalker cannot
  // reach. collectRoots() returns the main document plus every nested open
  // shadow root and readable (same-origin) iframe document, so all the text
  // extraction below can pierce those boundaries. Cross-origin iframes throw on
  // access and are silently skipped.
  function collectRoots() {
    const roots = [document];
    for (let i = 0; i < roots.length; i++) {
      const root = roots[i];
      let all;
      try {
        all = root.querySelectorAll("*");
      } catch (_) {
        continue;
      }
      all.forEach((el) => {
        if (el.shadowRoot) roots.push(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          let doc = null;
          try {
            doc = el.contentDocument;
          } catch (_) {
            /* cross-origin; not readable */
          }
          if (doc) roots.push(doc);
        }
      });
    }
    return roots;
  }

  function deepQuery(selector, roots) {
    for (const root of roots || collectRoots()) {
      let el = null;
      try {
        el = root.querySelector(selector);
      } catch (_) {
        /* invalid selector for this root type; skip */
      }
      if (el) return el;
    }
    return null;
  }

  function firstMatchText(selectorList) {
    const roots = collectRoots();
    for (const sel of selectorList) {
      const el = deepQuery(sel, roots);
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
    const roots = collectRoots();
    for (const sel of SELECTORS.detailsPane) {
      const el = deepQuery(sel, roots);
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
    let best = null;
    let bestLen = 0;
    for (const root of collectRoots()) {
      const scope = root.body || root; // Document -> body; ShadowRoot -> itself
      if (!scope) continue;
      const doc = root.ownerDocument || root; // owning Document for createTreeWalker
      let walker;
      try {
        walker = doc.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
      } catch (_) {
        continue;
      }
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
    const roots = collectRoots();
    const readableIframes = roots.filter(
      (r) => r.nodeType === 9 && r !== document
    ).length;
    const shadows = roots.filter((r) => r.nodeType === 11).length;
    const totalIframes = document.querySelectorAll("iframe").length;
    console.warn(
      LOG,
      `DIAG iframes=${totalIframes} (readable=${readableIframes}) ` +
        `shadowRoots=${shadows} rootsSearched=${roots.length}`
    );
  }

  // After the extension is reloaded/updated, the content script already injected
  // in open tabs becomes orphaned: its runtime is dead but its interval/observer
  // keep running, spamming "chrome-extension://invalid/" errors every tick. Detect
  // that and self-destruct (see teardown() at the bottom).
  function extensionAlive() {
    try {
      return typeof chrome !== "undefined" && !!chrome.runtime && !!chrome.runtime.id;
    } catch (_) {
      return false; // accessing chrome.runtime throws once the context is gone
    }
  }

  // The content script is injected on every LinkedIn page (so it survives SPA
  // navigation into the jobs view in any tab), but the panel and its work only
  // belong on the jobs pages.
  function isJobsPage() {
    return location.pathname.startsWith("/jobs/");
  }

  function getCurrentJobId() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("currentJobId");
    if (fromUrl) return fromUrl;

    // Standalone job page (/jobs/view/<id>/…): the id lives in the path, and
    // there is no list card to read it from.
    const fromPath = location.pathname.match(/\/jobs\/view\/(\d+)/);
    if (fromPath) return fromPath[1];

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

  function cardJobId(el) {
    const card = el.closest("[data-job-id], [data-occludable-job-id]");
    if (!card) return null;
    return (
      card.getAttribute("data-job-id") ||
      card.getAttribute("data-occludable-job-id")
    );
  }

  // Best-effort title/company from a job card's own text (first two lines).
  function cardMeta(el) {
    const card = el.closest("[data-job-id], [data-occludable-job-id]");
    if (!card) return {};
    const lines = (card.innerText || "")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    return { title: lines[0] || "", company: lines[1] || "" };
  }

  // Detect clicks on LinkedIn's own dismiss (X) / undo (↩️) buttons. aria-label
  // is LinkedIn's most stable signal (the CSS classes are hashed). The panel
  // toggle is the reliable fallback if these patterns miss a locale.
  const DISMISS_RE = /dismiss|yoksay|gizle|kapat|not interested|ilgilenmiyorum/i;
  const UNDO_RE = /undo|geri al|geri getir/i;
  const warnedLabels = new Set(); // distinct unmatched aria-labels, capped

  function onDocClick(event) {
    const btn = event.target.closest("button");
    if (!btn) return;
    const jobId = cardJobId(btn);
    if (!jobId) return; // not a button inside a job card
    const label = (btn.getAttribute("aria-label") || btn.title || "").trim();
    if (UNDO_RE.test(label)) {
      unmarkReviewed(jobId);
    } else if (DISMISS_RE.test(label)) {
      markReviewed(jobId, { ...cardMeta(btn), fit: cachedFit(jobId) });
    } else if (label && warnedLabels.size < 8 && !warnedLabels.has(label)) {
      // Help tune DISMISS_RE/UNDO_RE for the user's locale during verification.
      warnedLabels.add(label);
      console.warn(LOG, "card button click, unmatched aria-label:", label);
    }
  }

  function cachedFit(jobId) {
    const c = CACHE.get(jobId);
    return c && c.summary ? c.summary.fit_score : null;
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
        <div id="jobsum-actions">
          <button id="jobsum-refresh" type="button" title="Özeti yeniden oluştur" aria-label="Özeti yeniden oluştur">Yenile</button>
          <button id="jobsum-list" type="button" title="İşaretli ilanlar" aria-label="İşaretli ilanlar">Liste</button>
          <button id="jobsum-close" title="Close" aria-label="Close">×</button>
        </div>
      </div>
      <div id="jobsum-review"></div>
      <div id="jobsum-body">${lastBodyHtml}</div>
    `;
    panel.querySelector("#jobsum-close").addEventListener("click", () => {
      userClosed = true;
      panel.remove();
    });
    panel.querySelector("#jobsum-refresh").addEventListener("click", refreshSummary);
    panel.querySelector("#jobsum-list").addEventListener("click", toggleList);
    panel.querySelector("#jobsum-list").classList.toggle("is-active", showingList);
    return panel;
  }

  // --- Reviewed-jobs list view ----------------------------------------------
  // A permanent "Liste" button in the header toggles a list of every reviewed
  // posting (title/company/when) with a link to LinkedIn's canonical job URL —
  // useful when a marked job can no longer be found via search.

  function reviewedJobUrl(jobId) {
    return `https://www.linkedin.com/jobs/view/${encodeURIComponent(jobId)}/`;
  }

  function renderReviewedList() {
    const entries = Object.entries(reviewedMap).sort(
      (a, b) => (b[1].t || 0) - (a[1].t || 0)
    );
    if (!entries.length) {
      return `<div class="jobsum-status">Henüz işaretli ilan yok.</div>`;
    }
    const items = entries
      .map(([id, v]) => {
        const title = escapeHtml(v.title || `İlan ${id}`);
        const company = escapeHtml(v.company || "");
        const when = v.t ? escapeHtml(relativeTime(v.t)) : "";
        const sub = [company, when].filter(Boolean).join(" · ");
        return `
        <div class="jobsum-listitem">
          <a href="${reviewedJobUrl(id)}" target="_blank" rel="noopener">
            <span class="jobsum-listitem-title">${title}</span>
            <span class="jobsum-listitem-sub">${sub}</span>
          </a>
          <button class="jobsum-listitem-remove" type="button" data-jid="${escapeHtml(
            id
          )}" title="Kaldır" aria-label="Kaldır">×</button>
        </div>`;
      })
      .join("");
    return `<div class="jobsum-listhead">İşaretli ilanlar (${entries.length})</div>${items}`;
  }

  function attachListHandlers() {
    const panel = document.getElementById("jobsum-panel");
    if (!panel) return;
    panel.querySelectorAll(".jobsum-listitem-remove").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        unmarkReviewed(btn.getAttribute("data-jid"));
        if (showingList) {
          setBody(renderReviewedList()); // refresh the list in place
          attachListHandlers();
        }
      });
    });
  }

  function toggleList() {
    showingList = !showingList;
    const btn = document.getElementById("jobsum-list");
    if (btn) btn.classList.toggle("is-active", showingList);
    if (showingList) {
      setBody(renderReviewedList());
      attachListHandlers();
    } else {
      // Return to the summary view: force a re-render of the current job.
      reviewRenderKey = null;
      lastJobId = null;
      scheduleUpdate();
    }
  }

  // Review status block (under the header): warning banner + mark/unmark toggle
  // for the current job. Re-rendered only when the (job, reviewed) state changes.
  let reviewRenderKey = null;
  function renderReviewStatus(jobId) {
    const panel = ensurePanel();
    if (!panel) return;
    const slot = panel.querySelector("#jobsum-review");
    if (!slot) return;

    const key = `${jobId || ""}:${isReviewed(jobId)}`;
    if (key === reviewRenderKey) return; // nothing changed
    reviewRenderKey = key;

    if (!jobId) {
      slot.innerHTML = "";
      return;
    }

    if (isReviewed(jobId)) {
      const when = relativeTime(reviewedMap[jobId].t || Date.now());
      slot.className = "jobsum-review jobsum-review--seen";
      slot.innerHTML = `
        <span class="jobsum-review-text">⚠ Bu ilanı ${escapeHtml(when)} gördün</span>
        <button class="jobsum-review-btn jobsum-review-btn--undo" type="button">Geri al</button>`;
      slot.querySelector("button").addEventListener("click", () => {
        unmarkReviewed(jobId);
      });
    } else {
      slot.className = "jobsum-review";
      slot.innerHTML = `
        <button class="jobsum-review-btn" type="button">İncelendi</button>`;
      slot.querySelector("button").addEventListener("click", () => {
        const c = CACHE.get(jobId);
        markReviewed(jobId, {
          title: (c && c.summary && c.summary.job_title) || lastHeader.title || "",
          company: (c && c.summary && c.summary.company) || lastHeader.company || "",
          fit: cachedFit(jobId),
        });
      });
    }
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
    if (!isJobsPage()) return null;
    if (userClosed) return null;
    let panel = document.getElementById("jobsum-panel");
    if (!panel) {
      panel = buildPanel();
      document.documentElement.appendChild(panel);
      console.log(LOG, "panel added");
      if (showingList) attachListHandlers(); // re-wire list after a rebuild
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
    if (showingList) return; // don't clobber the list view
    setBody(`<div class="jobsum-status">Preparing summary…</div>`);
  }

  function showError(message) {
    if (showingList) return;
    setBody(`<div class="jobsum-status jobsum-error">${escapeHtml(message)}</div>`);
  }

  function renderSummary(data) {
    if (showingList) return;
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
      if (!extensionAlive()) {
        reject(new Error("Extension reloaded. Refresh the page."));
        return;
      }
      let sending;
      try {
        sending = chrome.runtime.sendMessage(
          { type: "SUMMARIZE", payload },
          (response) => {
            if (chrome.runtime.lastError) {
              reject(new Error("Extension messaging error. Reload the page."));
              return;
            }
            handle(response);
          }
        );
      } catch (_) {
        reject(new Error("Extension reloaded. Refresh the page."));
        return;
      }
      // Some Chrome builds return a Promise instead of using the callback.
      if (sending && typeof sending.then === "function") {
        sending.then(handle, () =>
          reject(new Error("Extension messaging error. Reload the page."))
        );
      }

      function handle(response) {
        if (!response) {
          reject(new Error("No response from backend."));
          return;
        }
        if (!response.ok) {
          reject(new Error(response.error || "Unknown error."));
          return;
        }
        resolve(response.data);
      }
    });
  }

  // The 3-tier description extraction, mirroring maybeUpdate's chain. Used by the
  // "Yenile" button to re-read the current page's text before recomputing.
  function getDescription() {
    let d = firstMatchText(SELECTORS.description);
    if (!d) d = fallbackDescription();
    if (!d) d = heuristicDescription();
    return d || "";
  }

  // "Yenile": recompute the current job's summary from whatever text is on screen
  // now (e.g. a cleaner /jobs/view page than the search page it was first cached
  // from), bypassing both caches and overwriting them with the fresh result.
  function refreshSummary() {
    if (showingList) return; // only meaningful in the summary view
    const jobId = lastJobId || getCurrentJobId();
    if (!jobId) return;
    const description = getDescription();
    if (!description || description.length < 40) {
      showError("Açıklama bulunamadı; özet yenilenemedi.");
      return;
    }
    CACHE.delete(jobId); // drop the stale client-side copy
    lastShownDescription = description;
    showLoading();
    requestSummary(jobId, description, { force: true });
  }

  function requestSummary(jobId, description, opts) {
    const payload = {
      text: description,
      title: firstMatchText(SELECTORS.title) || null,
      company: firstMatchText(SELECTORS.company) || null,
      location: firstMatchText(SELECTORS.location) || null,
      job_id: jobId || null, // server caches by this so a job is summarized once
      refresh: !!(opts && opts.force), // "Yenile": bypass + overwrite the cache
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

  // Dim reviewed job cards in the list and add a "görüldü" badge. Re-applied
  // every tick because LinkedIn virtualizes the list (cards mount/unmount).
  function markSeenCards() {
    const cards = document.querySelectorAll(
      "[data-job-id], [data-occludable-job-id]"
    );
    cards.forEach((card) => {
      if (card.closest("#jobsum-panel")) return; // never touch our own panel
      // Skip the big right-hand details pane (long text); only mark list cards.
      if ((card.innerText || "").length > 800) return;
      const id =
        card.getAttribute("data-job-id") ||
        card.getAttribute("data-occludable-job-id");
      if (!id) return;
      const seen = isReviewed(id);
      const marked = card.classList.contains("jobsum-seen");
      if (seen && !marked) {
        card.classList.add("jobsum-seen");
        if (!card.querySelector(":scope > .jobsum-seen-badge")) {
          const badge = document.createElement("span");
          badge.className = "jobsum-seen-badge";
          badge.textContent = "görüldü";
          card.appendChild(badge);
        }
      } else if (!seen && marked) {
        card.classList.remove("jobsum-seen");
        const b = card.querySelector(":scope > .jobsum-seen-badge");
        if (b) b.remove();
      }
    });
  }

  function maybeUpdate() {
    // Orphaned after an extension reload: stop everything and go quiet.
    if (!extensionAlive()) {
      teardown();
      return;
    }
    // Off the jobs pages (feed, messaging, a profile, …) the script is inert:
    // remove any leftover panel from a previous in-tab navigation and bail.
    if (!isJobsPage()) {
      const stale = document.getElementById("jobsum-panel");
      if (stale) stale.remove();
      return;
    }
    ensurePanel(); // re-add the panel if it was removed
    markSeenCards(); // reflect reviewed state in the list

    const jobId = getCurrentJobId();
    renderReviewStatus(jobId); // update the panel banner/toggle for this job
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
  const pollTimer = setInterval(maybeUpdate, 700);

  // Capture dismiss/undo clicks anywhere on the page.
  document.addEventListener("click", onDocClick, true);

  // Dismantle this (now orphaned) instance after an extension reload so it stops
  // polling a dead context and flooding the console.
  let torndown = false;
  function teardown() {
    if (torndown) return;
    torndown = true;
    try {
      observer.disconnect();
    } catch (_) {
      /* ignore */
    }
    clearInterval(pollTimer);
    clearTimeout(debounceTimer);
    document.removeEventListener("click", onDocClick, true);
    const panel = document.getElementById("jobsum-panel");
    if (panel) panel.remove();
    console.log(LOG, "extension context gone; content script stopped");
  }

  loadReviewed(); // load persisted "reviewed" memory, then reflect it
  ensurePanel();
  scheduleUpdate();
})();
