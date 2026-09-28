import { getStoredToken } from "@/security/token-store";

const BACKEND_ORIGIN = "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit, authed = false): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");

  if (authed) {
    const token = await getStoredToken();
    if (token) headers.set("X-Extension-Token", token);
  }

  const res = await fetch(`${BACKEND_ORIGIN}${path}`, { ...init, headers });
  if (!res.ok) {
    throw new Error(`Backend request to ${path} failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export const backend = {
  health: () => request<{ status: string; time: string }>("/api/v1/health"),

  pair: (pairingSecret: string, extensionOrigin: string) =>
    request<{ extension_token: string }>("/api/v1/system/pair", {
      method: "POST",
      body: JSON.stringify({ pairing_secret: pairingSecret, extension_origin: extensionOrigin }),
    }),

  automationStatus: () =>
    request<{ mode: "PAUSED" | "REVIEW" | "AUTO" }>("/api/v1/automation/status"),

  startAutomation: () =>
    request<{ mode: "PAUSED" | "REVIEW" | "AUTO" }>("/api/v1/automation/start", {
      method: "POST",
    }),

  pauseAutomation: () =>
    request<{ mode: "PAUSED" | "REVIEW" | "AUTO" }>("/api/v1/automation/pause", {
      method: "POST",
    }),

  captureJob: (page: { url: string; title: string; jsonLd: string[]; bodyText: string }) =>
    request<{ id: number; title: string; company: string }>(
      "/api/v1/jobs/capture",
      {
        method: "POST",
        body: JSON.stringify({
          url: page.url,
          page_title: page.title,
          json_ld: page.jsonLd,
          body_text: page.bodyText,
        }),
      },
      true, // extension-token authed, same as any other extension-only endpoint
    ),
};
