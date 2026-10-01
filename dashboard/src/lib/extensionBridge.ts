/** Talks to the Job Agent browser extension through the page (see extension/src/content/dashboard-bridge.ts). */

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
