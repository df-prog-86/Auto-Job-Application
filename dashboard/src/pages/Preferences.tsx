import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import type { DiscoveryRunResult, SearchProfile, SearchProfileInput, TargetEmployer } from "@/types/api";

/**
 * Milestone 3 (spec §4.3, §16-18): search profiles drive what discovery
 * matches against; the employer watchlist is this build's resolution to a
 * gap the spec leaves open — Greenhouse/Lever have no global keyword search,
 * so discovery instead polls a list of employers the candidate has chosen
 * to watch. See app/models/discovery.py for the reasoning.
 */
export function Preferences() {
  const queryClient = useQueryClient();

  const searchProfilesQuery = useQuery({ queryKey: ["search-profiles"], queryFn: api.listSearchProfiles });
  const employersQuery = useQuery({ queryKey: ["target-employers"], queryFn: api.listTargetEmployers });

  const [lastRun, setLastRun] = useState<DiscoveryRunResult | null>(null);
  const runDiscoveryMutation = useMutation({
    mutationFn: api.runDiscovery,
    onSuccess: (result) => {
      setLastRun(result);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div>
      <PageHeader
        title="Job Preferences"
        description="Search profiles decide what discovery looks for; the employer watchlist decides where it looks."
      />

      <SearchProfilesSection profiles={searchProfilesQuery.data ?? []} isLoading={searchProfilesQuery.isLoading} />

      <EmployerWatchlistSection employers={employersQuery.data ?? []} isLoading={employersQuery.isLoading} />

      <div className="mt-6 max-w-2xl rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Run discovery</h2>
        <p className="mb-3 text-xs text-slate-500">
          Checks every enabled watched employer for postings that match an enabled search profile above. This
          only reads public job listings — it doesn't apply to anything. Discovery also runs automatically on a
          schedule in the background.
        </p>
        <button
          onClick={() => runDiscoveryMutation.mutate()}
          disabled={runDiscoveryMutation.isPending}
          className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {runDiscoveryMutation.isPending ? "Running…" : "Run discovery now"}
        </button>

        {runDiscoveryMutation.isError && (
          <p className="mt-3 text-sm text-red-600">{(runDiscoveryMutation.error as ApiError).message}</p>
        )}

        {lastRun && (
          <div className="mt-4 rounded-md bg-slate-50 p-4 text-sm">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Employers checked" value={lastRun.employers_checked} />
              <Stat label="Postings fetched" value={lastRun.postings_fetched} />
              <Stat label="Matched" value={lastRun.postings_matched} />
              <Stat label="New jobs" value={lastRun.jobs_created} />
            </div>
            {lastRun.errors.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-amber-700">
                {lastRun.errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-lg font-semibold text-slate-900">{value}</div>
    </div>
  );
}

const EMPTY_PROFILE: SearchProfileInput = {
  name: "",
  titles: [],
  locations: [],
  remote: true,
  hybrid: true,
  onsite: false,
  salary_minimum: null,
  employment_type: null,
  desired_seniority: [],
  excluded_titles: [],
  excluded_employers: [],
  excluded_industries: [],
  required_keywords: [],
  preferred_keywords: [],
  travel_preference: null,
  relocation_willingness: false,
  enabled: true,
};

function SearchProfilesSection({ profiles, isLoading }: { profiles: SearchProfile[]; isLoading: boolean }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<SearchProfileInput>(EMPTY_PROFILE);

  const createMutation = useMutation({
    mutationFn: () => api.createSearchProfile(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["search-profiles"] });
      setForm(EMPTY_PROFILE);
      setShowForm(false);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => api.updateSearchProfile(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["search-profiles"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteSearchProfile(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["search-profiles"] }),
  });

  return (
    <div className="max-w-2xl rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">Search profiles</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          {showForm ? "Cancel" : "+ New profile"}
        </button>
      </div>

      {isLoading && <p className="text-sm text-slate-400">Loading…</p>}
      {!isLoading && profiles.length === 0 && !showForm && (
        <p className="text-sm text-slate-400">
          No search profiles yet. Add one so discovery knows what you're looking for.
        </p>
      )}

      <ul className="divide-y divide-slate-100">
        {profiles.map((p) => (
          <li key={p.id} className="flex items-center justify-between py-3">
            <div>
              <div className="text-sm font-medium text-slate-900">{p.name}</div>
              <div className="text-xs text-slate-500">
                {p.titles.join(", ") || "any title"} · {p.locations.join(", ") || "any location"}
                {p.remote ? " · remote ok" : ""}
                {p.hybrid ? " · hybrid ok" : ""}
                {p.onsite ? " · onsite ok" : ""}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1 text-xs text-slate-500">
                <input
                  type="checkbox"
                  checked={p.enabled}
                  onChange={(e) => toggleMutation.mutate({ id: p.id, enabled: e.target.checked })}
                />
                enabled
              </label>
              <button
                onClick={() => deleteMutation.mutate(p.id)}
                className="text-xs font-medium text-red-600 hover:text-red-700"
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
          className="mt-4 space-y-3 border-t border-slate-100 pt-4"
        >
          <TextField label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
          <ListField
            label="Job titles (comma-separated)"
            value={form.titles}
            onChange={(v) => setForm({ ...form, titles: v })}
          />
          <ListField
            label="Locations (comma-separated, ignored for remote-only matches)"
            value={form.locations}
            onChange={(v) => setForm({ ...form, locations: v })}
          />
          <div className="flex gap-4 text-sm">
            <CheckField label="Remote" checked={form.remote} onChange={(v) => setForm({ ...form, remote: v })} />
            <CheckField label="Hybrid" checked={form.hybrid} onChange={(v) => setForm({ ...form, hybrid: v })} />
            <CheckField label="On-site" checked={form.onsite} onChange={(v) => setForm({ ...form, onsite: v })} />
          </div>
          <ListField
            label="Required keywords (must all appear)"
            value={form.required_keywords}
            onChange={(v) => setForm({ ...form, required_keywords: v })}
          />
          <ListField
            label="Excluded titles"
            value={form.excluded_titles}
            onChange={(v) => setForm({ ...form, excluded_titles: v })}
          />
          <ListField
            label="Excluded employers"
            value={form.excluded_employers}
            onChange={(v) => setForm({ ...form, excluded_employers: v })}
          />

          <button
            type="submit"
            disabled={createMutation.isPending || !form.name}
            className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {createMutation.isPending ? "Saving…" : "Create profile"}
          </button>
          {createMutation.isError && (
            <p className="text-sm text-red-600">{(createMutation.error as ApiError).message}</p>
          )}
        </form>
      )}
    </div>
  );
}

function EmployerWatchlistSection({ employers, isLoading }: { employers: TargetEmployer[]; isLoading: boolean }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [ats, setAts] = useState<"greenhouse" | "lever">("greenhouse");
  const [identifier, setIdentifier] = useState("");

  const addMutation = useMutation({
    mutationFn: () => api.addTargetEmployer({ name, ats, identifier }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["target-employers"] });
      setName("");
      setIdentifier("");
      setShowForm(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteTargetEmployer(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["target-employers"] }),
  });

  return (
    <div className="mt-6 max-w-2xl rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">Employer watchlist</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          {showForm ? "Cancel" : "+ Add employer"}
        </button>
      </div>
      <p className="mb-3 text-xs text-slate-500">
        Greenhouse and Lever don't offer site-wide search, so discovery only checks employers listed here. Find
        an employer's identifier in their careers page URL — e.g. boards.greenhouse.io/<code>acme</code> or
        jobs.lever.co/<code>acme</code>.
      </p>

      {isLoading && <p className="text-sm text-slate-400">Loading…</p>}
      {!isLoading && employers.length === 0 && !showForm && (
        <p className="text-sm text-slate-400">No employers watched yet.</p>
      )}

      <ul className="divide-y divide-slate-100">
        {employers.map((e) => (
          <li key={e.id} className="flex items-center justify-between py-3">
            <div>
              <div className="text-sm font-medium text-slate-900">
                {e.name} <span className="font-normal text-slate-400">({e.ats})</span>
              </div>
              <div className="text-xs text-slate-500">
                {e.identifier}
                {e.last_checked_at &&
                  ` · last checked ${new Date(e.last_checked_at).toLocaleString()} (${e.last_check_status})`}
              </div>
              {e.last_check_status === "error" && e.last_check_error && (
                <div className="text-xs text-red-600">{e.last_check_error}</div>
              )}
            </div>
            <button
              onClick={() => deleteMutation.mutate(e.id)}
              className="text-xs font-medium text-red-600 hover:text-red-700"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addMutation.mutate();
          }}
          className="mt-4 space-y-3 border-t border-slate-100 pt-4"
        >
          <TextField label="Employer name" value={name} onChange={setName} required />
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">ATS</span>
            <select
              value={ats}
              onChange={(e) => setAts(e.target.value as "greenhouse" | "lever")}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5"
            >
              <option value="greenhouse">Greenhouse</option>
              <option value="lever">Lever</option>
            </select>
          </label>
          <TextField
            label="Identifier (board token / company slug)"
            value={identifier}
            onChange={setIdentifier}
            required
          />
          <button
            type="submit"
            disabled={addMutation.isPending || !name || !identifier}
            className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {addMutation.isPending ? "Adding…" : "Add employer"}
          </button>
          {addMutation.isError && <p className="text-sm text-red-600">{(addMutation.error as ApiError).message}</p>}
        </form>
      )}
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input
        type="text"
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-3 py-1.5"
      />
    </label>
  );
}

function ListField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [text, setText] = useState(value.join(", "));
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input
        type="text"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          );
        }}
        className="w-full rounded-md border border-slate-300 px-3 py-1.5"
      />
    </label>
  );
}

function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
