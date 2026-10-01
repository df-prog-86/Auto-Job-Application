import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, documentDownloadUrl } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import type { JobOut, TailorResumeOut } from "@/types/api";

function matchColor(score: number): string {
  if (score >= 0.75) return "text-emerald-600 bg-emerald-50";
  if (score >= 0.5) return "text-amber-600 bg-amber-50";
  return "text-slate-500 bg-slate-100";
}

/**
 * Milestone 3: jobs you found yourself (LinkedIn, Indeed, a company site,
 * wherever) and handed off here by pasting the link, plus anything the
 * watchlist-based discovery found. Paste-a-URL is Option 1 from the
 * manual-intake redesign; the "Save this job" button in the browser
 * extension (Option 2) is more reliable on sites that block a plain fetch.
 */
export function Jobs() {
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  return (
    <div>
      <PageHeader
        title="Jobs"
        description="Paste a link to a job posting you found, or use the 'Save this job' button in the browser extension while you're looking at one. Click 'Score match' on a job to see how well it fits — nothing runs automatically, and nothing proceeds toward an application until you click Proceed with Application."
      />

      <AddJobByUrl />

      {jobsQuery.isLoading && <p className="text-sm text-slate-400">Loading…</p>}

      {jobsQuery.data && jobsQuery.data.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
          No jobs yet. Paste a link above to add the first one.
        </div>
      )}

      {jobsQuery.data && jobsQuery.data.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <ul className="divide-y divide-slate-100">
            {jobsQuery.data.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function JobRow({ job }: { job: JobOut }) {
  const queryClient = useQueryClient();
  const evaluation = job.evaluation;

  const proceedMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.proceedWithApplication(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const requalifyMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.requalifyJob(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const undoMutation = useMutation<JobOut, ApiError, void>({
    mutationFn: () => api.undoProceed(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const deleteMutation = useMutation<void, ApiError, void>({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const tailorMutation = useMutation<TailorResumeOut, ApiError, void>({
    mutationFn: () => api.tailorResume(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return (
    <li className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-slate-900">
          {job.title} <span className="font-normal text-slate-500">· {job.company}</span>
        </div>
        <div className="flex items-center gap-3">
          {evaluation ? (
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${matchColor(evaluation.overall_score)}`}
              title="Qualification match — see gaps below for why"
            >
              {Math.round(evaluation.overall_score * 100)}% match
            </span>
          ) : (
            <span className="text-xs text-slate-400">Not scored</span>
          )}
          <a
            href={job.canonical_application_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            View posting ↗
          </a>
        </div>
      </div>

      <div className="mt-1 text-xs text-slate-500">
        {job.location || "Location unspecified"}
        {job.remote_type ? ` · ${job.remote_type}` : ""} · first seen{" "}
        {new Date(job.first_seen).toLocaleDateString()}
      </div>

      {evaluation && <div className="mt-2 text-xs text-slate-600">{evaluation.summary}</div>}
      {evaluation && evaluation.gaps.length > 0 && <GapDetails gaps={evaluation.gaps} />}

      <div className="mt-3 flex items-center gap-2">
        {job.application_status === "proceeding" ? (
          <span className="text-xs font-medium text-emerald-600">
            Proceeding with application{" "}
            <button
              onClick={() => undoMutation.mutate()}
              disabled={undoMutation.isPending}
              className="ml-1 font-normal text-slate-500 underline hover:text-slate-700 disabled:opacity-50"
            >
              Undo
            </button>
          </span>
        ) : (
          <button
            onClick={() => proceedMutation.mutate()}
            disabled={proceedMutation.isPending}
            className="rounded-md bg-brand-500 px-3 py-1 text-xs font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {proceedMutation.isPending ? "Starting…" : "Proceed with Application"}
          </button>
        )}
        <button
          onClick={() => requalifyMutation.mutate()}
          disabled={requalifyMutation.isPending}
          className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          {requalifyMutation.isPending
            ? evaluation
              ? "Re-scoring…"
              : "Scoring…"
            : evaluation
              ? "Re-score match"
              : "Score match"}
        </button>
        {confirmingDelete ? (
          <span className="ml-auto flex items-center gap-2 text-xs text-slate-600">
            Delete this job and its files?
            <button
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="rounded-md bg-red-600 px-3 py-1 font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {deleteMutation.isPending ? "Deleting…" : "Yes, delete"}
            </button>
            <button onClick={() => setConfirmingDelete(false)} className="text-slate-500 underline">
              Cancel
            </button>
          </span>
        ) : (
          <button
            onClick={() => setConfirmingDelete(true)}
            className="ml-auto text-xs font-medium text-red-600 hover:text-red-700"
          >
            Delete
          </button>
        )}
      </div>

      {job.application_status === "proceeding" && (
        <div className="mt-3 text-xs text-slate-600">
          <button
            onClick={() => tailorMutation.mutate()}
            disabled={tailorMutation.isPending}
            className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            {tailorMutation.isPending
              ? "Creating…"
              : job.documents.length > 0
                ? "Recreate tailored resume"
                : "Create tailored resume"}
          </button>
          {job.documents.length > 0 && (
            <span className="ml-3">
              Download:{" "}
              {job.documents.map((d) => (
                <a
                  key={d.id}
                  href={documentDownloadUrl(d.id)}
                  className="mr-2 font-medium text-brand-600 hover:text-brand-700"
                >
                  {d.document_type === "changelog" ? "Changelog" : d.format.toUpperCase()}
                </a>
              ))}
            </span>
          )}
          {tailorMutation.data && tailorMutation.data.changelog.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer select-none text-slate-500 hover:text-slate-700">
                Changelog and gaps ({tailorMutation.data.changelog.length})
              </summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {tailorMutation.data.changelog.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </details>
          )}
          {tailorMutation.data?.used_original_wording && (
            <p className="mt-1 text-amber-600">
              The AI's rewording didn't pass the accuracy checks, so this resume uses your original
              wording. Read it before using it.
            </p>
          )}
          {job.documents.length > 0 && !tailorMutation.data?.used_original_wording && (
            <p className="mt-1 text-slate-400">Read it over before sending — checks catch invented numbers and skills, not every change in emphasis.</p>
          )}
        </div>
      )}

      {(proceedMutation.isError ||
        requalifyMutation.isError ||
        tailorMutation.isError ||
        undoMutation.isError ||
        deleteMutation.isError) && (
        <p className="mt-2 text-xs text-red-600">
          {(
            proceedMutation.error ??
            requalifyMutation.error ??
            tailorMutation.error ??
            undoMutation.error ??
            deleteMutation.error
          )?.message}
        </p>
      )}
    </li>
  );
}

/** Collapsed by default — the summary line above is the answer to "why
 * this score"; this is the detail for when you want the specifics. */
function GapDetails({ gaps }: { gaps: string[] }) {
  return (
    <details className="mt-1 text-xs text-slate-500">
      <summary className="cursor-pointer select-none text-slate-500 hover:text-slate-700">
        See what's missing ({gaps.length})
      </summary>
      <ul className="mt-1 space-y-0.5 pl-3">
        {gaps.map((gap) => (
          <li key={gap}>{gap}</li>
        ))}
      </ul>
    </details>
  );
}

function AddJobByUrl() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [lastAdded, setLastAdded] = useState<JobOut | null>(null);

  const addMutation = useMutation<JobOut, ApiError, string>({
    mutationFn: (jobUrl) => api.addJobByUrl({ url: jobUrl }),
    onSuccess: (job) => {
      setLastAdded(job);
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="mb-6 max-w-2xl rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Add a job by link</h2>
      <p className="mb-3 text-xs text-slate-500">
        Paste the URL of a posting you found — on LinkedIn, Indeed, a company's careers page,
        anywhere. If the site blocks a direct fetch (LinkedIn and Indeed sometimes do, even for
        one page), use the "Save this job" button in the browser extension instead while you're
        looking at the posting.
      </p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) addMutation.mutate(url.trim());
        }}
      >
        <input
          type="url"
          required
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={addMutation.isPending || !url.trim()}
          className="rounded-md bg-brand-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {addMutation.isPending ? "Adding…" : "Add"}
        </button>
      </form>

      {addMutation.isError && (
        <p className="mt-3 text-sm text-red-600">{addMutation.error.message}</p>
      )}
      {lastAdded && !addMutation.isError && (
        <p className={`mt-3 text-sm ${lastAdded.already_existed ? "text-amber-600" : "text-emerald-600"}`}>
          {lastAdded.already_existed
            ? `Already in your list: ${lastAdded.title} · ${lastAdded.company}. Nothing new was added.`
            : `Added: ${lastAdded.title} · ${lastAdded.company}`}
        </p>
      )}
    </div>
  );
}
