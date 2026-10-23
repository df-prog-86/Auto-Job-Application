import { statusOf } from "@/lib/jobStatus";
import type { JobStatus } from "@/lib/jobStatus";
import type { JobOut } from "@/types/api";

/** What the Home page works out from the saved jobs. Plain functions so they are easy to check. */

export type StageKey = JobStatus;

export const FOLLOW_UP_AFTER_DAYS = 7;
/** A follow-up this old is labelled "Overdue"; between the two it is "Due now". */
export const OVERDUE_AFTER_DAYS = 10;
/** The follow-up meter fills over this many days; its halfway tick is the 7-day mark. */
export const FOLLOW_UP_METER_DAYS = 14;
const DAY = 86_400_000;

export const hasResume = (j: JobOut) => j.documents.some((d) => d.document_type === "resume");

export function daysSince(iso: string | null | undefined, now: Date): number {
  if (!iso) return 0;
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / DAY));
}

/** The status a job is in: Saved, Ready to apply, Applying or Applied. */
export const stageOf = statusOf;

const score = (j: JobOut) => j.evaluation?.overall_score ?? -1;

export function byStage(jobs: JobOut[]): Record<StageKey, JobOut[]> {
  const out: Record<StageKey, JobOut[]> = { saved: [], ready: [], applying: [], applied: [] };
  for (const j of jobs) out[stageOf(j)].push(j);
  out.saved.sort((a, b) => score(b) - score(a));
  out.ready.sort((a, b) => +new Date(readySince(a) ?? 0) - +new Date(readySince(b) ?? 0));
  out.applying.sort((a, b) => +new Date(a.application_started_at ?? 0) - +new Date(b.application_started_at ?? 0));
  out.applied.sort((a, b) => +new Date(b.applied_at ?? 0) - +new Date(a.applied_at ?? 0));
  return out;
}

/** When a job's resume was made, which is when it became ready to apply. */
export function readySince(j: JobOut): string | null {
  const times = j.documents.filter((d) => d.document_type === "resume").map((d) => d.generated_at);
  return times.length ? times.sort()[0] : null;
}

/** The ready-to-apply job that has waited longest, once it has waited 2 days or more. */
export function oldestWaiting(ready: JobOut[], now: Date): number | null {
  let oldest = 0;
  for (const j of ready) oldest = Math.max(oldest, daysSince(readySince(j) ?? j.first_seen, now));
  return oldest >= 2 ? oldest : null;
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

/** Applications sent on each day of this week, Monday first, plus which day today is (0 = Monday). */
export function dayCounts(jobs: JobOut[], now: Date): { counts: number[]; today: number } {
  const start = weekStart(now).getTime();
  const counts = [0, 0, 0, 0, 0, 0, 0];
  for (const j of jobs) {
    if (!j.applied_at) continue;
    const t = new Date(j.applied_at);
    if (t.getTime() < start) continue;
    const idx = (t.getDay() + 6) % 7;
    counts[idx]++;
  }
  return { counts, today: (now.getDay() + 6) % 7 };
}

/** How many a day it takes to reach the goal, counting today. Zero once the goal is met. */
export function perDayNeeded(thisWeek: number, goal: number, today: number): number {
  const left = Math.max(0, goal - thisWeek);
  if (left === 0) return 0;
  return Math.ceil(left / Math.max(1, 7 - today));
}

export const isOverdue = (days: number) => days >= OVERDUE_AFTER_DAYS;
