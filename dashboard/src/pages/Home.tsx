import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";

/**
 * Milestone 1: automation status, Start/Pause, and backend connectivity are
 * real (backed by /api/v1/automation/*). Application counts and recent
 * activity are placeholders until Milestones 3-7 populate real data —
 * they're visually present so the layout is right, not because the numbers
 * mean anything yet.
 */
export function Home() {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ["automation-status"],
    queryFn: api.automationStatus,
  });

  const toggle = useMutation({
    mutationFn: () =>
      statusQuery.data?.mode === "PAUSED" ? api.startAutomation() : api.pauseAutomation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["automation-status"] }),
  });

  const isPaused = statusQuery.data?.mode === "PAUSED";

  return (
    <div>
      <PageHeader title="Home" description="Automation status and recent activity." />

      <div className="mb-6 flex items-center gap-4 rounded-lg border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Automation
          </div>
          <div
            className={`text-lg font-semibold ${
              isPaused ? "text-slate-500" : "text-emerald-600"
            }`}
          >
            {statusQuery.isLoading ? "…" : statusQuery.data?.mode ?? "UNKNOWN"}
          </div>
        </div>
        <button
          onClick={() => toggle.mutate()}
          disabled={toggle.isPending || statusQuery.isLoading}
          className="ml-auto rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {isPaused ? "Start" : "Pause"}
        </button>
      </div>

      {statusQuery.isError && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Couldn't reach the backend at 127.0.0.1:8765. Is it running?
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Applications Today" value={0} />
        <StatCard label="Applications This Week" value={0} />
        <StatCard label="Qualified Jobs Waiting" value={0} />
        <StatCard label="Needs Your Attention" value={0} tone="warning" />
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Recent Activity</h2>
        <p className="text-sm text-slate-400">
          Nothing yet — discovery and applications arrive here starting with Milestone 3.
        </p>
      </div>
    </div>
  );
}
