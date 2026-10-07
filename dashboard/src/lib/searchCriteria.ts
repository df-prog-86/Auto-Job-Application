import type { JobSearchCriteria } from "@/types/api";

/** The last Job Search boxes, kept in this browser so Home can run the same search again. */
export const SAVED_KEY = "job-search-criteria";

export interface SavedCriteria {
  titles: string;
  location: string;
  workType: JobSearchCriteria["work_type"];
  keywords: string;
  exclude: string;
  targetSalary: string;
  requireSalary: boolean;
  within: JobSearchCriteria["posted_within_days"];
  count: number;
}

export function loadSavedCriteria(): Partial<SavedCriteria> {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY);
    return raw ? (JSON.parse(raw) as Partial<SavedCriteria>) : {};
  } catch {
    return {};
  }
}

/** What the backend expects, built from the saved boxes. */
export function toApiCriteria(c: Partial<SavedCriteria>): JobSearchCriteria {
  const salary = parseInt(String(c.targetSalary ?? "").replace(/[^0-9]/g, ""), 10);
  return {
    titles: (c.titles ?? "").trim(),
    location: (c.location ?? "").trim() || null,
    work_type: c.workType ?? "any",
    keywords: (c.keywords ?? "").trim() || null,
    exclude_companies: (c.exclude ?? "").trim() || null,
    target_salary: Number.isFinite(salary) && salary > 0 ? salary : null,
    require_salary: c.requireSalary ?? false,
    posted_within_days: c.within ?? 0,
    count: c.count ?? 10,
  };
}
