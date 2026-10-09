import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { Button, Card } from "@/components/ui";
import type { CoverageOut, EmployerOut } from "@/types/api";

const SYSTEM_NAMES: Record<string, string> = { workday: "Workday", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" };
const SYSTEM_ORDER = ["workday", "greenhouse", "lever", "ashby"];
const SOURCE_NOTES: Record<string, string> = {
  saved_job: "from your saved jobs",
  user_link: "added from a link",
  search: "found by a search",
  starter: "starter list",
};

const num = (v: number) => v.toLocaleString("en-US");
const plural = (v: number, one: string, many: string) => (v === 1 ? one : many);

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong. Try again.";
}

/** What the saved employer lists covered for the search that just ran. */
export function CoverageCard({ coverage }: { coverage: CoverageOut }) {
  const systems = SYSTEM_ORDER.filter((s) => coverage.by_system[s]);
  const most = Math.max(1, ...systems.map((s) => coverage.by_system[s].postings));
  const fits = `${num(coverage.matches)}${coverage.matches_capped ? "+" : ""}`;
  return (
    <section className="rounded-2xl bg-brand-50 px-5 py-4" aria-label="What this search covered">
      <p className="text-[15px] font-extrabold text-ink-900">
        Searched {num(coverage.employers)} {plural(coverage.employers, "employer", "employers")} and {num(coverage.postings)} open{" "}
        {plural(coverage.postings, "posting", "postings")}. {fits} {plural(coverage.matches, "fits", "fit")} this search.
      </p>
      <div className="mt-3 grid gap-x-6 gap-y-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {systems.map((s) => {
          const info = coverage.by_system[s];
          return (
            <div key={s} className="text-xs">
              <div className="flex justify-between font-semibold text-ink-500">
                <span>{SYSTEM_NAMES[s] ?? s}</span>
                <span className="text-ink-900">
                  {num(info.employers)} {plural(info.employers, "employer", "employers")}
                </span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-white" role="img" aria-label={`${num(info.postings)} open postings on ${SYSTEM_NAMES[s] ?? s}`}>
                <div className="h-2 rounded-full bg-brand-400" style={{ width: `${Math.max(4, Math.round((info.postings / most) * 100))}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      {coverage.waiting > 0 ? (
        <p className="mt-3 text-xs text-ink-500">
          {num(coverage.waiting)} {plural(coverage.waiting, "employer is", "employers are")} still being read for the first time. Search again in a few
          minutes to see their jobs too.
        </p>
      ) : coverage.refreshing ? (
        <p className="mt-3 text-xs text-ink-500">Updating the employer job lists in the background.</p>
      ) : null}
    </section>
  );
}

function statusLine(e: EmployerOut): { text: string; bad: boolean } {
  const note = `${SYSTEM_NAMES[e.system] ?? e.system}, ${SOURCE_NOTES[e.source] ?? e.source}`;
  if (e.status === "new") return { text: `${note}. Waiting to be read.`, bad: false };
  if (e.status === "error") return { text: `${note}. Couldn't read it last time${e.last_error ? `: ${e.last_error}` : ""}. Trying again later.`, bad: true };
  if (e.status === "unreachable") return { text: `${note}. Couldn't be read several times in a row${e.last_error ? `: ${e.last_error}` : ""}.`, bad: true };
  return { text: note, bad: false };
}

const SHOWN_AT_FIRST = 12;

/** The employers whose job lists are saved and searched: add one from a link, switch one off, update now. */
export function EmployersPanel() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [filter, setFilter] = useState("");
  const [showAll, setShowAll] = useState(false);

  const list = useQuery({
    queryKey: ["job-employers", filter],
    queryFn: () => api.listEmployers(filter),
    enabled: open,
    refetchInterval: (query) => (query.state.data?.refreshing ? 3000 : false),
  });
  const summary = useQuery({
    queryKey: ["job-employers", ""],
    queryFn: () => api.listEmployers(""),
    staleTime: 30_000,
    refetchInterval: (query) => (query.state.data?.refreshing ? 3000 : false),
  });
  const totals = summary.data;

  const refresh = () => void qc.invalidateQueries({ queryKey: ["job-employers"] });

  const add = useMutation({
    mutationFn: () => api.addEmployer(link.trim()),
    onSuccess: () => {
      setLink("");
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (e: EmployerOut) => api.setEmployerEnabled(e.id, !e.enabled),
    onSuccess: refresh,
  });
  const updateNow = useMutation({
    mutationFn: () => api.refreshEmployers(),
    onSuccess: refresh,
  });

  const rows = list.data?.employers ?? [];
  const visible = showAll || filter ? rows : rows.slice(0, SHOWN_AT_FIRST);
  const data = list.data ?? totals;

  return (
    <Card className="border border-[#e9e6f4]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center justify-between gap-3 px-5 py-3.5 text-left"
      >
        <span>
          <span className="block text-sm font-extrabold text-ink-900">Employers we search</span>
          <span className="block text-xs text-ink-500">
            {totals
              ? `${num(totals.total_employers)} ${plural(totals.total_employers, "employer", "employers")}, ${num(totals.total_postings)} open ${plural(totals.total_postings, "posting", "postings")}`
              : "Loading..."}
            {totals?.refreshing ? ` (updating ${totals.refresh_done} of ${totals.refresh_total})` : ""}
          </span>
        </span>
        <span className="text-[13px] font-bold text-brand-600">{open ? "Hide" : "Show"}</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-[#ebe8f6] px-5 py-4">
          <p className="text-xs text-ink-500">
            Job Search reads these employers' public job lists, the same ones on their careers pages, and keeps a copy on this computer. The copy updates in the
            background. Employers join the list from jobs you save, links you add here, and searches.
          </p>

          <form
            className="flex flex-wrap items-center gap-2.5"
            onSubmit={(e) => {
              e.preventDefault();
              if (link.trim().length >= 8 && !add.isPending) add.mutate();
            }}
          >
            <label htmlFor="js-employer-link" className="sr-only">
              Link to a job or job list
            </label>
            <input
              id="js-employer-link"
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="Paste a job link to add its employer"
              maxLength={1000}
              className="min-w-[240px] flex-1 rounded-full border border-[#8f88bb] bg-white px-4 py-2.5 text-[13px] text-ink-900 placeholder:text-[#6a6585] focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200"
            />
            <Button type="submit" variant="secondary" size="sm" disabled={link.trim().length < 8 || add.isPending}>
              {add.isPending ? "Reading..." : "Add employer"}
            </Button>
          </form>
          {add.isError && (
            <p className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700" role="alert">
              {errorText(add.error)}
            </p>
          )}
          {add.isSuccess && add.data && (
            <p className="rounded-xl bg-[#e8f6ee] px-3.5 py-2.5 text-[13px] font-bold text-[#17603f]" role="status">
              Added {add.data.name}: {num(add.data.open_jobs)} open {plural(add.data.open_jobs, "job", "jobs")}.
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <label htmlFor="js-employer-filter" className="sr-only">
              Find an employer
            </label>
            <input
              id="js-employer-filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Find an employer"
              className="w-56 rounded-full border border-[#cfc8ee] bg-white px-4 py-2 text-[13px] text-ink-900 placeholder:text-[#6a6585] focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200"
            />
            <Button variant="secondary" size="sm" onClick={() => updateNow.mutate()} disabled={updateNow.isPending || !!data?.refreshing}>
              {data?.refreshing ? `Updating ${data.refresh_done} of ${data.refresh_total}` : "Update now"}
            </Button>
          </div>
          {data && data.disabled_systems.length > 0 && (
            <p className="text-xs text-ink-500">
              Switched off in settings: {data.disabled_systems.map((s) => SYSTEM_NAMES[s] ?? s).join(", ")}.
            </p>
          )}

          {list.isLoading ? (
            <p className="text-sm text-ink-500">Loading...</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-ink-500">
              {filter ? "No employer matches that name." : "No employers yet. Save a job or paste a job link above, and its employer joins the list."}
            </p>
          ) : (
            <ul className="divide-y divide-[#f0edf9]">
              {visible.map((e) => {
                const line = statusLine(e);
                return (
                  <li key={e.id} className="flex items-center gap-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className={`truncate text-sm font-bold ${e.enabled ? "text-ink-900" : "text-ink-400"}`}>{e.name}</p>
                      <p className={`text-xs ${line.bad ? "text-red-700" : "text-ink-500"}`}>{line.text}</p>
                    </div>
                    <span className="w-24 shrink-0 text-right text-[13px] tabular-nums text-ink-700">
                      {e.status === "new" ? "" : `${num(e.open_jobs)} ${plural(e.open_jobs, "job", "jobs")}`}
                    </span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={e.enabled}
                      aria-label={`Search ${e.name}`}
                      disabled={toggle.isPending}
                      onClick={() => toggle.mutate(e)}
                      className={`relative h-[22px] w-[38px] shrink-0 rounded-full transition ${e.enabled ? "bg-brand-500" : "bg-[#cfc8ee]"}`}
                    >
                      <span
                        className={`absolute top-[3px] h-4 w-4 rounded-full bg-white shadow transition-all ${e.enabled ? "left-[19px]" : "left-[3px]"}`}
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {!filter && !showAll && rows.length > SHOWN_AT_FIRST && (
            <button type="button" onClick={() => setShowAll(true)} className="text-[13px] font-bold text-brand-600 hover:underline">
              Show all {num(rows.length)}
              {totals && totals.total_employers > rows.length ? ` (the busiest ${num(rows.length)} of ${num(totals.total_employers)}; use Find to reach the rest)` : ""}
            </button>
          )}
        </div>
      )}
    </Card>
  );
}
