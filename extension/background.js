// Service worker: forwards summary requests from the content script to the Python
// backend. Doing the fetch here keeps it independent of the LinkedIn page origin and
// allows CORS-free access via host_permissions.

const BACKEND_URL = "http://localhost:8000/summarize";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "SUMMARIZE") return false;

  fetch(BACKEND_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.payload),
  })
    .then(async (res) => {
      if (!res.ok) {
        let detail = `Server error (${res.status})`;
        try {
          const body = await res.json();
          if (body?.detail) detail = body.detail;
        } catch (_) {
          /* body is not JSON; keep the default message */
        }
        sendResponse({ ok: false, error: detail });
        return;
      }
      const data = await res.json();
      sendResponse({ ok: true, data });
    })
    .catch(() => {
      sendResponse({
        ok: false,
        error:
          "Backend unreachable. Make sure the Python server (localhost:8000) is running.",
      });
    });

  // Keep the message channel open for the async response.
  return true;
});
