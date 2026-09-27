import type {
  AutomationStatusResponse,
  HealthResponse,
  PairingSecretResponse,
  PairRequest,
  PairResponse,
  ProfileOut,
  ResumeExtraction,
  ResumeParseResponse,
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
  const isFormData = init?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail ?? JSON.stringify(body);
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new ApiError(res.status, message);
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

  parseResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ResumeParseResponse>("/profile/resume/parse", {
      method: "POST",
      body: form,
    });
  },
  commitProfile: (payload: {
    extraction: ResumeExtraction;
    approved_claims: ResumeParseResponse["draft_claims"];
    resume_filename: string;
  }) =>
    request<ProfileOut>("/profile/commit", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getProfile: () => request<ProfileOut>("/profile"),
};

export { ApiError };
