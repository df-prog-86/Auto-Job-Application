import type {
  AutomationStatusResponse,
  HealthResponse,
  PairingSecretResponse,
  PairRequest,
  PairResponse,
  VersionResponse,
} from "@/types/api";

/**
 * Same-origin in production (backend serves the dashboard at /app and the
 * API at /api/v1 from the same process — spec §14), proxied in dev by
 * vite.config.ts. Never hits anything but 127.0.0.1.
 */
const API_BASE = "/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  version: () => request<VersionResponse>("/version"),

  automationStatus: () => request<AutomationStatusResponse>("/automation/status"),
  startAutomation: () =>
    request<AutomationStatusResponse>("/automation/start", { method: "POST" }),
  pauseAutomation: () =>
    request<AutomationStatusResponse>("/automation/pause", { method: "POST" }),

  createPairingSecret: () =>
    request<PairingSecretResponse>("/system/pairing-secret", { method: "POST" }),
  pairExtension: (payload: PairRequest) =>
    request<PairResponse>("/system/pair", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export { ApiError };
