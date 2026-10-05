import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Button, Card, inputClass } from "@/components/ui";
import { formatPosted } from "@/lib/jobText";
import type { JobSearchCriteria, JobSearchResultOut } from "@/types/api";

const labelClass = "mb-1 block text-xs font-semibold text-ink-500";

const SAVED_KEY = "job-search-criteria";

interface SavedCriteria {
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

/** The last search, so the boxes are filled in next time. Stays in this browser only. */
function loadSaved(): Partial<SavedCriteria> {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY);
    return raw ? (JSON.parse(raw) as Partial<SavedCriteria>) : {};
  } catch {
    return {};
  }
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong. Try again.";
}

export function JobSearch() {
  const qc = useQueryClient();
  const [saved] = useState(loadSaved);
  const [titles, setTitles] = useState(saved.titles ?? "");
  const [location, setLocation] = useState(saved.location ?? "");
  const [workType, setWorkType] = useState<JobSearchCriteria["work_type"]>(saved.workType ?? "any");
  const [keywords, setKeywords] = useState(saved.keywords ?? "");
  const [exclude, setExclude] = useState(saved.exclude ?? "");
  const [targetSalary, setTargetSalary] = useState(saved.targetSalary ?? "");
  const [requireSalary, setRequireSalary] = useState(saved.requireSalary ?? false);
  const [within, setWithin] = useState<JobSearchCriteria["posted_within_days"]>(saved.within ?? 0);
  const [count, setCount] = useState(saved.count ?? 10);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const results = useQuery({ queryKey: ["job-search-results"], queryFn: api.listSearchResults });
  const items = (results.data ?? []).filter((r) => r.status === "new");

  const search = useMutation({
    mutationFn: () => {
      try {
        const keep: SavedCriteria = { titles, location, workType, keywords, exclude, targetSalary, requireSalary, within, count };
        window.localStorage.setItem(SAVED_KEY, JSON.stringify(keep));
      } catch {
        // saving the boxes is a convenience only
      }
      const salary = parseInt(targetSalary.replace(/[^0-9]/g, ""), 10);
      return api.runJobSearch({
        titles: titles.trim(),
        location: location.trim() || null,
        work_type: workType,
        keywords: keywords.trim() || null,
        exclude_companies: exclude.trim() || null,
        target_salary: Number.isFinite(salary) && salary > 0 ? salary : null,
        require_salary: requireSalary,
        posted_within_days: within,
        count,
      });
    },
    onSuccess: (r) => {
      setNotice(
        r.found > 0
          ? `Found ${r.found} new ${r.found === 1 ? "match" : "matches"}.${r.skipped ? ` ${r.skipped} skipped (already in your jobs, already shown, no longer open, or not a real posting link).` : ""}`
          : `No new matches. ${r.skipped ? `${r.skipped} skipped because you already have them, removed them, or they are no longer open.` : "Try broader words."}`,
      );
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
    },
    onError: () => setNotice(null),
  });

  const add = useMutation({
    mutationFn: (id: number) => api.addSearchResult(id),
    onSuccess: (r) => {
      setNotice(
        r.from_summary
          ? `Added "${r.job.title}" to Jobs, using the search summary because the posting page couldn't be read. Open the posting to check the details.`
          : `Added "${r.job.title}" to Jobs.`,
      );
      void qc.invalidateQueries({ queryKey: ["job-search-results"] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
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

  const busyId = add.isPending ? add.variables : remove.isPending ? remove.variables : null;
  const canSearch = titles.trim().length >= 2 && !search.isPending;

  return (
    <div>
      <PageHeader
        title="Job Search"
        description="Tell us what you want and we search the web for matching openings. Nothing is added to Jobs until you click Add to jobs."
        action={items.length > 0 ? <Badge tone="brand">{items.length} to review</Badge> : undefined}
      />

      <Card className="p-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSearch) search.mutate();
          }}
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          <div className="sm:col-span-2 lg:col-span-3">
            <label className={labelClass} htmlFor="js-titles">Job titles</label>
            <input
              id="js-titles"
              className={inputClass}
              value={titles}
              onChange={(e) => setTitles(e.target.value)}
              placeholder="Project manager, program manager"
              maxLength={300}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="js-location">Location</label>
            <input
              id="js-location"
              className={inputClass}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Austin, TX or United States"
              maxLength={200}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="js-type">Work type</label>
            <select
              id="js-type"
              className={inputClass}
              value={workType}
              onChange={(e) => setWorkType(e.target.value as JobSearchCriteria["work_type"])}
            >
              <option value="any">Any</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">On site</option>
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="js-salary">Salary minimum (yearly)</label>
            <input
              id="js-salary"
              className={inputClass}
              inputMode="numeric"
              value={targetSalary}
              onChange={(e) => setTargetSalary(e.target.value)}
              placeholder="80000"
            />
            <p className="mt-1 text-xs text-ink-400">Pay range midpoint must be at least this. Higher is fine.</p>
          </div>
          <div className="sm:col-span-2 lg:col-span-3">
            <label className={labelClass} htmlFor="js-exclude">Leave out these companies (optional)</label>
            <input
              id="js-exclude"
              className={inputClass}
              value={exclude}
              onChange={(e) => setExclude(e.target.value)}
              placeholder="Separate with commas"
              maxLength={300}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-ink-700 sm:col-span-2 lg:col-span-3">
            <input
              type="checkbox"
              checked={requireSalary}
              onChange={(e) => setRequireSalary(e.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-brand-500 focus:ring-brand-200"
            />
            Only show jobs that post their salary
          </label>
          <div className="sm:col-span-2">
            <label className={labelClass} htmlFor="js-keywords">Keywords (optional)</label>
            <input
              id="js-keywords"
              className={inputClass}
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="healthcare, Agile, SaaS"
              maxLength={300}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="js-within">Posted within</label>
            <select
              id="js-within"
              className={inputClass}
              value={within}
              onChange={(e) => setWithin(Number(e.target.value) as JobSearchCriteria["posted_within_days"])}
            >
              <option value={0}>Any time</option>
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="js-count">How many results</label>
            <select
              id="js-count"
              className={inputClass}
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
          <div className="flex flex-col justify-end gap-1.5 sm:col-span-2 lg:col-span-2">
            <div className="flex items-center gap-3">
              <Button type="submit" variant="primary" disabled={!canSearch}>
                {search.isPending ? "Searching..." : "Search the web"}
              </Button>
              {search.isPending && (
                <span className="text-xs text-ink-500">Searching the web. This can take up to a minute.</span>
              )}
            </div>
            <p className="text-xs text-ink-400">
              Each search uses your AI connection and costs a small amount. Only the words above are sent, nothing from your profile.
            </p>
          </div>
        </form>
        {search.isError && (
          <p className="mt-4 rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
            {errorText(search.error)}
          </p>
        )}
      </Card>

      {notice && (
        <p className="mt-4 rounded-xl bg-brand-50 px-3.5 py-2.5 text-sm text-brand-700" role="status">
          {notice}{" "}
          {notice.startsWith("Added") && (
            <Link to="/jobs" className="font-semibold underline">
              Go to Jobs
            </Link>
          )}
        </p>
      )}
      {(add.isError || remove.isError) && (
        <p className="mt-4 rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
          {errorText(add.error ?? remove.error)}
        </p>
      )}

      <div className="mt-8 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink-700">Matches</h2>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => search.mutate()} disabled={!canSearch}>
            {search.isPending ? "Searching..." : "Search again"}
          </Button>
        {items.length > 0 &&
          (confirmClear ? (
            <span className="flex items-center gap-2 text-xs text-ink-500">
              Remove all {items.length}?
              <Button size="sm" variant="danger" onClick={() => clear.mutate()} disabled={clear.isPending}>
                Yes, remove all
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmClear(false)}>
                Keep
              </Button>
            </span>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirmClear(true)}>
              Clear all
            </Button>
          ))}
        </div>
      </div>

      {results.isLoading ? (
        <p className="mt-4 text-sm text-ink-500">Loading...</p>
      ) : items.length === 0 ? (
        <Card className="mt-3 p-6 text-sm text-ink-500">
          No matches yet. Fill in the boxes above and click Search the web.
        </Card>
      ) : (
        <ul className="mt-3 space-y-3">
          {items.map((r) => (
            <ResultCard
              key={r.id}
              r={r}
              busy={busyId === r.id}
              onAdd={() => add.mutate(r.id)}
              onRemove={() => remove.mutate(r.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultCard({
  r,
  busy,
  onAdd,
  onRemove,
}: {
  r: JobSearchResultOut;
  busy: boolean;
  onAdd: () => void;
  onRemove: () => void;
}) {
  const posted = formatPosted(r.posted_at);
  const meta = [r.company, r.location, r.work_type, r.salary_text, posted ? `Posted ${posted}` : null].filter(Boolean).join("  |  ");
  return (
    <li>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-ink-900">{r.title}</h3>
            <p className="mt-0.5 text-sm text-ink-500">{meta}</p>
          </div>
          {!r.grounded && <Badge tone="warning">Link not verified</Badge>}
        </div>
        {r.summary && <p className="mt-3 text-sm leading-relaxed text-ink-700">{r.summary}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="primary" size="sm" onClick={onAdd} disabled={busy}>
            {busy ? "Working..." : "Add to jobs"}
          </Button>
          <Button size="sm" onClick={onRemove} disabled={busy}>
            Remove
          </Button>
          <a
            href={r.url}
            target="_blank"
            rel="noreferrer noopener"
            className="ml-1 text-xs font-semibold text-brand-700 underline"
          >
            View posting
          </a>
        </div>
      </Card>
    </li>
  );
}
