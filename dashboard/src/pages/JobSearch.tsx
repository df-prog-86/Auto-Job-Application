import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { ChipInput } from "@/components/ChipInput";
import { MenuItem, MoreMenu } from "@/components/MoreMenu";
import { SuggestInput } from "@/components/Suggest";
import { EmployersPanel } from "@/components/JobSources";
import { scoreColor, scoreLabel } from "@/components/match";
import { OtterTile } from "@/components/OtterTile";
import { Ring } from "@/components/ui";
import { autofillSite } from "@/lib/autofill";
import { formatPayText, formatPosted, formatPostedBoth, inSentence, mayBeClosed } from "@/lib/jobText";
import type { CoverageOut, JobSearchCriteria, JobSearchResultOut } from "@/types/api";
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

/** Jobs on one page of results. */
const PAGE_SIZE = 10;

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

type SortBy = "search" | "newest";

/** Time of the posting date, or null when it is missing or unreadable. */
function postedTime(r: JobSearchResultOut): number | null {
  if (!r.posted_at) return null;
  const t = Date.parse(r.posted_at);
  return Number.isNaN(t) ? null : t;
}

/** Best search match, or newest posted. Jobs missing the value always go last. */
function sortResults(list: JobSearchResultOut[], by: SortBy): JobSearchResultOut[] {
  const missingLast = (a: number | null, b: number | null) => {
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return b - a;
  };
  return [...list].sort((a, b) => {
    if (by === "search") {
      const c = missingLast(a.fit_score ?? null, b.fit_score ?? null);
      if (c !== 0) return c;
    }
    return missingLast(postedTime(a), postedTime(b));
  });
}

type Notice = { kind: "info" | "added"; text: string; jobId?: number };

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
  const count = PAGE_SIZE;
  const [page, setPage] = useState(1);
  // Pages after the first come from the server one at a time: the ids of the jobs on each, and how many matches there are in all.
  const [serverPages, setServerPages] = useState<Record<number, number[]>>({});
  const [matchTotal, setMatchTotal] = useState<number | null>(null);
  // True once the web search has been ranked into the list: from then on page 1 is also cut from the server's list.
  const [webMerged, setWebMerged] = useState(false);
  const pageRef = useRef(1);
  const sortRef = useRef<SortBy>("search");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [autofillOnly, setAutofillOnly] = useState(false);
  const [sortBy, setSortBy] = useState<SortBy>("search");
  const [savedList, setSavedList] = useState<SavedSearch[]>(loadSavedSearches);
  const [coverage, setCoverage] = useState<CoverageOut | null>(null);
  const lastCriteria = useRef<JobSearchCriteria | null>(null);
  // What the last search used (the saved boxes at page load), which step of a running search we are on, and whether one finished here.
  const [searched, setSearched] = useState<SavedCriteria | null>(() => (saved.titles ? (saved as SavedCriteria) : null));
  const [step, setStep] = useState(0);
  const [justSearched, setJustSearched] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  const results = useQuery({ queryKey: ["job-search-results"], queryFn: api.listSearchResults });
  const items = (results.data ?? []).filter((r) => r.status === "new");
  const shown = sortResults(autofillOnly ? items.filter((r) => autofillSite(r.url)) : items, sortBy);
  // Pages of PAGE_SIZE. In "Best match" order the first page is the top of what is loaded and every later page is fetched from the
  // server on its own (so the last page is as quick as page 2). In any other order the pages are cut from what is already loaded.
  const serverMode = !autofillOnly;
  // One number for the status line and the page count: the saved-list matches the server counted for this search.
  const countedMatches = matchTotal ?? coverage?.matches ?? items.length;
  const poolSize = serverMode ? countedMatches : shown.length;
  const totalPages = Math.max(1, Math.ceil(poolSize / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  // The jobs the search itself returned (the web results included), best first. Jobs opened from later pages are kept apart.
  const searchRows = sortResults(items.filter((r) => !r.page_no), "search");
  const firstPageIds = new Set(searchRows.map((r) => r.id));
  const byId = new Map(items.map((r) => [r.id, r]));
  // In "Best match" order page 1 is what the search just found (the web results included); every other page, and every page in
  // another order, is the server's cut of the whole list in that order.
  const fromServer = serverMode && !(sortBy === "search" && currentPage === 1 && !webMerged);
  const pageItems = fromServer
    ? (serverPages[currentPage] ?? []).map((id) => byId.get(id)).filter((r): r is JobSearchResultOut => !!r && (sortBy !== "search" || webMerged || !firstPageIds.has(r.id)))
    : serverMode
      ? searchRows.slice(0, PAGE_SIZE)
      : shown.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  // The number in the status line must equal the cards on screen. With a single page the cards are the truth (the server's count is
  // taken before duplicates are merged and results trimmed, so it can say 9 when 8 are listed).
  const totalMatches = !autofillOnly && totalPages <= 1 && pageItems.length > 0 ? pageItems.length : countedMatches;
  useEffect(() => {
    pageRef.current = currentPage;
    sortRef.current = sortBy;
    listRef.current?.scrollTo({ top: 0 });
  }, [currentPage, sortBy]);
  const anyAutofill = items.some((r) => autofillSite(r.url));

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

  // After a refresh the page knows the saved jobs but not how many matches the last search had: ask once, so the number of pages is right.
  const askedTotal = useRef(false);
  useEffect(() => {
    if (askedTotal.current || !results.isSuccess || items.length === 0 || matchTotal !== null || titles.length === 0) return;
    askedTotal.current = true;
    api
      .pageJobSearch({ ...toApiCriteria(current), count: PAGE_SIZE, page: 0 })
      .then((t) => setMatchTotal(t.total))
      .catch(() => undefined);
  }, [results.isSuccess, items.length, matchTotal, titles.length, current]);

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
    mutationFn: async () => {
      const c = settle();
      try {
        window.localStorage.setItem(SAVED_KEY, JSON.stringify(c));
      } catch {
        // remembering the boxes is a convenience only
      }
      const apiCriteria = toApiCriteria(c);
      lastCriteria.current = apiCriteria;
      setStep(0);
      setNotice(null);
      setSearched(c);
      // Nothing is shown until every check is done: the saved lists, then the web search, then the first page checked against the
      // employers' own systems. What appears is the final list, so the number and the jobs never change under the person.
      const run = await api.runJobSearch({ ...apiCriteria, web: "saved" });
      setStep(1);
      await api.webJobSearch(apiCriteria).catch(() => undefined);
      setStep(2);
      const first = await api.pageJobSearch({ ...apiCriteria, count: PAGE_SIZE, page: 1, sort: "search" });
      return { run, first, crit: apiCriteria };
    },
    onSuccess: ({ run, first, crit }) => {
      if (lastCriteria.current !== crit) return;
      setCoverage(run.coverage ?? null);
      setJustSearched(true);
      setPage(1);
      qc.setQueryData<JobSearchResultOut[]>(["job-search-results"], (old) => {
        const have = new Set((old ?? []).map((x) => x.id));
        return [...(old ?? []), ...first.results.filter((x) => !have.has(x.id))];
      });
      setServerPages({ 1: first.results.map((x) => x.id) });
      setMatchTotal(first.total);
      setWebMerged(true);
      void qc.invalidateQueries({ queryKey: ["job-employers"] });
      setNotice(
        first.results.length > 0
          ? null
          : {
              kind: "info",
              text: `No new matches. ${run.skipped ? `${run.skipped} skipped because you already have them, removed them, or they are no longer open.` : "Try broader words."}`,
            },
      );
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
    },
    onError: () => setNotice(null),
  });

  /** Opens a page of the saved-list matches: only that page's jobs are fetched, so any page opens quickly. No AI is used. */
  const openPage = useMutation({
    mutationFn: ({ target, sort }: { target: number; sort: SortBy }) =>
      api.pageJobSearch({ ...(lastCriteria.current ?? toApiCriteria(current)), count: PAGE_SIZE, page: target, sort }),
    onSuccess: (r, v) => {
      // the jobs go straight into the list's data, so the page shows at once while the list refreshes behind it
      qc.setQueryData<JobSearchResultOut[]>(["job-search-results"], (old) => {
        const have = new Set((old ?? []).map((x) => x.id));
        return [...(old ?? []), ...r.results.filter((x) => !have.has(x.id))];
      });
      setServerPages((p) => ({ ...p, [v.target]: r.results.map((x) => x.id) }));
      setMatchTotal(r.total);
      setPage(v.target);
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
    },
  });

  /** A new order re-sorts the whole list, so the pages are fetched again; the number of pages stays the same. */
  const changeSort = (value: SortBy) => {
    setSortBy(value);
    setServerPages({});
    setPage(1);
    if (serverMode && (value !== "search" || webMerged)) openPage.mutate({ target: 1, sort: value });
  };

  const goToPage = (target: number) => {
    if (openPage.isPending || target < 1 || target > totalPages || target === currentPage) return;
    if (!serverMode || (sortBy === "search" && target === 1 && !webMerged) || serverPages[target]) setPage(target);
    else openPage.mutate({ target, sort: sortBy });
  };

  const add = useMutation({
    mutationFn: (id: number) => api.addSearchResult(id),
    onSuccess: (r) => {
      setNotice({
        kind: "added",
        jobId: r.job.id,
        text: r.from_summary
          ? `Added "${r.job.title}" to Jobs, from the search summary. The posting page couldn't be read, so open it to check the details.`
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
  };

  const deleteSavedSearch = (name: string) => {
    const next = savedList.filter((s) => s.name !== name);
    setSavedList(next);
    storeSavedSearches(next);
  };

  /** What is narrowing the search right now, each with a way to clear it. */
  const filterChips: { key: string; text: string; clear: () => void }[] = [];
  if (location.trim()) filterChips.push({ key: "loc", text: location.trim(), clear: () => setLocation("") });
  if (workType !== "any") {
    const names = { remote: "Remote", hybrid: "Hybrid", onsite: "On site" } as const;
    filterChips.push({ key: "wt", text: names[workType as keyof typeof names] ?? String(workType), clear: () => setWorkType("any") });
  }
  if (within) filterChips.push({ key: "within", text: `Last ${within} days`, clear: () => setWithin(0) });
  const salaryNumber = parseInt(targetSalary.replace(/[^0-9]/g, ""), 10);
  if (Number.isFinite(salaryNumber) && salaryNumber > 0) {
    filterChips.push({
      key: "pay",
      text: `Pay $${salaryNumber.toLocaleString("en-US")} or more`,
      clear: () => setTargetSalary(""),
    });
  }
  if (requireSalary) filterChips.push({ key: "reqpay", text: "Pay must be listed", clear: () => setRequireSalary(false) });
  for (const k of keywords) filterChips.push({ key: `kw-${k}`, text: `Keyword: ${k}`, clear: () => setKeywords(keywords.filter((x) => x !== k)) });
  for (const x of exclude) filterChips.push({ key: `ex-${x}`, text: `Leaving out ${x}`, clear: () => setExclude(exclude.filter((y) => y !== x)) });
  const clearFilters = () => {
    setTitles([]);
    setTitleDraft("");
    setLocation("");
    setWorkType("any");
    setWithin(0);
    setTargetSalary("");
    setRequireSalary(false);
    setKeywords([]);
    setExclude([]);
  };

  /** Not interested: hide these results now. Hiding a company also adds it to the companies to leave out, so it stays gone. */
  const hideMany = useMutation({
    mutationFn: async (ids: number[]) => {
      for (const id of ids) await api.removeSearchResult(id);
      return ids.length;
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["job-search-results"] }),
  });
  const hideCompany = (r: JobSearchResultOut) => {
    const name = r.company.trim();
    if (!name) return;
    const ids = items.filter((x) => x.company.trim().toLowerCase() === name.toLowerCase()).map((x) => x.id);
    const next = exclude.some((x) => x.toLowerCase() === name.toLowerCase()) ? exclude : [...exclude, name];
    setExclude(next);
    try {
      const raw = window.localStorage.getItem(SAVED_KEY);
      const base = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
      window.localStorage.setItem(SAVED_KEY, JSON.stringify({ ...base, exclude: next.join(", ") }));
    } catch {
      // remembering the list is a convenience only
    }
    setNotice({ kind: "info", text: `Hid ${ids.length} ${ids.length === 1 ? "job" : "jobs"} from ${name}. Future searches leave them out.` });
    hideMany.mutate(ids);
  };
  const hideTitle = (r: JobSearchResultOut) => {
    const t = r.title.trim().toLowerCase();
    const ids = items.filter((x) => x.title.trim().toLowerCase() === t).map((x) => x.id);
    setNotice({ kind: "info", text: `Hid ${ids.length} ${ids.length === 1 ? "job" : "jobs"} titled "${r.title}".` });
    hideMany.mutate(ids);
  };

  const busyId = add.isPending ? add.variables : remove.isPending ? remove.variables : score.isPending ? score.variables : null;
  const hiding = hideMany.isPending;
  const canSearch = withDraft(titles, titleDraft).join(", ").length >= 2 && !search.isPending;
  const canSave = withDraft(titles, titleDraft).length > 0 && !activeSaved;

  // The job shown on the right. Falls back to the first one when the chosen job is gone (added or hidden).
  const selected = pageItems.find((r) => r.id === selectedId) ?? pageItems[0] ?? null;

  // Filters in use, shown as pills under the search bar. The place lives in the search bar itself.
  const pills = filterChips.filter((c) => c.key !== "loc");

  /** What was searched, for the lines above the results. */
  const searchedFor = (() => {
    const c = searched ?? current;
    const t = splitList(c.titles).join(", ");
    return c.location?.trim() ? `${t} in ${c.location.trim()}` : t;
  })();
  const stale = !!searched && !search.isPending && items.length > 0 && !sameCriteria(searched, current);
  const matchWord = totalMatches === 1 ? "match" : "matches";

  const openFilters = () => setFiltersOpen(true);

  return (
    <div className="space-y-4">
      <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink-900">Job Search</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSearch) search.mutate();
        }}
        className="flex flex-wrap items-center gap-2 rounded-[20px] border border-[#e9e6f4] bg-white p-2.5 shadow-soft"
      >
        <div className="flex min-w-[260px] flex-[1_1_340px] items-center gap-2 px-2.5 py-1">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-[18px] w-[18px] shrink-0 text-ink-500" aria-hidden="true">
            <circle cx="11" cy="11" r="6.5" />
            <path d="M16 16l4 4" />
          </svg>
          <div className="min-w-0 flex-1">
            <ChipInput
              variant="title"
              label="Job titles"
              values={titles}
              onChange={setTitles}
              draft={titleDraft}
              onDraft={setTitleDraft}
              placeholder="Job titles, like project manager"
              maxLength={100}
              suggest="title"
            />
          </div>
        </div>
        <div className="hidden h-7 w-px bg-[#e9e6f4] sm:block" />
        <div className="relative flex min-w-[200px] flex-[0_1_260px] items-center">
          <label htmlFor="js-location" className="sr-only">
            Location
          </label>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="pointer-events-none absolute left-3 h-[18px] w-[18px] text-ink-500" aria-hidden="true">
            <path d="M12 21s7-6.2 7-11.5A7 7 0 005 9.5C5 14.8 12 21 12 21z" />
            <circle cx="12" cy="9.5" r="2.5" />
          </svg>
          <SuggestInput
            id="js-location"
            value={location}
            onChange={setLocation}
            kind="place"
            placeholder="City, state, or United States"
            maxLength={200}
            className="w-full rounded-xl border border-transparent bg-transparent py-2.5 pl-10 pr-3 text-[14px] text-ink-900 placeholder:text-ink-400 hover:border-[#ddd8f3] focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200"
          />
        </div>
        <button
          type="submit"
          disabled={!canSearch}
          className={`h-[46px] rounded-xl bg-brand-500 px-7 text-[15px] font-semibold text-white transition hover:bg-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:opacity-50 ${search.isPending ? "ai-working" : ""}`}
        >
          {search.isPending ? "Searching..." : "Search"}
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        {pills.map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={openFilters}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-brand-500 bg-brand-100 shadow-pill pl-3.5 pr-3 text-[13px] font-semibold text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-200"
          >
            {c.text}
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        ))}
        {workType === "any" && (
          <button
            type="button"
            onClick={openFilters}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[#ddd8f3] bg-white shadow-pill px-3.5 text-[13px] font-semibold text-ink-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200"
          >
            Work type
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        )}
        <div className="relative">
          <button
            type="button"
            onClick={() => setFiltersOpen((v) => !v)}
            aria-expanded={filtersOpen}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[#ddd8f3] bg-white shadow-pill px-3.5 text-[13px] font-semibold text-ink-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-[15px] w-[15px]" aria-hidden="true">
              <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
              <circle cx="16" cy="7" r="2" />
              <circle cx="8" cy="17" r="2" />
            </svg>
            All filters
          </button>
          {filtersOpen && (
            <FiltersPopover
              onClose={() => setFiltersOpen(false)}
              workType={workType}
              setWorkType={setWorkType}
              within={within}
              setWithin={setWithin}
              keywords={keywords}
              setKeywords={setKeywords}
              keywordDraft={keywordDraft}
              setKeywordDraft={setKeywordDraft}
              exclude={exclude}
              setExclude={setExclude}
              excludeDraft={excludeDraft}
              setExcludeDraft={setExcludeDraft}
              targetSalary={targetSalary}
              setTargetSalary={setTargetSalary}
              requireSalary={requireSalary}
              setRequireSalary={setRequireSalary}
              onClear={clearFilters}
              onSearch={() => search.mutate()}
              canSearch={canSearch}
            />
          )}
        </div>
        {pills.length > 0 && (
          <button type="button" onClick={clearFilters} className="h-9 px-1.5 text-[13px] font-semibold text-brand-600 hover:text-brand-700 hover:underline">
            Clear all
          </button>
        )}
        <span className="flex-1" />
        <div className="relative">
          <button
            type="button"
            onClick={() => setSavedOpen((v) => !v)}
            aria-expanded={savedOpen}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-[#ddd8f3] bg-white shadow-pill px-3 text-[13px] font-semibold text-ink-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-[15px] w-[15px]" aria-hidden="true">
              <path d="M7 4h10v16l-5-4-5 4z" />
            </svg>
            {activeSaved ? `Saved searches: ${activeSaved.name}` : "Saved searches"}
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
          {savedOpen && (
            <SavedMenu
              onClose={() => setSavedOpen(false)}
              list={savedList}
              activeName={activeSaved?.name}
              canSave={canSave}
              onLoad={(s) => {
                loadSavedSearch(s);
                setSavedOpen(false);
              }}
              onForget={deleteSavedSearch}
              onSave={() => {
                saveThisSearch();
                setSavedOpen(false);
              }}
            />
          )}
        </div>
      </div>

      {search.isError && (
        <p className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
          {errorText(search.error)}
        </p>
      )}
      {openPage.isError && (
        <p className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
          {errorText(openPage.error)}
        </p>
      )}
      {(add.isError || remove.isError) && (
        <p className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
          {errorText(add.error ?? remove.error)}
        </p>
      )}

      {notice && (items.length > 0 || notice.kind === "added") && (
        <div
          role="status"
          className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl px-4 py-2.5 text-sm font-semibold ${
            notice.kind === "added" ? "bg-[#e8f6ee] text-[#17603f]" : "bg-brand-50 text-brand-700"
          }`}
        >
          <span>{notice.text}</span>
          {notice.kind === "added" && (
            <Link to={notice.jobId ? `/jobs?highlight=${notice.jobId}` : "/jobs"} className="underline">
              Go to job listing
            </Link>
          )}
          <button type="button" onClick={() => setNotice(null)} className="ml-auto rounded-full px-3 py-1 text-[13px] font-bold hover:bg-black/5 focus:outline-none focus:ring-2 focus:ring-brand-200">
            Clear
          </button>
        </div>
      )}

      {stale && (
        <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[13.5px] font-semibold text-[#92400e]">
          <span>These results are from your last search ({searchedFor}).</span>
          <button
            type="button"
            onClick={() => canSearch && search.mutate()}
            disabled={!canSearch}
            className="ml-auto h-9 rounded-full bg-brand-500 px-4 text-[13px] font-bold text-white hover:bg-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:opacity-50"
          >
            Search again
          </button>
        </div>
      )}

      {results.isLoading ? (
        <p className="text-sm text-ink-500">Loading...</p>
      ) : search.isPending ? (
        <div aria-busy="true" className="space-y-3">
          <div className="flex flex-wrap items-center gap-5 rounded-[20px] bg-white px-6 py-5 shadow-soft">
            <OtterTile size={72} />
            <div className="min-w-[240px] flex-1">
              <h2 role="status" className="mb-2.5 text-base font-bold text-ink-900">
                Searching for {searchedFor}
              </h2>
              <ul className="mb-3.5 grid gap-1.5 text-[13.5px] font-semibold">
                {["Searching saved employers", "Searching the web", "Checking each job is still open"].map((label, i) => (
                  <li key={label} className={`flex items-center gap-2.5 ${i <= step ? "text-ink-900" : "text-ink-500"}`}>
                    {i < step ? (
                      <span className="grid h-[18px] w-[18px] place-items-center rounded-full bg-[#12b76a] text-[11px] font-extrabold text-white" aria-hidden="true">
                        &#10003;
                      </span>
                    ) : i === step ? (
                      <span className="h-[18px] w-[18px] animate-spin rounded-full border-2 border-brand-500 border-t-transparent" aria-hidden="true" />
                    ) : (
                      <span className="h-[18px] w-[18px] rounded-full border-2 border-[#d3d0ff]" aria-hidden="true" />
                    )}
                    {label}
                  </li>
                ))}
              </ul>
              <div className="h-2 overflow-hidden rounded-full bg-[#e5e0fa]" aria-hidden="true">
                <div className="h-full rounded-full bg-gradient-to-r from-[#8b87ff] to-[#5b57f5] transition-all duration-700" style={{ width: `${8 + step * 38}%` }} />
              </div>
              <p className="mt-2 text-xs text-ink-500">This can take up to a minute.</p>
            </div>
          </div>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-[62px] animate-pulse rounded-2xl bg-white/70" aria-hidden="true" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-[20px] border border-[#e9e6f4] bg-white p-10 text-center shadow-soft">
          {searched && justSearched ? (
            <>
              <h2 className="text-base font-bold text-ink-900">No jobs matched this search</h2>
              <p className="mt-1 text-sm text-ink-500">Try fewer filters, a wider area, or another title.</p>
              <button
                type="button"
                onClick={clearFilters}
                className="mt-4 h-10 rounded-full border border-[#ddd8f3] bg-white px-5 text-sm font-bold text-brand-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200"
              >
                Clear filters
              </button>
            </>
          ) : (
            <>
              <h2 className="text-base font-bold text-ink-900">No matches yet</h2>
              <p className="mt-1 text-sm text-ink-500">Add a job title above and hit Search.</p>
            </>
          )}
        </div>
      ) : (
        <div className="grid items-start gap-x-5 gap-y-3 lg:grid-cols-[minmax(0,480px)_minmax(0,1fr)]">
          <div className="flex items-center gap-3 lg:col-span-2">
            <p role="status" className="min-w-0 px-1 text-sm text-ink-700">
              <b className="font-extrabold text-ink-900">
                {totalMatches.toLocaleString("en-US")}
                {coverage?.matches_capped && matchTotal === null ? "+" : ""} {matchWord}
              </b>
              {searchedFor ? ` for ${searchedFor}` : ""}
              {justSearched && !stale ? <span className="text-ink-500"> &middot; searched just now</span> : null}
            </p>
            <span className="flex-1" />
            <label className="flex shrink-0 items-center gap-1 text-[13px] font-semibold text-ink-700">
              Sort
              <select
                value={sortBy}
                onChange={(e) => changeSort(e.target.value === "newest" ? "newest" : "search")}
                className="cursor-pointer rounded-lg bg-transparent py-1 pl-1 pr-1 text-[13px] font-bold text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200"
              >
                <option value="search">Best match</option>
                <option value="newest">Newest</option>
              </select>
            </label>
            <div className="flex shrink-0 items-center gap-1">
              <MoreMenu>
                {anyAutofill && (
                  <MenuItem onClick={() => setAutofillOnly((v) => !v)}>
                    {autofillOnly ? "Show all jobs" : "Show only autofill ready"}
                  </MenuItem>
                )}
                <MenuItem danger onClick={() => setConfirmClear(true)}>
                  Clear all
                </MenuItem>
              </MoreMenu>
            </div>
          </div>

          {confirmClear && (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-800 lg:col-span-2">
              Remove all {items.length} matches?
              <span className="flex gap-2">
                <button
                  type="button"
                  onClick={() => clear.mutate()}
                  disabled={clear.isPending}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 disabled:opacity-50"
                >
                  Yes, remove all
                </button>
                <button type="button" onClick={() => setConfirmClear(false)} className="rounded-lg px-3 py-1.5 text-xs font-bold text-red-800 hover:bg-red-100">
                  Keep
                </button>
              </span>
            </div>
          )}
          <div
            ref={listRef}
            className="overflow-y-auto overscroll-contain rounded-[20px] border border-[#e9e6f4] bg-white shadow-soft"
            style={{ maxHeight: "max(480px, calc(100vh - 300px))", scrollbarWidth: "thin", scrollbarColor: "#ddd8f3 transparent" }}
          >
            {shown.length === 0 ? (
              <p className="p-5 text-sm text-ink-500">
                None of these can be autofilled. Choose "Show all jobs" in the menu above to see all {items.length}.
              </p>
            ) : (
              <ul>
                {pageItems.map((r) => (
                  <ResultRow key={r.id} r={r} selected={selected?.id === r.id} onPick={() => setSelectedId(r.id)} />
                ))}
              </ul>
            )}
            {totalPages > 1 && (
              <Pager page={currentPage} total={totalPages} busy={openPage.isPending} onPick={goToPage} />
            )}
          </div>

          {selected && (
            <JobDetail
              key={selected.id}
              r={selected}
              busy={busyId === selected.id || hiding}
              scoring={score.isPending && score.variables === selected.id}
              problem={score.isError && score.variables === selected.id ? errorText(score.error) : undefined}
              onScore={() => score.mutate(selected.id)}
              onAdd={() => add.mutate(selected.id)}
              onRemove={() => remove.mutate(selected.id)}
              onHideCompany={() => hideCompany(selected)}
              onHideTitle={() => hideTitle(selected)}
            />
          )}
        </div>
      )}

      <EmployersPanel />
    </div>
  );
}

const CARD =
  "rounded-[20px] border border-[#e9e6f4] bg-white shadow-soft";

/** "Today", "Yesterday", "8 days ago", then a short date: the same wording as every other page. */
function agoText(date?: string | null): string {
  return formatPosted(date) ?? "Date not listed";
}

/** The pay in the one pay style; text that has no dollar amount is shown as written, without dashes. */
function payText(text?: string | null): string | null {
  if (!text || !text.trim()) return null;
  return formatPayText(text) ?? text.trim().replace(/[\u2013\u2014]/g, " to ");
}

const WORK_NAMES: Record<string, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On site" };

// The work type as text: not repeated when the place already says it ("Remote, Ohio"), and none when it is not known.
function workTypeText(r: { work_type?: string | null; location?: string | null }): string | null {
  if (!r.work_type) return null;
  const name = WORK_NAMES[r.work_type] ?? r.work_type;
  return r.location && r.location.toLowerCase().includes(name.toLowerCase()) ? null : name;
}

/** How well the posting fits the search: a level and the number behind it. */
function fitLevel(score: number | null | undefined): { word: string; num: number | null; cls: string } {
  if (score == null) return { word: "Possible match", num: null, cls: "bg-[#f0eff7] text-ink-700" };
  const num = Math.round(score * 100);
  if (num >= 90) return { word: "Top match", num, cls: "bg-[#e8f6ee] text-[#17603f]" };
  if (num >= 75) return { word: "Strong match", num, cls: "bg-[#e8e6ff] text-[#3b36b8]" };
  if (num >= 55) return { word: "Good match", num, cls: "bg-[#fff4d6] text-[#8a5a00]" };
  return { word: "Possible match", num, cls: "bg-[#f0eff7] text-ink-700" };
}

function FitPill({ score }: { score: number | null | undefined }) {
  const f = fitLevel(score);
  return (
    <span className={`inline-flex h-6 items-center whitespace-nowrap rounded-full px-2.5 text-xs font-bold ${f.cls}`}>
      {f.word}
      {f.num !== null && <> &middot; {f.num}</>}
    </span>
  );
}

/** Page numbers under the list: 1 2 3 ... last, then Next. */
function pageNumbers(page: number, total: number): (number | "gap")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (page <= 3) return [1, 2, 3, "gap", total];
  if (page >= total - 2) return [1, "gap", total - 2, total - 1, total];
  return [1, "gap", page - 1, page, page + 1, "gap", total];
}

function Pager({ page, total, busy, onPick }: { page: number; total: number; busy: boolean; onPick: (n: number) => void }) {
  const btn =
    "grid h-[38px] min-w-[38px] place-items-center rounded-xl border border-[#e9e6f4] bg-white px-2 text-[13px] font-bold text-brand-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:opacity-50";
  const link = "h-[38px] px-2 text-[13px] font-bold text-brand-600 hover:underline focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:opacity-50";
  return (
    <nav aria-label="Pages of results" className="sticky bottom-0 flex flex-wrap items-center justify-center gap-1.5 border-t border-[#ebe8f6] bg-white p-3.5">
      {page > 1 && (
        <button type="button" className={link} disabled={busy} onClick={() => onPick(page - 1)}>
          Back
        </button>
      )}
      {pageNumbers(page, total).map((n, i) =>
        n === "gap" ? (
          <span key={`g${i}`} className="px-1 text-ink-500" aria-hidden="true">
            ...
          </span>
        ) : (
          <button
            key={n}
            type="button"
            disabled={busy}
            onClick={() => onPick(n)}
            aria-current={n === page ? "page" : undefined}
            aria-label={`Page ${n} of ${total}`}
            className={n === page ? "grid h-[38px] min-w-[38px] place-items-center rounded-xl bg-brand-500 px-2 text-[13px] font-bold text-white" : btn}
          >
            {n}
          </button>
        ),
      )}
      {page < total && (
        <button type="button" className={link} disabled={busy} onClick={() => onPick(page + 1)}>
          {busy ? "Looking..." : "Next"}
        </button>
      )}
    </nav>
  );
}

function ResultRow({ r, selected, onPick }: { r: JobSearchResultOut; selected: boolean; onPick: () => void }) {
  const meta = [r.location, workTypeText(r), payText(r.salary_text)].filter(Boolean).join(" \u00b7 ");
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        aria-pressed={selected}
        aria-label={`${r.title} at ${r.company}`}
        className={`flex w-full items-start gap-3.5 border-b border-[#ebe8f6] px-5 py-4 text-left transition last:border-b-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400 ${
          selected ? "bg-brand-50 shadow-[inset_3px_0_0_#5b57f5]" : "hover:bg-[#faf9ff]"
        }`}
      >
        <span className="block min-w-0 flex-1">
          <span className="block text-[15px] font-bold text-ink-900">{r.title}</span>
          <span className="mt-0.5 block text-[14px] text-ink-700">{r.company}</span>
          {meta && <span className="mt-1 block text-[13px] text-ink-500">{meta}</span>}
          <span className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <FitPill score={r.fit_score} />
            {autofillSite(r.url) && (
              <span className="inline-flex h-6 items-center whitespace-nowrap rounded-full bg-[#e8f6ee] px-2.5 text-xs font-bold text-[#17603f]">Autofill ready</span>
            )}
            {mayBeClosed(r.posted_at) && (
              <span className="inline-flex h-6 items-center whitespace-nowrap rounded-full bg-amber-50 px-2.5 text-xs font-bold text-amber-700">May be closed</span>
            )}
          </span>
        </span>
        <span className="shrink-0 whitespace-nowrap text-[13px] font-medium text-ink-500">{agoText(r.posted_at)}</span>
      </button>
    </li>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Not listed";
  }
}

function FactCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-bold text-ink-500">{label}</div>
      <div className="mt-0.5 text-sm font-bold text-ink-900">{children}</div>
    </div>
  );
}

/** The reasons a job fits, one per line. The note arrives as one sentence with parts split by a middle dot. */
function fitReasons(note?: string | null): string[] {
  if (!note) return [];
  return note
    .replace(/\s*\u00b7\s*Posted [^\u00b7]*$/, "")
    .split(/\s*\u00b7\s*/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function JobDetail({
  r,
  busy,
  scoring,
  problem,
  onScore,
  onAdd,
  onRemove,
  onHideCompany,
  onHideTitle,
}: {
  r: JobSearchResultOut;
  busy: boolean;
  scoring: boolean;
  /** Why the last attempt to check this one failed, such as a closed posting. */
  problem?: string;
  onScore: () => void;
  onAdd: () => void;
  onRemove: () => void;
  onHideCompany: () => void;
  onHideTitle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const posted = formatPostedBoth(r.posted_at);
  const site = autofillSite(r.url);
  // A score that came only from the one-line summary is not shown; it would look surer than it is.
  const score = r.match_from_page === false ? null : (r.match_score ?? null);
  const gaps = (r.match_gaps ?? []).slice(0, 3);
  const reasons = fitReasons(r.fit_note);
  const about = r.summary || "";
  const LONG = 220;
  const clipped = !expanded && about.length > LONG;
  const where = [r.location || "Not listed", workTypeText(r)].filter(Boolean).join(" \u00b7 ");
  return (
    <div className={`${CARD} flex min-w-0 flex-col gap-5 p-6 sm:p-7 lg:sticky lg:top-4`}>
      <div>
        <h2 className="text-[21px] font-bold leading-tight tracking-tight text-ink-900">{r.title}</h2>
        {r.company && <div className="mt-0.5 text-sm font-bold text-ink-500">{r.company}</div>}
      </div>
      <div className="flex flex-wrap gap-2">
        <FitPill score={r.fit_score} />
        {site && (
          <span className="inline-flex h-6 items-center whitespace-nowrap rounded-full bg-[#e8f6ee] px-2.5 text-xs font-bold text-[#17603f]">Autofill ready on {site}</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onAdd}
          disabled={busy}
          className="h-11 rounded-full bg-brand-500 px-6 text-[15px] font-bold text-white transition hover:bg-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:opacity-50"
        >
          {busy && !scoring ? "Working..." : "Add to jobs"}
        </button>
        <a
          href={r.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex h-11 items-center rounded-full border border-[#ddd8f3] px-5 text-[15px] font-bold text-ink-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200"
        >
          View posting
        </a>
        <MoreMenu wide>
          {score !== null && (
            <MenuItem onClick={onScore} disabled={busy}>
              Check against my resume again
            </MenuItem>
          )}
          <MenuItem onClick={onRemove} disabled={busy}>
            Remove from results
          </MenuItem>
          {r.company && (
            <MenuItem onClick={onHideCompany} disabled={busy}>
              Hide this company
            </MenuItem>
          )}
          <MenuItem onClick={onHideTitle} disabled={busy}>
            Hide this title
          </MenuItem>
        </MoreMenu>
      </div>

      {!r.grounded && (
        <div className="rounded-xl bg-[#fff4dc] px-4 py-3 text-sm text-[#8a5a00]">
          Found on the web. We couldn&apos;t confirm it&apos;s still open, so check before you apply.
        </div>
      )}
      {mayBeClosed(r.posted_at) && (
        <div className="rounded-xl bg-[#fff4dc] px-4 py-3 text-sm text-[#8a5a00]">Posted over 60 days ago. It may have been filled, so check before you apply.</div>
      )}

      <div className="grid grid-cols-1 gap-x-5 gap-y-3.5 border-y border-[#ebe8f6] py-3.5 sm:grid-cols-2">
        <FactCell label="Location">{where}</FactCell>
        <FactCell label="Pay">{payText(r.salary_text) ?? "Not listed"}</FactCell>
        <FactCell label="Posted">{posted ? inSentence(posted) : "Not listed"}</FactCell>
        <FactCell label="Applies through">{site ?? hostOf(r.url)}</FactCell>
      </div>

      {reasons.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-bold text-ink-900">Why it fits your search</h3>
          <ul className="grid gap-1.5">
            {reasons.map((x) => (
              <li key={x} className="flex gap-2 text-[13.5px] leading-snug text-ink-900">
                <span className="font-extrabold text-[#047857]" aria-hidden="true">
                  &#10003;
                </span>
                {x}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-sm font-bold text-ink-900">About the role</h3>
        <p className="text-[13.5px] leading-relaxed text-ink-700">
          {about ? (clipped ? `${about.slice(0, LONG).trimEnd()}...` : about) : "No description saved for this one. Open the posting to read it."}
        </p>
        {about.length > LONG && (
          <button type="button" onClick={() => setExpanded((v) => !v)} className="mt-1 text-[13px] font-bold text-brand-600 hover:underline focus:outline-none focus:ring-2 focus:ring-brand-200">
            {expanded ? "Show less" : "Read more"}
          </button>
        )}
      </section>

      <div className="flex flex-col gap-3 rounded-2xl border border-[#e9e6f4] bg-[#faf9ff] p-4">
        {score !== null ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3.5">
              <Ring value={score} size={56} stroke={6} color={scoreColor(score)}>
                <span className="text-base font-bold text-ink-900">{Math.round(score * 100)}</span>
              </Ring>
              <div>
                <div className="text-sm font-bold text-ink-900">{scoreLabel(score)}</div>
                <div className="text-xs text-ink-500">How well your resume fits this job</div>
              </div>
            </div>
            {r.match_summary && <p className="text-[13.5px] leading-relaxed text-ink-700">{r.match_summary}</p>}
            {gaps.length > 0 && <p className="text-[13.5px] leading-relaxed text-ink-500">Not on your resume: {gaps.join(", ")}</p>}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-[160px] flex-1">
              <div className="text-sm font-bold text-ink-900">How well does your resume fit?</div>
              <div className="mt-0.5 text-xs text-ink-500">{scoring ? "Comparing this job with your resume. Up to a minute." : "Takes up to a minute."}</div>
            </div>
            <button
              type="button"
              onClick={onScore}
              disabled={busy}
              className={`h-10 rounded-full border border-[#ddd8f3] bg-white px-[18px] text-sm font-bold text-brand-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:opacity-50 ${scoring ? "ai-working" : ""}`}
            >
              {scoring ? "Checking..." : "Check my resume"}
            </button>
          </div>
        )}
        {problem && !scoring && (
          <p className="rounded-xl bg-[#fff4dc] px-3 py-2 text-[13px] text-[#8a5a00]" role="alert">
            {problem}
          </p>
        )}
      </div>
    </div>
  );
}

function useClickAway(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);
  return ref;
}

function Segmented<T extends string | number>({
  label,
  options,
  value,
  onPick,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onPick: (v: T) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-semibold text-ink-900">{label}</span>
      <div className="flex flex-wrap gap-0.5 self-start rounded-xl bg-brand-50 p-1" role="group" aria-label={label}>
        {options.map((o) => {
          const on = o.value === value;
          return (
            <button
              key={String(o.value)}
              type="button"
              aria-pressed={on}
              onClick={() => onPick(o.value)}
              className={`h-9 rounded-lg px-3.5 text-[13px] font-semibold transition ${
                on ? "bg-white text-brand-700 shadow-[0_1px_3px_rgba(31,27,46,0.12)]" : "text-ink-700 hover:text-brand-700"
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function formatPay(v: string): string {
  const digits = v.replace(/[^0-9]/g, "").slice(0, 9);
  return digits ? `$${Number(digits).toLocaleString("en-US")}` : "";
}

const inputCls =
  "h-[42px] w-full rounded-[10px] border border-[#ddd8f3] bg-white px-3.5 text-sm text-ink-900 placeholder:text-ink-400 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200";

function FiltersPopover(p: {
  onClose: () => void;
  workType: JobSearchCriteria["work_type"];
  setWorkType: (v: JobSearchCriteria["work_type"]) => void;
  within: JobSearchCriteria["posted_within_days"];
  setWithin: (v: JobSearchCriteria["posted_within_days"]) => void;
  keywords: string[];
  setKeywords: (v: string[]) => void;
  keywordDraft: string;
  setKeywordDraft: (v: string) => void;
  exclude: string[];
  setExclude: (v: string[]) => void;
  excludeDraft: string;
  setExcludeDraft: (v: string) => void;
  targetSalary: string;
  setTargetSalary: (v: string) => void;
  requireSalary: boolean;
  setRequireSalary: (v: boolean) => void;
  onClear: () => void;
  onSearch: () => void;
  canSearch: boolean;
}) {
  const ref = useClickAway(p.onClose);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="All filters"
      className="absolute left-0 top-11 z-30 flex max-h-[80vh] w-[520px] max-w-[calc(100vw-48px)] flex-col gap-[22px] overflow-y-auto rounded-[20px] border border-[#e9e6f4] bg-white p-6 shadow-[0_12px_32px_rgba(75,50,184,0.18)]"
    >
      <Segmented
        label="Work type"
        value={p.workType as string}
        onPick={(v) => p.setWorkType(v as JobSearchCriteria["work_type"])}
        options={[
          { value: "any", label: "Any" },
          { value: "remote", label: "Remote" },
          { value: "hybrid", label: "Hybrid" },
          { value: "onsite", label: "On site" },
        ]}
      />
      <Segmented
        label="Posted"
        value={p.within as number}
        onPick={(v) => p.setWithin(v as JobSearchCriteria["posted_within_days"])}
        options={[
          { value: 0, label: "Any time" },
          { value: 7, label: "7 days" },
          { value: 14, label: "14 days" },
          { value: 30, label: "30 days" },
        ]}
      />
      <div className="flex flex-col gap-2">
        <span className="text-sm font-semibold text-ink-900">Keywords</span>
        <ChipInput
          label="Keywords"
          values={p.keywords}
          onChange={p.setKeywords}
          draft={p.keywordDraft}
          onDraft={p.setKeywordDraft}
          placeholder="denials, Epic, Medicare"
          suggest="keyword"
        />
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-sm font-semibold text-ink-900">Leave out companies</span>
        <ChipInput
          label="Companies to leave out"
          values={p.exclude}
          onChange={p.setExclude}
          draft={p.excludeDraft}
          onDraft={p.setExcludeDraft}
          placeholder="Add a company"
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor="js-salary" className="text-sm font-semibold text-ink-900">
          Desired Salary
        </label>
        <input id="js-salary" className={inputCls} inputMode="numeric" value={formatPay(p.targetSalary)} onChange={(e) => p.setTargetSalary(formatPay(e.target.value))} placeholder="$85,000" />
        <label className="mt-2.5 flex items-center gap-2.5 text-sm text-ink-700">
          <input
            type="checkbox"
            checked={p.requireSalary}
            onChange={(e) => p.setRequireSalary(e.target.checked)}
            className="h-[18px] w-[18px] accent-[#5b57f5]"
          />
          Only show jobs that post their pay
        </label>
      </div>
      <div className="flex items-center justify-between border-t border-[#ebe8f6] pt-[18px]">
        <button type="button" onClick={p.onClear} className="py-2 text-sm font-semibold text-brand-600 hover:text-brand-700 hover:underline">
          Clear all
        </button>
        <button
          type="button"
          onClick={() => {
            p.onClose();
            p.onSearch();
          }}
          disabled={!p.canSearch}
          className="h-11 rounded-xl bg-brand-500 px-7 text-[15px] font-semibold text-white hover:bg-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Search
        </button>
      </div>
    </div>
  );
}

function SavedMenu({
  onClose,
  list,
  activeName,
  canSave,
  onLoad,
  onForget,
  onSave,
}: {
  onClose: () => void;
  list: SavedSearch[];
  activeName?: string;
  canSave: boolean;
  onLoad: (s: SavedSearch) => void;
  onForget: (name: string) => void;
  onSave: () => void;
}) {
  const ref = useClickAway(onClose);
  return (
    <div ref={ref} className="absolute right-0 top-11 z-30 w-72 rounded-2xl border border-[#e9e6f4] bg-white p-1.5 shadow-[0_12px_32px_rgba(75,50,184,0.18)]">
      {list.length === 0 && <p className="px-3 py-2 text-sm text-ink-500">No saved searches yet.</p>}
      {list.map((s) => (
        <div key={s.name} className="flex items-center rounded-xl hover:bg-brand-50">
          <button
            type="button"
            onClick={() => onLoad(s)}
            aria-pressed={activeName === s.name}
            className={`min-w-0 flex-1 truncate px-3 py-2 text-left text-sm font-medium ${activeName === s.name ? "text-brand-700" : "text-ink-700"}`}
          >
            {s.name}
          </button>
          <button
            type="button"
            aria-label={`Forget saved search ${s.name}`}
            onClick={() => onForget(s.name)}
            className="mr-1 flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold text-ink-500 hover:bg-white"
          >
            &#10005;
          </button>
        </div>
      ))}
      {canSave && (
        <button type="button" onClick={onSave} className="mt-1 block w-full rounded-xl border-t border-[#ebe8f6] px-3 py-2 text-left text-sm font-semibold text-brand-600 hover:bg-brand-50">
          + Save this search
        </button>
      )}
    </div>
  );
}
