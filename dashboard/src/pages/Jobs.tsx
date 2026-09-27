import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";

/** Milestone 3: read-only view of what discovery has found so far. */
export function Jobs() {
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  return (
    <div>
      <PageHeader title="Jobs" description="Postings discovery has found from your watched employers." />

      {jobsQuery.isLoading && <p className="text-sm text-slate-400">Loading…</p>}

      {jobsQuery.data && jobsQuery.data.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
          No jobs found yet. Add employers to your watchlist and run discovery from Job Preferences.
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
