import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { api, ApiError, documentDownloadUrl } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, CheckIcon, Ring, inputClass } from "@/components/ui";
import { scoreColor, scoreLabel } from "@/components/match";
import { completeApplication } from "@/lib/extensionBridge";
import { formatLocation, formatPosted, formatSalary } from "@/lib/jobText";
import type { GeneratedDocumentOut, JobOut, TailorResumeOut } from "@/types/api";

/**
 * Jobs you found yourself and added by link (or with Save this job in the
 * browser extension). Nothing runs automatically: scoring, proceeding and
 * tailoring each happen only when you click.
 */
type Stage = "all" | "going" | "ready" | "progress" | "applied";
type SortBy = "newest" | "fit";

const STAGES: { value: Stage; label: string }[] = [
  { value: "all", label: "All" },
  { value: "going", label: "Going after" },
  { value: "ready", label: "Ready to apply" },
  { value: "progress", label: "Application in progress" },
  { value: "applied", label: "Completed" },
];

function hasResumeDoc(job: JobOut): boolean {
  return job.documents.some((d) => d.document_type === "resume");
}

/** Each job sits in exactly one stage (the furthest it has reached), so the tab counts add up. */
function inStage(job: JobOut, stage: Stage): boolean {
  if (stage === "all") return true;
  const going = job.application_status === "proceeding";
  const applied = !!job.applied_at;
  const started = !!job.application_started_at;
  const resume = hasResumeDoc(job);
  if (stage === "applied") return applied;
  if (applied) return false;
  if (stage === "progress") return started;
  if (started) return false;
  if (stage === "ready") return going && resume;
  if (stage === "going") return going && !resume;
  return false;
}

export function Jobs() {
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const [params] = useSearchParams();
  const wanted = params.get("stage");
  const [stage, setStage] = useState<Stage>(() => (STAGES.some((s) => s.value === wanted) ? (wanted as Stage) : "all"));
  const [sortBy, setSortBy] = useState<SortBy>("newest");
  const [query, setQuery] = useState("");
  const all = jobsQuery.data ?? [];
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const searched = terms.length
    ? all.filter((j) => {
        const hay = `${j.title} ${j.company}`.toLowerCase();
        return terms.every((t) => hay.includes(t));
      })
    : all;
  const visible = searched
    .filter((j) => inStage(j, stage))
    .sort((a, b) =>
      sortBy === "fit" ? (b.evaluation?.overall_score ?? -1) - (a.evaluation?.overall_score ?? -1) : 0,
    );

  return (
    <div>
      <PageHeader
        title="Jobs"
        description="Save jobs you find, see how well they fit, and tailor your resume for the ones you want."
      />

      <Card className="mb-6 overflow-hidden">
        <AddJobByUrl />

        {all.length > 1 && (
          <>
            <nav aria-label="Job stages" className="flex gap-5 overflow-x-auto border-t border-ink-900/5 px-5">
              {STAGES.map((st) => {
                const on = stage === st.value;
                return (
                  <button
                    key={st.value}
                    type="button"
                    onClick={() => setStage(st.value)}
                    aria-pressed={on}
                    className={`-mb-px whitespace-nowrap border-b-[3px] pb-3 pt-3.5 text-[13px] font-bold transition ${
                      on ? "border-brand-500 text-brand-600" : "border-transparent text-ink-400 hover:text-brand-700"
                    }`}
                  >
                    {st.label}
                    <span
                      className={`ml-2 rounded-full px-2 py-0.5 text-[11px] ${
                        on ? "bg-brand-100 text-brand-600" : "bg-ink-900/5 text-ink-500"
                      }`}
                    >
                      {searched.filter((j) => inStage(j, st.value)).length}
                    </span>
                  </button>
                );
              })}
            </nav>

            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2.5 border-t border-ink-900/5 bg-[#faf9fe] px-4 py-3 sm:pl-5">
              <div className="relative min-w-[200px] flex-1">
                <label htmlFor="job-search-box" className="sr-only">
                  Search jobs by role or company
                </label>
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400"
                  aria-hidden="true"
                >
                  <circle cx="11" cy="11" r="6.5" />
                  <path d="M16 16l4 4" />
                </svg>
                <input
                  id="job-search-box"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search role or company"
                  className="w-full rounded-full border border-[#ddd8f3] bg-white py-2.5 pl-10 pr-4 text-[13px] text-ink-900 placeholder:text-ink-400 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200"
                />
              </div>
              <label className="ml-auto flex items-center gap-2 text-xs font-bold text-ink-400">
                Sort
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value === "fit" ? "fit" : "newest")}
                  className="rounded-full border border-[#ddd8f3] bg-white px-3.5 py-2.5 text-[13px] font-bold text-brand-700"
                >
                  <option value="newest">Newest first</option>
                  <option value="fit">Best fit first</option>
                </select>
              </label>
            </div>
          </>
        )}
      </Card>

      {jobsQuery.isLoading && <p className="text-sm text-ink-400">Loading…</p>}
      {jobsQuery.isError && (
        <p className="text-sm text-red-600">Couldn't load your jobs. Make sure the backend is running, then refresh.</p>
      )}

      {jobsQuery.data && jobsQuery.data.length === 0 && (
        <Card className="p-10 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-500">
            <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7" aria-hidden="true">
              <rect x="3" y="7" width="18" height="13" rx="3" stroke="currentColor" strokeWidth="1.8" />
              <path d="M9 7V5.5A1.5 1.5 0 0110.5 4h3A1.5 1.5 0 0115 5.5V7" stroke="currentColor" strokeWidth="1.8" />
            </svg>
          </div>
          <h2 className="text-base font-bold text-ink-900">No jobs yet</h2>
          <p className="mt-1 text-sm text-ink-500">Paste a link above to add your first one.</p>
        </Card>
      )}

      {all.length > 0 && visible.length === 0 && (
        <p className="text-sm text-ink-400">
          {terms.length ? `No jobs match "${query.trim()}" in this view.` : "No jobs in this view. Pick another filter above."}
        </p>
      )}

      {visible.length > 0 && (
        <ul className="space-y-4">
          {visible.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </ul>
      )}
    </div>
  );
}

function Progress({ job }: { job: JobOut }) {
  const steps = [
    { label: "Added", done: true },
    { label: "Scored", done: !!job.evaluation },
    { label: "Going after", done: job.application_status === "proceeding" },
    { label: "Resume ready", done: job.documents.some((d) => d.document_type === "resume") },
    { label: "Application started", done: !!job.application_started_at || !!job.applied_at },
    { label: "Applied", done: !!job.applied_at },
  ];
  return (
    <ol className="flex items-center" aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s.label} className="flex items-center">
          <span className="flex items-center gap-1.5">
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full ${
                s.done ? "bg-emerald-500 text-white" : "bg-ink-900/5 text-transparent"
              }`}
            >
              <CheckIcon className="h-3 w-3" />
            </span>
            <span className={`text-xs font-semibold ${s.done ? "text-ink-700" : "text-ink-400"}`}>{s.label}</span>
          </span>
          {i < steps.length - 1 && (
            <span className={`mx-2 h-0.5 w-5 rounded-full sm:w-8 ${steps[i + 1].done ? "bg-emerald-300" : "bg-ink-900/10"}`} />
          )}
        </li>
      ))}
    </ol>
  );
}

function MoreMenu({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-label="More actions"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 w-8 items-center justify-center rounded-full text-ink-500 transition hover:bg-brand-50 hover:text-brand-700"
      >
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="currentColor" aria-hidden="true">
          <circle cx="4" cy="10" r="1.6" />
          <circle cx="10" cy="10" r="1.6" />
          <circle cx="16" cy="10" r="1.6" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute right-0 z-10 mt-1 w-52 animate-rise rounded-2xl bg-white p-1.5 shadow-lift"
          onClick={() => setOpen(false)}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function MenuItem({
  children,
  onClick,
  href,
  danger = false,
  disabled = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  href?: string;
  danger?: boolean;
  disabled?: boolean;
}) {
  const cls = `block w-full rounded-xl px-3 py-2 text-left text-sm font-medium transition disabled:opacity-50 ${
    danger ? "text-red-600 hover:bg-red-50" : "text-ink-700 hover:bg-brand-50 hover:text-brand-700"
  }`;
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={cls}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={cls}>
      {children}
    </button>
  );
}

function JobCard({ job }: { job: JobOut }) {
  const queryClient = useQueryClient();
  const evaluation = job.evaluation;
  const proceeding = job.application_status === "proceeding";
  const resumeDocs = job.documents.filter((d) => d.document_type === "resume");
  const changelogDocs = job.documents.filter((d) => d.document_type === "changelog");
  const hasResume = resumeDocs.length > 0;
  const usingOriginal = resumeDocs.some((d) => d.template_version === "original-1");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [applyState, setApplyState] = useState<{ kind: "idle" | "starting" | "opened" | "problem"; text?: string }>({
    kind: "idle",
  });

  const startApplication = async () => {
    setApplyState({ kind: "starting" });
    const reply = await completeApplication(job.id, job.canonical_application_url);
    if (reply === null) {
      setApplyState({
        kind: "problem",
        text: "The browser extension didn't answer. Reload it on the extensions page, then refresh this page.",
      });
    } else if (!reply.ok) {
      setApplyState({ kind: "problem", text: reply.error ?? "Couldn't start the application." });
    } else {
      setApplyState({ kind: "opened" });
    }
  };

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["jobs"] });

  const proceedMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.proceedWithApplication(job.id),
    onSuccess: refresh,
  });
  const requalifyMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.requalifyJob(job.id),
    onSuccess: refresh,
  });
  const undoMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.undoProceed(job.id),
    onSuccess: refresh,
  });
  const [markingApplied, setMarkingApplied] = useState(false);
  const [appliedOn, setAppliedOn] = useState(() => new Date().toLocaleDateString("en-CA"));
  const today = new Date().toLocaleDateString("en-CA");
  const appliedMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.markApplied(job.id, appliedOn || undefined),
    onSuccess: () => {
      setMarkingApplied(false);
      return refresh();
    },
  });
  const notAppliedMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.markNotApplied(job.id),
    onSuccess: refresh,
  });
  const deleteMutation = useMutation<void, ApiError, void>({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: refresh,
  });
  const originalMutation = useMutation<GeneratedDocumentOut[], ApiError, void>({
    mutationFn: () => api.useOriginalResume(job.id),
    onSuccess: refresh,
  });
  const tailorMutation = useMutation<TailorResumeOut, ApiError, void>({
    mutationFn: () => api.tailorResume(job.id),
    onSuccess: refresh,
  });

  const error =
    proceedMutation.error ?? requalifyMutation.error ?? tailorMutation.error ?? originalMutation.error ?? undoMutation.error ?? appliedMutation.error ?? notAppliedMutation.error ?? deleteMutation.error;

  const detailsButton = (
    <button
      type="button"
      onClick={() => setExpanded((v) => !v)}
      aria-expanded={expanded}
      className="text-[13px] font-bold text-brand-600 hover:text-brand-700 hover:underline"
    >
      {expanded ? "Hide details" : "Show details"}
    </button>
  );

  const menu = (
    <MoreMenu>
      <MenuItem href={job.canonical_application_url}>Open job posting</MenuItem>
      {(evaluation || proceeding) && (
        <MenuItem onClick={() => requalifyMutation.mutate()} disabled={requalifyMutation.isPending}>
          {evaluation ? "Re-score match" : "Score match"}
        </MenuItem>
      )}
      {proceeding && (
        <MenuItem onClick={() => undoMutation.mutate()} disabled={undoMutation.isPending}>
          Undo proceeding
        </MenuItem>
      )}
      {job.applied_at && (
        <MenuItem onClick={() => notAppliedMutation.mutate()} disabled={notAppliedMutation.isPending}>
          Not applied after all
        </MenuItem>
      )}
      <MenuItem danger onClick={() => setConfirmingDelete(true)}>
        Delete job
      </MenuItem>
    </MoreMenu>
  );

  const showDetails = !!evaluation || (proceeding && hasResume);
  const busyResume = tailorMutation.isPending || originalMutation.isPending;
  const linkClass = "text-[13px] font-bold text-brand-600 hover:text-brand-700 hover:underline disabled:opacity-50";
  const gaps = evaluation?.gaps ?? [];
  const showResumePanel = proceeding && hasResume;
  const wordDoc = resumeDocs.find((d) => d.format === "docx");

  return (
    <li>
      <Card className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-bold leading-snug text-ink-900">{job.title}</h2>
            <div className="mt-0.5 text-sm font-semibold text-ink-500">{job.company}</div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-400">
              <span>{formatLocation(job.location) || "Location not listed"}</span>
              {job.remote_type && <span className="capitalize">{job.remote_type}</span>}
              {formatPosted(job.posted_at) && <span>Posted {formatPosted(job.posted_at)}</span>}
              {formatSalary(job.salary) && <span>{formatSalary(job.salary)}</span>}
              <span>Added {new Date(job.first_seen).toLocaleDateString()}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {evaluation ? (
              <div className="flex items-center gap-3">
                <div className="hidden text-right sm:block">
                  <div className="text-sm font-bold" style={{ color: scoreColor(evaluation.overall_score) }}>
                    {scoreLabel(evaluation.overall_score)}
                  </div>
                  <div className="text-xs text-ink-400">match with your resume</div>
                </div>
                <Ring value={evaluation.overall_score} size={58} stroke={6} color={scoreColor(evaluation.overall_score)}>
                  <span className="text-sm font-bold text-ink-900">{Math.round(evaluation.overall_score * 100)}</span>
                </Ring>
              </div>
            ) : (
              <Button size="sm" variant="primary" onClick={() => requalifyMutation.mutate()} disabled={requalifyMutation.isPending}>
                {requalifyMutation.isPending ? "Scoring…" : "Score"}
              </Button>
            )}
          </div>
        </div>

        <div className="mt-3 border-t border-ink-900/5 pt-3">
          <Progress job={job} />
        </div>

        {job.applied_at && (
          <p className="mt-3 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            Applied {new Date(job.applied_at).toLocaleDateString()}
            {job.applied_via === "extension"
              ? ". The extension saw the confirmation page. Use the menu if that's wrong."
              : "."}
          </p>
        )}

        {markingApplied && !job.applied_at && (
          <div className="mt-3 flex flex-wrap items-end gap-3 rounded-2xl bg-brand-50/60 p-4">
            <label className="text-xs font-semibold text-ink-600">
              Day you applied
              <input
                type="date"
                value={appliedOn}
                max={today}
                onChange={(e) => setAppliedOn(e.target.value)}
                className={`${inputClass} mt-1 block`}
              />
            </label>
            <Button variant="primary" onClick={() => appliedMutation.mutate()} disabled={appliedMutation.isPending}>
              {appliedMutation.isPending ? "Saving…" : "Save"}
            </Button>
            <Button variant="secondary" onClick={() => setMarkingApplied(false)}>
              Cancel
            </Button>
          </div>
        )}

        <div className="mt-3.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {!job.applied_at && !proceeding && (
              <Button
                variant={evaluation ? "primary" : "secondary"}
                onClick={() => proceedMutation.mutate()}
                disabled={proceedMutation.isPending}
              >
                {proceedMutation.isPending ? "Starting…" : "Go after it"}
              </Button>
            )}
            {!job.applied_at && proceeding && !hasResume && (
              <>
                <Button variant="primary" onClick={() => tailorMutation.mutate()} disabled={busyResume}>
                  {tailorMutation.isPending ? "Creating…" : "Tailor my resume first"}
                </Button>
                <button type="button" className={linkClass} onClick={() => originalMutation.mutate()} disabled={busyResume}>
                  {originalMutation.isPending ? "Saving…" : "Use my original resume"}
                </button>
              </>
            )}
            {!job.applied_at && proceeding && hasResume && (
              <Button variant="primary" onClick={startApplication} disabled={applyState.kind === "starting"}>
                {applyState.kind === "starting" ? "Opening…" : "Complete application"}
              </Button>
            )}
            {!job.applied_at && !markingApplied && (
              <button type="button" className={linkClass} onClick={() => setMarkingApplied(true)}>
                I already applied
              </button>
            )}
          </div>
          <div className="ml-auto flex items-center gap-3">
            {showDetails && detailsButton}
            {menu}
          </div>
        </div>

        {proceeding && !hasResume && !job.applied_at && (
          <p className="mt-2 text-xs text-ink-500">
            Either way, the application is filled from the resume you pick here, including each role's bullets.
          </p>
        )}
        {applyState.kind === "opened" && (
          <p className="mt-2 text-xs text-ink-600">
            Opened in a new tab and filling now. You will get a notification when it is done. Anything it couldn't
            answer is highlighted there and listed under Needs Attention. Review it, then submit it yourself.
          </p>
        )}
        {applyState.kind === "problem" && (
          <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {applyState.text}{" "}
            <a className="font-semibold underline" href={job.canonical_application_url} target="_blank" rel="noreferrer">
              Open the posting
            </a>
          </p>
        )}
        {requalifyMutation.isPending && evaluation && (
          <p className="mt-2 animate-pulse text-xs text-ink-400">Comparing your resume with this job…</p>
        )}
        {tailorMutation.isPending && (
          <p className="mt-2 animate-pulse text-xs text-ink-500">Tailoring your resume. This can take a minute.</p>
        )}

        {expanded && (evaluation || showResumePanel) && (
          <div className="mt-4 border-t border-ink-900/5 pt-4">
            <div className={`grid gap-6 ${evaluation && showResumePanel ? "md:grid-cols-[1.3fr_1fr]" : ""}`}>
              {evaluation && (
                <div className="min-w-0">
                  <h3 className="text-xs font-extrabold text-ink-900">Why it fits</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-700">{evaluation.summary}</p>
                  {gaps.length > 0 && (
                    <>
                      <h3 className="mt-4 text-xs font-extrabold text-ink-900">Gaps</h3>
                      <ul className="mt-1.5 space-y-1.5">
                        {gaps.map((gap) => (
                          <li key={gap} className="flex gap-2 text-xs leading-relaxed text-ink-500">
                            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                            {gap}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}

              {showResumePanel && (
                <div className="self-start overflow-hidden rounded-[18px] border border-[#e7e1fa] bg-[#f6f3ff]">
                  <div className="flex items-center gap-3 px-4 pb-3 pt-3.5">
                    <div
                      className="flex h-12 w-10 shrink-0 flex-col justify-center gap-1 rounded-lg bg-white px-2 shadow-soft"
                      aria-hidden="true"
                    >
                      <i className="h-[3px] w-3/5 rounded bg-brand-500" />
                      <i className="h-[3px] rounded bg-[#d9d2f4]" />
                      <i className="h-[3px] rounded bg-[#d9d2f4]" />
                      <i className="h-[3px] w-4/5 rounded bg-[#d9d2f4]" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-extrabold text-ink-900">
                        {usingOriginal ? "Your original resume" : "Your tailored resume"}
                      </div>
                      <div className="mt-0.5 text-xs text-ink-500">Read it over before you send it.</div>
                    </div>
                  </div>
                  <div className="flex gap-2 px-4 pb-3.5">
                    {resumeDocs.map((d) => {
                      const primary = wordDoc ? d.id === wordDoc.id : d.id === resumeDocs[0].id;
                      return (
                        <a
                          key={d.id}
                          href={documentDownloadUrl(d.id)}
                          className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-[13px] font-bold transition ${
                            primary
                              ? "bg-gradient-to-b from-brand-400 to-brand-500 text-white shadow-glow hover:from-brand-500 hover:to-brand-600"
                              : "border border-[#ddd8f3] bg-white text-brand-700 hover:bg-brand-50"
                          }`}
                        >
                          <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.4"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            className="h-3.5 w-3.5"
                            aria-hidden="true"
                          >
                            <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
                          </svg>
                          {d.format === "docx" ? "Word" : d.format.toUpperCase()}
                        </a>
                      );
                    })}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-[#e7e1fa] bg-white px-4 py-2.5">
                    {!usingOriginal &&
                      changelogDocs.map((d) => (
                        <a key={d.id} href={documentDownloadUrl(d.id)} className="text-xs font-bold text-brand-600 hover:underline">
                          What changed
                        </a>
                      ))}
                    <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1.5">
                      <button
                        type="button"
                        className="text-xs font-bold text-ink-500 hover:text-brand-700 disabled:opacity-50"
                        onClick={() => tailorMutation.mutate()}
                        disabled={busyResume}
                      >
                        {tailorMutation.isPending ? "Creating…" : usingOriginal ? "Tailor it instead" : "Recreate"}
                      </button>
                      {!usingOriginal && (
                        <button
                          type="button"
                          className="text-xs font-bold text-ink-500 hover:text-brand-700 disabled:opacity-50"
                          onClick={() => originalMutation.mutate()}
                          disabled={busyResume}
                        >
                          {originalMutation.isPending ? "Saving…" : "Use original instead"}
                        </button>
                      )}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {showResumePanel && tailorMutation.data?.used_original_wording && (
              <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
                The AI's rewording didn't pass the accuracy checks, so this resume uses your original wording.
              </p>
            )}
            {showResumePanel && tailorMutation.data && tailorMutation.data.changelog.length > 0 && (
              <details className="mt-3 text-xs text-ink-500">
                <summary className="cursor-pointer select-none font-semibold text-ink-700 hover:text-brand-700">
                  Changes and gaps ({tailorMutation.data.changelog.length})
                </summary>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {tailorMutation.data.changelog.map((note, i) => (
                    <li key={i}>{note}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {confirmingDelete && (
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-800">
            Delete this job and its files?
            <span className="flex gap-2">
              <Button size="sm" variant="danger" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
                {deleteMutation.isPending ? "Deleting…" : "Yes, delete"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmingDelete(false)}>
                Cancel
              </Button>
            </span>
          </div>
        )}

        {error && <p className="mt-3 text-sm text-red-600">{error.message}</p>}
      </Card>
    </li>
  );
}

/** Collapsed by default. The summary above answers "why this score"; this is the detail. */
function AddJobByUrl() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [lastAdded, setLastAdded] = useState<JobOut | null>(null);

  const addMutation = useMutation<JobOut, ApiError, string>({
    mutationFn: (jobUrl) => api.addJobByUrl({ url: jobUrl }),
    onSuccess: (job) => {
      setLastAdded(job);
      setUrl("");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="bg-gradient-to-b from-[#f8f6ff] to-white px-5 py-4">
      <form
        className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) addMutation.mutate(url.trim());
        }}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className="hidden h-5 w-5 shrink-0 text-brand-500 sm:block"
          aria-hidden="true"
        >
          <path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1" />
          <path d="M14 10a4 4 0 00-5.7 0l-3 3A4 4 0 0011 18.7l1-1" />
        </svg>
        <input
          type="url"
          required
          aria-label="Job posting link"
          placeholder="Paste a job link to add it"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="min-h-[44px] flex-1 border-0 bg-transparent text-[15px] text-ink-900 placeholder:text-ink-400 focus:outline-none"
        />
        <Button type="submit" variant="primary" className="px-6 py-3" disabled={addMutation.isPending || !url.trim()}>
          {addMutation.isPending ? "Adding…" : "Add job"}
        </Button>
      </form>
      <p className="mt-1 text-xs text-ink-400">
        If a site blocks the link, open the posting and use Save this job in the browser extension instead.
      </p>

      {addMutation.isError && <p className="mt-3 text-sm text-red-600">{addMutation.error.message}</p>}
      {lastAdded && !addMutation.isError && (
        <p className={`mt-3 text-sm font-medium ${lastAdded.already_existed ? "text-amber-700" : "text-emerald-700"}`}>
          {lastAdded.already_existed
            ? `Already in your list: ${lastAdded.title} at ${lastAdded.company}. Nothing new was added.`
            : `Added: ${lastAdded.title} at ${lastAdded.company}`}
        </p>
      )}
    </div>
  );
}
