import type { JobOut } from "@/types/api";

/** What the Home page works out from the saved jobs. Plain functions so they are easy to check. */

export type StageKey = "scored" | "going" | "ready" | "progress" | "applied";

export const FOLLOW_UP_AFTER_DAYS = 7;
const DAY = 86_400_000;

export const hasResume = (j: JobOut) => j.documents.some((d) => d.document_type === "resume");

export function daysSince(iso: string | null | undefined, now: Date): number {
  if (!iso) return 0;
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / DAY));
}

/** The furthest step a job has reached. A job sits in exactly one stage. */
export function stageOf(j: JobOut): StageKey | null {
  if (j.applied_at) return "applied";
  if (j.application_started_at) return "progress";
  if (j.application_status === "proceeding") return hasResume(j) ? "ready" : "going";
  if (j.evaluation) return "scored";
  return null;
}

const score = (j: JobOut) => j.evaluation?.overall_score ?? -1;

export function byStage(jobs: JobOut[]): Record<StageKey, JobOut[]> {
  const out: Record<StageKey, JobOut[]> = { scored: [], going: [], ready: [], progress: [], applied: [] };
  for (const j of jobs) {
    const s = stageOf(j);
    if (s) out[s].push(j);
  }
  out.scored.sort((a, b) => score(b) - score(a));
  out.going.sort((a, b) => score(b) - score(a));
  out.ready.sort((a, b) => score(b) - score(a));
  out.applied.sort((a, b) => +new Date(a.applied_at ?? 0) - +new Date(b.applied_at ?? 0));
  out.progress.sort((a, b) => +new Date(a.application_started_at ?? 0) - +new Date(b.application_started_at ?? 0));
  return out;
}

/** Of the steps you still have to act on, the one whose oldest job has waited longest (3 days or more). */
export function stalledStage(stages: Record<StageKey, JobOut[]>, now: Date): StageKey | null {
  let best: StageKey | null = null;
  let bestAge = 2;
  for (const key of ["scored", "going", "ready", "progress"] as const) {
    for (const j of stages[key]) {
      const age = daysSince(j.first_seen, now);
      if (age > bestAge) {
        bestAge = age;
        best = key;
      }
    }
  }
  return best;
}

/** Monday 00:00 of the week that contains `now`. */
export function weekStart(now: Date): Date {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

export function weeklyCounts(jobs: JobOut[], now: Date): { thisWeek: number; lastWeek: number } {
  const start = weekStart(now).getTime();
  let thisWeek = 0;
  let lastWeek = 0;
  for (const j of jobs) {
    if (!j.applied_at) continue;
    const t = new Date(j.applied_at).getTime();
    if (t >= start) thisWeek++;
    else if (t >= start - 7 * DAY) lastWeek++;
  }
  return { thisWeek, lastWeek };
}

export interface FollowUp {
  job: JobOut;
  kind: "after_applying" | "after_interview";
  days: number;
}

/** Applications with no reply after a week. */
export function followUps(jobs: JobOut[], now: Date): FollowUp[] {
  const out: FollowUp[] = [];
  for (const job of jobs) {
    const since = job.applied_at;
    if (!since) continue;
    if (job.followup_done_at && new Date(job.followup_done_at) >= new Date(since)) continue;
    const days = daysSince(since, now);
    if (days >= FOLLOW_UP_AFTER_DAYS) out.push({ job, kind: "after_applying", days });
  }
  return out.sort((a, b) => b.days - a.days);
}
