/**
 * Runs only on the Job Agent dashboard (http://127.0.0.1:8765/app/*). Lets
 * the dashboard's "Complete application" button reach the extension. It
 * relays exactly two message kinds and nothing else; the service worker
 * re-checks everything (sender, job id, destination site).
 */

const SOURCE = "job-agent-dashboard";
const REPLY = "job-agent-extension";

window.addEventListener("message", (event: MessageEvent) => {
  if (event.source !== window || event.origin !== location.origin) return;
  const data = event.data as { source?: string; type?: string; requestId?: string; jobId?: unknown; url?: unknown };
  if (!data || data.source !== SOURCE || typeof data.requestId !== "string") return;

  if (data.type === "PING") {
    window.postMessage({ source: REPLY, requestId: data.requestId, ok: true, ready: true }, location.origin);
    return;
  }
  if (data.type === "COMPLETE_APPLICATION" && typeof data.jobId === "number" && typeof data.url === "string") {
    chrome.runtime
      .sendMessage({ type: "COMPLETE_APPLICATION", jobId: data.jobId, url: data.url })
      .then((res) => window.postMessage({ source: REPLY, requestId: data.requestId, ...res }, location.origin))
      .catch((err: Error) =>
        window.postMessage({ source: REPLY, requestId: data.requestId, ok: false, error: err.message }, location.origin),
      );
  }
});
