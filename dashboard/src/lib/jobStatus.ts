import type { JobOut } from "@/types/api";

/** The four statuses a job moves through on the Jobs page. A job is in exactly one. */
export type JobStatus = "saved" | "ready" | "applying" | "applied";

const hasResume = (j: JobOut) => j.documents.some((d) => d.document_type === "resume");

export function statusOf(j: JobOut): JobStatus {
  if (j.applied_at) return "applied";
  if (j.application_started_at) return "applying";
  if (j.application_status === "proceeding" && hasResume(j)) return "ready";
  return "saved";
}
