import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { ChipInput } from "@/components/ChipInput";
import { MenuItem, MoreMenu } from "@/components/MoreMenu";
import { PageHeader } from "@/components/PageHeader";
import { FitPill, MatchPanel, scoreColor } from "@/components/match";
import { Button, Card, Ring } from "@/components/ui";
import { autofillSite } from "@/lib/autofill";
import { formatPosted } from "@/lib/jobText";
import type { JobSearchCriteria, JobSearchResultOut } from "@/types/api";
import {
  SAVED_KEY,
  loadSavedCriteria as loadSaved,
  loadSavedSearches,
  sameCriteria,
  savedSearchName,
  storeSavedSearches,
  toApiCriteria,
} from "@/lib/searchCriteria";
import type { SavedCriteria, SavedSearch } from "@/lib/searchCriteria";

const labelClass = "mb-1.5 block text-xs font-bold text-[#5a5570]";
const fieldClass =
  "w-full rounded-xl border border-[#8f88bb] bg-white px-3.5 py-2.5 text-[13px] text-ink-900 placeholder:text-[#6a6585] focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200";
const selectPill =
  "rounded-full border border-[#8f88bb] bg-white px-3.5 py-2.5 text-[13px] font-bold text-brand-700 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200";

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong. Try again.";
}

function splitList(s: string | undefined): string[] {
  return (s ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** Chips plus whatever is still typed in the box, without repeats. */
function withDraft(values: string[], draft: string): string[] {
  const out = [...values];
  for (const p of splitList(draft)) {
    if (!out.some((v) => v.toLowerCase() === p.toLowerCase())) out.push(p);
  }
  return out;
}

type SortBy = "newest" | "fit";

/** Time of the posting date, or null when it is missing or unreadable. */
function postedTime(r: JobSearchResultOut): number | null {
  if (!r.posted_at) return null;
  const t = Date.parse(r.posted_at);
  return Number.isNaN(t) ? null : t;
}

/** Newest posting first, or best match first. Jobs missing the value always go last. */
function sortResults(list: JobSearchResultOut[], by: SortBy): JobSearchResultOut[] {
  const missingLast = (a: number | null, b: number | null) => {
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return b - a;
  };
  return [...list].sort((a, b) => {
    if (by === "fit") {
      const c = missingLast(a.match_score ?? null, b.match_score ?? null);
      if (c !== 0) return c;
    }
    return missingLast(postedTime(a), postedTime(b));
  });
}

type Notice = { kind: "found" | "info" | "added"; text: string };

export function JobSearch() {
  const qc = useQueryClient();
  const [saved] = useState(loadSaved);
  const [titles, setTitles] = useState<string[]>(() => splitList(saved.titles));
  const [titleDraft, setTitleDraft] = useState("");
  const [location, setLocation] = useState(saved.location ?? "");
  const [workType, setWorkType] = useState<JobSearchCriteria["work_type"]>(saved.workType ?? "any");
  const [keywords, setKeywords] = useState<string[]>(() => splitList(saved.keywords));
  const [keywordDraft, setKeywordDraft] = useState("");
  const [exclude, setExclude] = useState<string[]>(() => splitList(saved.exclude));
  const [excludeDraft, setExcludeDraft] = useState("");
  const [targetSalary, setTargetSalary] = useState(saved.targetSalary ?? "");
  const [requireSalary, setRequireSalary] = useState(saved.requireSalary ?? false);
  const [within, setWithin] = useState<JobSearchCriteria["posted_within_days"]>(saved.within ?? 0);
  const [count, setCount] = useState(saved.count ?? 10);
  const [moreOpen, setMoreOpen] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [autofillOnly, setAutofillOnly] = useState(false);
  const [sortBy, setSortBy] = useState<SortBy>("newest");
  const [savedList, setSavedList] = useState<SavedSearch[]>(loadSavedSearches);
  const [scoringAll, setScoringAll] = useState<{ done: number; total: number } | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  const results = useQuery({ queryKey: ["job-search-results"], queryFn: api.listSearchResults });
  const items = (results.data ?? []).filter((r) => r.status === "new");
  const shown = sortResults(autofillOnly ? items.filter((r) => autofillSite(r.url)) : items, sortBy);
  const anyAutofill = items.some((r) => autofillSite(r.url));
  const unscored = items.filter((r) => r.match_score == null);

  const buildCriteria = (t: string[], k: string[], x: string[]): SavedCriteria => ({
    titles: t.join(", "),
    location,
    workType,
    keywords: k.join(", "),
    exclude: x.join(", "),
    targetSalary,
    requireSalary,
    within,
    count,
  });
  const current = buildCriteria(titles, keywords, exclude);
  const activeSaved = savedList.find((s) => sameCriteria(s.criteria, current));

  const moreCount =
    (targetSalary.trim() ? 1 : 0) +
    (requireSalary ? 1 : 0) +
    (keywords.length > 0 || keywordDraft.trim() ? 1 : 0) +
    (exclude.length > 0 || excludeDraft.trim() ? 1 : 0) +
    (count !== 10 ? 1 : 0);

  /** Turns anything still typed into chips so the search and the saved copy match what is on screen. */
  const settle = () => {
    const t = withDraft(titles, titleDraft);
    const k = withDraft(keywords, keywordDraft);
    const x = withDraft(exclude, excludeDraft);
    setTitles(t);
    setKeywords(k);
    setExclude(x);
    setTitleDraft("");
    setKeywordDraft("");
    setExcludeDraft("");
    return buildCriteria(t, k, x);
  };

  const search = useMutation({
    mutationFn: () => {
      const c = settle();
      try {
        window.localStorage.setItem(SAVED_KEY, JSON.stringify(c));
      } catch {
        // remembering the boxes is a convenience only
      }
      return api.runJobSearch(toApiCriteria(c));
    },
    onSuccess: (r) => {
      setNotice(
        r.found > 0
          ? {
              kind: "found",
              text: `Found ${r.found} new ${r.found === 1 ? "match" : "matches"}.${r.skipped ? ` ${r.skipped} skipped (already in your jobs, already shown, no longer open, or not a real posting link).` : ""}`,
            }
          : {
              kind: "info",
              text: `No new matches. ${r.skipped ? `${r.skipped} skipped because you already have them, removed them, or they are no longer open.` : "Try broader words."}`,
            },
      );
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
    },
    onError: () => setNotice(null),
  });

  const navigate = useNavigate();
  const [toast, setToast] = useState<{ jobId: number; title: string } | null>(null);
  const toastHovered = useRef(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const armToast = () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => {
      if (toastHovered.current) armToast();
      else setToast(null);
    }, 5000);
  };
  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const add = useMutation({
    mutationFn: (id: number) => api.addSearchResult(id),
    onSuccess: (r) => {
      setToast({ jobId: r.job.id, title: r.job.title });
      armToast();
      setNotice({
        kind: "added",
        text: r.from_summary
          ? `Added "${r.job.title}" to Jobs, using the search summary because the posting page couldn't be read. Open the posting to check the details.`
          : `Added "${r.job.title}" to Jobs.`,
      });
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const score = useMutation({
    mutationFn: (id: number) => api.scoreSearchResult(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["job-search-results"] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.removeSearchResult(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["job-search-results"] }),
  });

  const clear = useMutation({
    mutationFn: () => api.clearSearchResults(),
    onSuccess: () => {
      setConfirmClear(false);
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
    },
  });

  const scoreAll = async () => {
    const todo = unscored.map((r) => r.id);
    if (todo.length === 0 || scoringAll) return;
    setBulkError(null);
    setScoringAll({ done: 0, total: todo.length });
    let skipped = 0;
    try {
      for (let i = 0; i < todo.length; i++) {
        try {
          await api.scoreSearchResult(todo[i]);
        } catch (e) {
          // Setup problems (no resume, AI not connected) would repeat for every job, so stop there.
          if (e instanceof ApiError && (e.status === 409 || e.status === 503)) throw e;
          skipped += 1;
        }
        setScoringAll({ done: i + 1, total: todo.length });
        await qc.invalidateQueries({ queryKey: ["job-search-results"] });
      }
      if (skipped > 0) {
        setBulkError(
          `${skipped} ${skipped === 1 ? "posting" : "postings"} couldn't be scored because the page is closed or couldn't be read. Open them to check.`,
        );
      }
    } catch (e) {
      setBulkError(errorText(e));
    } finally {
      setScoringAll(null);
    }
  };

  const saveThisSearch = () => {
    const c = settle();
    if (!c.titles.trim()) return;
    const name = savedSearchName(c);
    const next = [{ name, criteria: c }, ...savedList.filter((s) => s.name !== name)].slice(0, 8);
    setSavedList(next);
    storeSavedSearches(next);
  };

  const loadSavedSearch = (s: SavedSearch) => {
    const c = s.criteria;
    setTitles(splitList(c.titles));
    setTitleDraft("");
    setLocation(c.location ?? "");
    setWorkType(c.workType ?? "any");
    setKeywords(splitList(c.keywords));
    setKeywordDraft("");
    setExclude(splitList(c.exclude));
    setExcludeDraft("");
    setTargetSalary(c.targetSalary ?? "");
    setRequireSalary(c.requireSalary ?? false);
    setWithin(c.within ?? 0);
    setCount(c.count ?? 10);
  };

  const deleteSavedSearch = (name: string) => {
    const next = savedList.filter((s) => s.name !== name);
    setSavedList(next);
    storeSavedSearches(next);
  };

  const busyId = add.isPending ? add.variables : remove.isPending ? remove.variables : score.isPending ? score.variables : null;
  const canSearch = withDraft(titles, titleDraft).join(", ").length >= 2 && !search.isPending;
  const canSave = withDraft(titles, titleDraft).length > 0 && !activeSaved;

  return (
    <div className="space-y-5">
      {toast && (
        <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-6">
          <div
            className="added-toast pointer-events-auto flex items-center gap-5 rounded-2xl bg-[rgba(28,27,58,0.82)] py-4 pl-6 pr-4 text-[15px] text-white shadow-lg backdrop-blur"
            role="status"
            onMouseEnter={() => (toastHovered.current = true)}
            onMouseLeave={() => (toastHovered.current = false)}
          >
            <span>Added to Jobs</span>
            <button
              type="button"
              className="rounded-full bg-white px-5 py-2.5 text-sm font-bold text-brand-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-white/60"
              onClick={() => {
                const id = toast.jobId;
                setToast(null);
                navigate(`/jobs?highlight=${id}`);
              }}
            >
              Go to job listing
            </button>
          </div>
        </div>
      )}
      <PageHeader
        title="Job Search"
        description="Tell us what you want and we search the web for matching openings. Nothing is added to Jobs until you click Add to jobs."
      />

      <Card className="overflow-hidden border border-[#e9e6f4] !shadow-[0_-6px_18px_rgba(60,50,120,0.08),0_1px_2px_rgba(31,27,46,0.08),0_12px_32px_rgba(60,50,120,0.12)]">
        {(savedList.length > 0 || canSave) && (
          <div className="flex flex-wrap items-center gap-2 border-b border-[#ebe8f6] bg-[#f9f8fd] px-5 py-3">
            <span className="mr-1 text-xs font-extrabold text-[#5a5570]">Saved searches</span>
            {savedList.map((s) => {
              const on = activeSaved?.name === s.name;
              return (
                <span
                  key={s.name}
                  className={`inline-flex items-center rounded-full border text-xs font-bold ${
                    on ? "border-brand-500 bg-brand-500 text-white" : "border-[#cfc8ee] bg-white text-ink-700"
                  }`}
                >
                  <button type="button" onClick={() => loadSavedSearch(s)} className="py-1.5 pl-3 pr-1.5" aria-pressed={on}>
                    {s.name}
                  </button>
                  <button
                    type="button"
                    aria-label={`Forget saved search ${s.name}`}
                    onClick={() => deleteSavedSearch(s.name)}
                    className={`mr-1.5 flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-extrabold ${
                      on ? "hover:bg-white/25" : "text-ink-500 hover:bg-brand-50"
                    }`}
                  >
                    &#10005;
                  </button>
                </span>
              );
            })}
            {canSave && (
              <button
                type="button"
                onClick={saveThisSearch}
                className="ml-auto text-xs font-bold text-brand-600 hover:text-brand-700 hover:underline"
              >
                + Save this search
              </button>
            )}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSearch) search.mutate();
          }}
        >
          <div className="flex flex-wrap items-center gap-3 bg-gradient-to-b from-[#f8f6ff] to-[#fefeff] px-5 py-3.5">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              className="h-5 w-5 shrink-0 text-brand-500"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="6.5" />
              <path d="M16 16l4 4" />
            </svg>
            <div className="min-w-[260px] flex-1">
              <ChipInput
                variant="title"
                label="Job titles"
                values={titles}
                onChange={setTitles}
                draft={titleDraft}
                onDraft={setTitleDraft}
                placeholder="Job titles, like project manager"
                maxLength={100}
              />
            </div>
            <Button type="submit" variant="primary" className={`px-6 py-3 ${search.isPending ? "ai-working" : ""}`} disabled={!canSearch}>
              {search.isPending ? "Searching..." : "Search the web"}
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5 border-t border-[#ebe8f6] bg-[#f9f8fd] px-4 py-3 sm:pl-5">
            <div className="relative min-w-[200px] flex-1">
              <label htmlFor="js-location" className="sr-only">
                Location
              </label>
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#5a5570]"
                aria-hidden="true"
              >
                <path d="M12 21s7-6.2 7-11.5A7 7 0 005 9.5C5 14.8 12 21 12 21z" />
                <circle cx="12" cy="9.5" r="2.5" />
              </svg>
              <input
                id="js-location"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="City, state, or United States"
                maxLength={200}
                className="w-full rounded-full border border-[#8f88bb] bg-white py-2.5 pl-10 pr-4 text-[13px] text-ink-900 placeholder:text-[#6a6585] focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200"
              />
            </div>
            <select
              aria-label="Work type"
              className={selectPill}
              value={workType}
              onChange={(e) => setWorkType(e.target.value as JobSearchCriteria["work_type"])}
            >
              <option value="any">Any work type</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">On site</option>
            </select>
            <select
              aria-label="Posted within"
              className={selectPill}
              value={within}
              onChange={(e) => setWithin(Number(e.target.value) as JobSearchCriteria["posted_within_days"])}
            >
              <option value={0}>Posted any time</option>
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
            <button
              type="button"
              onClick={() => setMoreOpen((v) => !v)}
              aria-expanded={moreOpen}
              className="ml-auto inline-flex items-center gap-1.5 text-[13px] font-bold text-brand-600 hover:text-brand-700"
            >
              {moreOpen ? "Fewer filters" : "More filters"}
              {moreCount > 0 && (
                <span className="rounded-full bg-brand-500 px-1.5 text-[11px] text-white">{moreCount}</span>
              )}
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-3 w-3"
                aria-hidden="true"
              >
                <path d={moreOpen ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
              </svg>
            </button>
          </div>

          {moreOpen && (
            <div className="grid gap-x-7 gap-y-5 border-t border-[#ebe8f6] bg-white px-5 py-4 md:grid-cols-2">
              <div>
                <label className={labelClass} htmlFor="js-salary">
                  Salary minimum (yearly)
                </label>
                <input
                  id="js-salary"
                  className={`${fieldClass} max-w-[220px]`}
                  inputMode="numeric"
                  value={targetSalary}
                  onChange={(e) => setTargetSalary(e.target.value)}
                  placeholder="80000"
                />
                <p className="mt-1.5 text-xs text-ink-500">The pay range midpoint must be at least this. Higher is fine.</p>
              </div>
              <div className="space-y-4">
                <div>
                  <label className={labelClass} htmlFor="js-count">
                    How many results
                  </label>
                  <select
                    id="js-count"
                    className={`${fieldClass} max-w-[220px]`}
                    value={count}
                    onChange={(e) => setCount(Number(e.target.value))}
                  >
                    {[5, 10, 15].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-center gap-2.5">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={requireSalary}
                    aria-labelledby="js-require-salary"
                    onClick={() => setRequireSalary((v) => !v)}
                    className={`relative h-[22px] w-[38px] shrink-0 rounded-full transition ${
                      requireSalary ? "bg-brand-500" : "bg-[#cfc8ee]"
                    }`}
                  >
                    <span
                      className={`absolute top-[3px] h-4 w-4 rounded-full bg-white shadow transition-all ${
                        requireSalary ? "left-[19px]" : "left-[3px]"
                      }`}
                    />
                  </button>
                  <span id="js-require-salary" className="text-[13px] font-semibold text-ink-700">
                    Only show jobs that post their salary
                  </span>
                </div>
              </div>
              <div>
                <span className={labelClass}>Keywords (optional)</span>
                <ChipInput
                  label="Keywords"
                  values={keywords}
                  onChange={setKeywords}
                  draft={keywordDraft}
                  onDraft={setKeywordDraft}
                  placeholder="healthcare, Agile, SaaS"
                />
              </div>
              <div>
                <span className={labelClass}>Leave out these companies (optional)</span>
                <ChipInput
                  label="Companies to leave out"
                  values={exclude}
                  onChange={setExclude}
                  draft={excludeDraft}
                  onDraft={setExcludeDraft}
                  placeholder="Add a company"
                />
              </div>
            </div>
          )}

          <p className="flex items-center gap-2 border-t border-[#ebe8f6] bg-white px-5 py-2.5 text-xs text-ink-500">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              className="h-3.5 w-3.5 shrink-0"
              aria-hidden="true"
            >
              <rect x="5" y="11" width="14" height="9" rx="2" />
              <path d="M8 11V8a4 4 0 018 0v3" />
            </svg>
            Only the words above are sent. Nothing from your profile. Each search costs a small amount.
          </p>
        </form>
      </Card>

      {search.isPending && (
        <p className="animate-pulse text-sm text-ink-500" role="status">
          Searching the web. This can take up to a minute.
        </p>
      )}
      {search.isError && (
        <p className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
          {errorText(search.error)}
        </p>
      )}

      {notice && (
        <p
          className={`flex items-center gap-2.5 rounded-2xl px-4 py-3 text-[13px] font-bold ${
            notice.kind === "found" ? "bg-[#e8f6ee] text-[#17603f]" : "bg-brand-50 text-brand-700"
          }`}
          role="status"
        >
          {notice.kind === "found" && (
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-[18px] w-[18px] shrink-0"
              aria-hidden="true"
            >
              <path d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
          )}
          <span>
            {notice.text}{" "}
            {notice.kind === "added" && (
              <Link to="/jobs" className="underline">
                Go to Jobs
              </Link>
            )}
          </span>
        </p>
      )}
      {(add.isError || remove.isError || bulkError) && (
        <p className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
          {bulkError ?? errorText(add.error ?? remove.error)}
        </p>
      )}

      {results.isLoading ? (
        <p className="text-sm text-ink-500">Loading...</p>
      ) : items.length === 0 ? (
        <Card className="p-10 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-500">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="h-7 w-7" aria-hidden="true">
              <circle cx="11" cy="11" r="6.5" />
              <path d="M16 16l4 4" />
            </svg>
          </div>
          <h2 className="text-base font-bold text-ink-900">No matches yet</h2>
          <p className="mt-1 text-sm text-ink-500">Add a job title above and click Search the web.</p>
        </Card>
      ) : (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-extrabold text-ink-900">
              {items.length} {items.length === 1 ? "match" : "matches"} to review
            </h2>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-xs font-bold text-[#5a5570]">
                Sort
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value === "fit" ? "fit" : "newest")}
                  className="rounded-full border border-[#8f88bb] bg-white px-3.5 py-2 text-[13px] font-bold text-brand-700 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200"
                >
                  <option value="newest">Newest posted</option>
                  <option value="fit">Best fit first</option>
                </select>
              </label>
              {anyAutofill && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={autofillOnly}
                    aria-labelledby="js-autofill-only"
                    onClick={() => setAutofillOnly((v) => !v)}
                    className={`relative h-[19px] w-[32px] shrink-0 rounded-full transition ${
                      autofillOnly ? "bg-brand-500" : "bg-[#cfc8ee]"
                    }`}
                  >
                    <span
                      className={`absolute top-[3px] h-[13px] w-[13px] rounded-full bg-white shadow transition-all ${
                        autofillOnly ? "left-[16px]" : "left-[3px]"
                      }`}
                    />
                  </button>
                  <span id="js-autofill-only" className="text-xs font-bold text-[#5a5570]">
                    Autofill ready only
                  </span>
                </div>
              )}
              <MoreMenu>
                <MenuItem onClick={() => void scoreAll()} disabled={unscored.length === 0 || scoringAll !== null}>
                  {unscored.length > 0 ? `Score all (${unscored.length})` : "Score all"}
                </MenuItem>
                <MenuItem danger onClick={() => setConfirmClear(true)}>
                  Clear all
                </MenuItem>
              </MoreMenu>
            </div>
          </div>

          {confirmClear && (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-800">
              Remove all {items.length} matches?
              <span className="flex gap-2">
                <Button size="sm" variant="danger" onClick={() => clear.mutate()} disabled={clear.isPending}>
                  Yes, remove all
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmClear(false)}>
                  Keep
                </Button>
              </span>
            </div>
          )}
          {scoringAll && (
            <p className="animate-pulse text-xs text-ink-500" role="status">
              Scoring {Math.min(scoringAll.done + 1, scoringAll.total)} of {scoringAll.total}. This can take a few minutes.
            </p>
          )}

          {shown.length === 0 ? (
            <p className="text-sm text-ink-500">
              None of these can be autofilled. Turn off "Autofill ready only" to see all {items.length}.
            </p>
          ) : (
            <ul className="space-y-3.5">
              {shown.map((r) => (
                <ResultCard
                  key={r.id}
                  r={r}
                  busy={busyId === r.id || scoringAll !== null}
                  scoring={score.isPending && score.variables === r.id}
                  problem={score.isError && score.variables === r.id ? errorText(score.error) : undefined}
                  onScore={() => score.mutate(r.id)}
                  onAdd={() => add.mutate(r.id)}
                  onRemove={() => remove.mutate(r.id)}
                />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function ResultCard({
  r,
  busy,
  scoring,
  problem,
  onScore,
  onAdd,
  onRemove,
}: {
  r: JobSearchResultOut;
  busy: boolean;
  scoring: boolean;
  /** Why the last attempt to score this one failed, such as a closed posting. */
  problem?: string;
  onScore: () => void;
  onAdd: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const posted = formatPosted(r.posted_at);
  const site = autofillSite(r.url);
  // A score that came only from the one-line summary is not shown; it would look surer than it is.
  const score = r.match_from_page === false ? null : (r.match_score ?? null);
  const edge = score === null ? "#e3dff3" : scoreColor(score);
  return (
    <li>
      <Card className="flex">
        <div className="w-[5px] shrink-0 rounded-l-2xl" style={{ backgroundColor: edge }} aria-hidden="true" />
        <div className="min-w-0 flex-1 p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-lg font-bold leading-snug text-ink-900">{r.title}</h3>
              {r.company && <div className="mt-0.5 text-sm font-semibold text-ink-500">{r.company}</div>}
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-500">
                {r.location && (
                  <span className="inline-flex items-center gap-1.5">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    >
                      <path d="M12 21s7-6.2 7-11.5A7 7 0 005 9.5C5 14.8 12 21 12 21z" />
                      <circle cx="12" cy="9.5" r="2.5" />
                    </svg>
                    {r.location}
                  </span>
                )}
                {r.work_type && <span className="capitalize">{r.work_type}</span>}
                {r.salary_text && <span>{r.salary_text}</span>}
                <span className={posted ? "" : "text-ink-400"}>{posted ? `Posted ${posted}` : "Posted date not listed"}</span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2.5">
              {!r.grounded && (
                <span className="rounded-full bg-[#fff4dc] px-3 py-1 text-xs font-bold text-[#8a5a00]">Link not verified</span>
              )}
              {score !== null ? (
                <div className="flex items-center gap-3">
                  <div className="hidden flex-col items-end gap-1 sm:flex">
                    <FitPill score={score} />
                    <span className="text-[11px] text-ink-500">match with your resume</span>
                  </div>
                  <Ring value={score} size={58} stroke={6} color={scoreColor(score)}>
                    <span className="text-sm font-bold text-ink-900">{Math.round(score * 100)}</span>
                  </Ring>
                </div>
              ) : (
                <Button size="sm" variant="primary" className={scoring ? "ai-working" : ""} onClick={onScore} disabled={busy}>
                  {scoring ? "Scoring..." : "Score"}
                </Button>
              )}
            </div>
          </div>

          {r.summary && (
            <p
              className="mt-3 text-sm leading-relaxed text-ink-700"
              style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}
            >
              {r.summary}
            </p>
          )}
          {problem && !scoring && (
            <p className="mt-3 rounded-xl bg-[#fff4dc] px-3.5 py-2.5 text-[13px] text-[#8a5a00]" role="alert">
              {problem}
            </p>
          )}
          {scoring && (
            <p className="mt-3 animate-pulse text-xs text-ink-500">
              Reading the posting and comparing it with your resume. This can take up to a minute.
            </p>
          )}

          {open && score !== null && (
            <div className="mt-4">
              <MatchPanel score={score} summary={r.match_summary} gaps={r.match_gaps ?? []} />
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button variant="primary" onClick={onAdd} disabled={busy}>
                {busy && !scoring ? "Working..." : "Add to jobs"}
              </Button>
              <a
                href={r.url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-[13px] font-bold text-brand-600 hover:text-brand-700 hover:underline"
              >
                View posting
              </a>
              {site && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#e8f6ee] px-3 py-1 text-xs font-bold text-[#17603f]">
                  <svg viewBox="0 0 24 24" fill="currentColor" className="h-3 w-3" aria-hidden="true">
                    <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
                  </svg>
                  Autofill ready on {site}
                </span>
              )}
            </div>
            <div className="ml-auto flex items-center gap-3">
              {score !== null && (
                <button
                  type="button"
                  onClick={() => setOpen((v) => !v)}
                  aria-expanded={open}
                  className="text-[13px] font-bold text-brand-600 hover:text-brand-700 hover:underline"
                >
                  {open ? "Hide details" : "Show more details"}
                </button>
              )}
              <MoreMenu>
                {score !== null && (
                  <MenuItem onClick={onScore} disabled={busy}>
                    Score again
                  </MenuItem>
                )}
                <MenuItem danger onClick={onRemove} disabled={busy}>
                  Remove
                </MenuItem>
              </MoreMenu>
            </div>
          </div>
        </div>
      </Card>
    </li>
  );
}
