import type { ApplyCandidate, ApplyEducation, ApplyExperience, FlaggedField } from "@/form-engine/types";
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
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ApplyContextResponse {
  job: { id: number; title: string; company: string; url: string; proceeding: boolean } | null;
  candidate: ApplyCandidate | null;
  answers: Record<string, unknown>;
  learned_answers: Record<string, string>;
  resume: { document_id: number; filename: string; format: string } | null;
  experience: ApplyExperience[];
  education: ApplyEducation[];
  candidates: { id: number; title: string; company: string; url: string; proceeding: boolean }[];
  problem: string | null;
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

  applyContext: (url: string, jobId?: number) =>
    request<ApplyContextResponse>(
      "/api/v1/apply/context",
      { method: "POST", body: JSON.stringify({ url, job_id: jobId ?? null }) },
      true,
    ),

  applyReport: (report: { jobId: number; pageUrl: string; filledCount: number; flagged: FlaggedField[] }) =>
    request<void>(
      "/api/v1/apply/report",
      {
        method: "POST",
        body: JSON.stringify({
          job_id: report.jobId,
          page_url: report.pageUrl,
          filled_count: report.filledCount,
          flagged: report.flagged,
        }),
      },
      true,
    ),
};

/** The tailored resume, as base64 so it can be handed to the page script. */
export async function downloadDocumentBase64(documentId: number): Promise<string> {
  const res = await fetch(`${BACKEND_ORIGIN}/api/v1/jobs/documents/${documentId}/download`);
  if (!res.ok) throw new Error("Couldn't load the tailored resume from the app.");
  const bytes = new Uint8Array(await res.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}
