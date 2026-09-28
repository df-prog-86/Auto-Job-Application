import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import type { JobOut } from "@/types/api";

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
        description="Paste a link to a job posting you found, or use the 'Save this job' button in the browser extension while you're looking at one."
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
              <li key={job.id} className="p-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-slate-900">
                    {job.title} <span className="font-normal text-slate-500">· {job.company}</span>
                  </div>
                  <a
                    href={job.canonical_application_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-medium text-brand-600 hover:text-brand-700"
                  >
                    View posting ↗
                  </a>
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {job.location || "Location unspecified"}
                  {job.remote_type ? ` · ${job.remote_type}` : ""} · first seen{" "}
                  {new Date(job.first_seen).toLocaleDateString()}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
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
        <p className="mt-3 text-sm text-emerald-600">
          Added: {lastAdded.title} · {lastAdded.company}
        </p>
      )}
    </div>
  );
}
