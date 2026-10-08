import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { api, ApiError, documentDownloadUrl } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Button, Card, CheckIcon, Ring, inputClass } from "@/components/ui";
import { GapDetails, scoreColor, scoreLabel } from "@/components/match";
import { completeApplication } from "@/lib/extensionBridge";
import { formatLocation, formatPosted, formatSalary } from "@/lib/jobText";
import type { GeneratedDocumentOut, JobOut, TailorResumeOut } from "@/types/api";

/**
 * Jobs you found yourself and added by link (or with Save this job in the
 * browser extension). Nothing runs automatically: scoring, proceeding and
 * tailoring each happen only when you click.
 */
type Stage = "all" | "to-score" | "going" | "ready" | "progress" | "applied";
type SortBy = "newest" | "fit";

const STAGES: { value: Stage; label: string }[] = [
  { value: "all", label: "All" },
  { value: "to-score", label: "Not yet going after" },
  { value: "going", label: "Going after" },
  { value: "ready", label: "Ready to apply" },
  { value: "progress", label: "Application in progress" },
  { value: "applied", label: "Application completed" },
];

function hasResumeDoc(job: JobOut): boolean {
  return job.documents.some((d) => d.document_type === "resume");
}

function inStage(job: JobOut, stage: Stage): boolean {
  const going = job.application_status === "proceeding";
  const applied = !!job.applied_at;
  const started = !!job.application_started_at;
  if (stage === "applied") return applied;
  if (stage === "progress") return started && !applied;
  if (stage === "to-score") return !going && !applied;
  if (stage === "going") return going && !applied;
  if (stage === "ready") return going && hasResumeDoc(job) && !started && !applied;
  return true;
}

export function Jobs() {
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const [params] = useSearchParams();
  const wanted = params.get("stage");
  const [stage, setStage] = useState<Stage>(() => (STAGES.some((s) => s.value === wanted) ? (wanted as Stage) : "all"));
  const [sortBy, setSortBy] = useState<SortBy>("newest");
  const all = jobsQuery.data ?? [];
  const visible = all
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

      <AddJobByUrl />

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

      {all.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {STAGES.map((st) => (
            <button
              key={st.value}
              type="button"
              onClick={() => setStage(st.value)}
              aria-pressed={stage === st.value}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                stage === st.value ? "bg-brand-500 text-white shadow-glow" : "bg-white/80 text-ink-500 hover:text-brand-700"
              }`}
            >
              {st.label}
              <span className="ml-1.5 opacity-70">{all.filter((j) => inStage(j, st.value)).length}</span>
            </button>
          ))}
          <label className="ml-auto flex items-center gap-2 text-xs font-semibold text-ink-500">
            Sort
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value === "fit" ? "fit" : "newest")}
              className="rounded-full border border-[#ddd8f3] bg-white px-3 py-1.5 text-xs font-semibold text-ink-700"
            >
              <option value="newest">Newest first</option>
              <option value="fit">Best fit first</option>
            </select>
          </label>
        </div>
      )}

      {all.length > 0 && visible.length === 0 && (
        <p className="text-sm text-ink-400">No jobs in this view. Pick another filter above.</p>
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
      className="text-xs font-semibold text-brand-600 hover:text-brand-700"
    >
      {expanded ? "Hide details" : "Show details"}
    </button>
  );

  const menu = (
      <MoreMenu>
        <MenuItem href={job.canonical_application_url}>View posting</MenuItem>
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
        {job.applied_at ? (
          <MenuItem onClick={() => notAppliedMutation.mutate()} disabled={notAppliedMutation.isPending}>
            Not applied after all
          </MenuItem>
        ) : (
          <MenuItem onClick={() => setMarkingApplied(true)}>Mark as applied</MenuItem>
        )}
        <MenuItem danger onClick={() => setConfirmingDelete(true)}>
          Delete job
        </MenuItem>
      </MoreMenu>
  );

  const readyCollapsed = proceeding && hasResume && !expanded && !job.applied_at;
  const showDetails = !!evaluation || (proceeding && hasResume);

  const applyBlock = (
    <div>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" onClick={startApplication} disabled={applyState.kind === "starting"}>
                  {applyState.kind === "starting" ? "Opening…" : "Complete application"}
                </Button>
                {!job.applied_at && !markingApplied && (
                  <Button variant="secondary" onClick={() => setMarkingApplied(true)}>
                    Mark as applied
                  </Button>
                )}
                <span className="text-xs text-ink-500">
                  Opens in a new tab and fills it in. You review it and press Submit.
                </span>
              </div>
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
    </div>
  );

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

        {evaluation && expanded && (
          <div className="mt-4">
            <p className="text-sm leading-relaxed text-ink-700">{evaluation.summary}</p>
            {evaluation.gaps.length > 0 && <GapDetails gaps={evaluation.gaps} />}
          </div>
        )}

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

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {readyCollapsed && applyBlock}
          {!job.applied_at && !markingApplied && !(proceeding && hasResume) && (
            <Button variant="secondary" onClick={() => setMarkingApplied(true)}>
              Mark as applied
            </Button>
          )}
          {!proceeding && (
            <Button
              variant={evaluation ? "primary" : "secondary"}
              onClick={() => proceedMutation.mutate()}
              disabled={proceedMutation.isPending}
            >
              {proceedMutation.isPending ? "Starting…" : "Proceed with Application"}
            </Button>
          )}
          {proceeding && !hasResume && (
            <div className="w-full rounded-2xl bg-brand-50/60 p-4">
              <div className="text-sm font-bold text-ink-900">Which resume should this application use?</div>
              <div className="mt-0.5 text-xs text-ink-500">
                Either way, the application is filled from the same resume you pick here, including each role's bullets.
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  onClick={() => tailorMutation.mutate()}
                  disabled={tailorMutation.isPending || originalMutation.isPending}
                >
                  {tailorMutation.isPending ? "Creating…" : "Tailor my resume first"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => originalMutation.mutate()}
                  disabled={tailorMutation.isPending || originalMutation.isPending}
                >
                  {originalMutation.isPending ? "Saving…" : "Use my original resume"}
                </Button>
              </div>
            </div>
          )}
          {requalifyMutation.isPending && evaluation && (
            <span className="animate-pulse text-xs text-ink-400">Comparing your resume with this job…</span>
          )}
          {requalifyMutation.isPending && !evaluation && !proceeding && (
            <span className="animate-pulse text-xs text-ink-400">Comparing your resume with this job…</span>
          )}
          <div className="ml-auto flex items-center gap-3">
            {showDetails && detailsButton}
            {menu}
          </div>
        </div>

        {tailorMutation.isPending && (
          <p className="mt-3 animate-pulse text-xs text-ink-500">Tailoring your resume. This can take a minute.</p>
        )}


        {proceeding && hasResume && expanded && (
          <div className="mt-4 rounded-2xl bg-brand-50/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-bold text-ink-900">
                  {usingOriginal ? "Using your original resume" : "Your tailored resume is ready"}
                </div>
                <div className="mt-0.5 text-xs text-ink-500">
                  {usingOriginal
                    ? "Your saved resume, unchanged. Read it over before you send it."
                    : "Made from your master resume with the same layout. Read it over before you send it."}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {resumeDocs.map((d) => (
                  <a
                    key={d.id}
                    href={documentDownloadUrl(d.id)}
                    className="inline-flex items-center gap-1.5 rounded-full bg-gradient-to-b from-brand-400 to-brand-500 px-4 py-2 text-sm font-semibold text-white shadow-glow transition hover:from-brand-500 hover:to-brand-600"
                  >
                    Download {d.format === "docx" ? "Word file" : d.format.toUpperCase()}
                  </a>
                ))}
                {!usingOriginal && changelogDocs.map((d) => (
                  <a
                    key={d.id}
                    href={documentDownloadUrl(d.id)}
                    className="rounded-full border border-[#ddd8f3] bg-white px-4 py-2 text-sm font-semibold text-ink-700 transition hover:border-brand-400 hover:text-brand-700"
                  >
                    What changed
                  </a>
                ))}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => tailorMutation.mutate()}
                  disabled={tailorMutation.isPending || originalMutation.isPending}
                >
                  {tailorMutation.isPending ? "Creating…" : usingOriginal ? "Tailor it instead" : "Recreate"}
                </Button>
                {!usingOriginal && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => originalMutation.mutate()}
                    disabled={tailorMutation.isPending || originalMutation.isPending}
                  >
                    {originalMutation.isPending ? "Saving…" : "Use original instead"}
                  </Button>
                )}
              </div>
            </div>

            <div className="mt-4 border-t border-brand-200/40 pt-4">{applyBlock}</div>

            {tailorMutation.data?.used_original_wording && (
              <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
                The AI's rewording didn't pass the accuracy checks, so this resume uses your original wording.
              </p>
            )}
            {tailorMutation.data && tailorMutation.data.changelog.length > 0 && (
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
    <Card className="mb-6 p-5">
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) addMutation.mutate(url.trim());
        }}
      >
        <input
          type="url"
          required
          aria-label="Job posting link"
          placeholder="Paste a job link"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className={`${inputClass} flex-1 py-2.5`}
        />
        <Button type="submit" variant="primary" disabled={addMutation.isPending || !url.trim()}>
          {addMutation.isPending ? "Adding…" : "Add job"}
        </Button>
      </form>
      <p className="mt-2.5 text-xs text-ink-400">
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
    </Card>
  );
}
