/** Talks to the OtterApply browser extension through the page (see extension/src/content/dashboard-bridge.ts). */

const SOURCE = "job-agent-dashboard";
const REPLY = "job-agent-extension";

export interface BridgeReply {
  ok: boolean;
  ready?: boolean;
  unsupported?: boolean;
  error?: string;
}

function ask(type: string, extra: Record<string, unknown>, timeoutMs: number): Promise<BridgeReply | null> {
  return new Promise((resolve) => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const onMessage = (event: MessageEvent) => {
      const d = event.data;
      if (event.source !== window || !d || d.source !== REPLY || d.requestId !== requestId) return;
      cleanup();
      resolve(d as BridgeReply);
    };
    const timer = setTimeout(() => {
      cleanup();
      resolve(null);
    }, timeoutMs);
    function cleanup() {
      window.removeEventListener("message", onMessage);
      clearTimeout(timer);
    }
    window.addEventListener("message", onMessage);
    window.postMessage({ source: SOURCE, type, requestId, ...extra }, window.location.origin);
  });
}

/** Resolves null when the extension isn't there (not installed, not reloaded, or the page predates it). */
export const pingExtension = () => ask("PING", {}, 1200);

export const completeApplication = (jobId: number, url: string) =>
  ask("COMPLETE_APPLICATION", { jobId, url }, 5000);

/** Asks the extension to open the job's page and wait for you to save it, so the description is added to this saved job. */
export const grabDescription = (jobId: number, url: string, title: string) =>
  ask("GRAB_DESCRIPTION", { jobId, url, title }, 5000);

/** Called when the extension has saved the description and brought you back. Returns a function that stops listening. */
export function onDescriptionAdded(callback: (jobId: number) => void): () => void {
  const handler = (event: MessageEvent) => {
    const d = event.data;
    if (event.source !== window || !d || d.source !== REPLY || d.type !== "DESCRIPTION_ADDED" || typeof d.jobId !== "number") return;
    callback(d.jobId);
  };
  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
}
