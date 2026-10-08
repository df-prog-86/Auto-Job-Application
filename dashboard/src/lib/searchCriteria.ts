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

/** Searches the person chose to keep, shown as chips on Job Search. Stored in this browser only. */
export const SAVED_LIST_KEY = "job-search-saved-list";
const MAX_SAVED = 8;

export interface SavedSearch {
  name: string;
  criteria: SavedCriteria;
}

export function loadSavedSearches(): SavedSearch[] {
  try {
    const raw = window.localStorage.getItem(SAVED_LIST_KEY);
    const list = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(list)) return [];
    return list.filter(
      (s): s is SavedSearch => !!s && typeof s.name === "string" && typeof s.criteria === "object" && s.criteria !== null,
    );
  } catch {
    return [];
  }
}

export function storeSavedSearches(list: SavedSearch[]): void {
  try {
    window.localStorage.setItem(SAVED_LIST_KEY, JSON.stringify(list.slice(0, MAX_SAVED)));
  } catch {
    // keeping searches is a convenience only
  }
}

/** A short readable name like "Project manager, Boston". */
export function savedSearchName(c: SavedCriteria): string {
  const first = c.titles.split(",")[0]?.trim() || "Search";
  const place = c.location.trim();
  const name = place ? `${first}, ${place.split(",")[0].trim()}` : first;
  return name.length > 40 ? `${name.slice(0, 37)}...` : name;
}

export function sameCriteria(a: SavedCriteria, b: SavedCriteria): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
