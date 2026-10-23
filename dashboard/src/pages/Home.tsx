import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { OtterTile } from "@/components/OtterTile";
import { scoreColor } from "@/components/match";
import { Badge, Button, Card, CheckIcon, Ring } from "@/components/ui";
import { answerValue, missingItems, profilePercent } from "@/lib/completeness";
import { completeApplication, pingExtension } from "@/lib/extensionBridge";
import {
  byStage,
  dayCounts,
  daysSince,
  followUps,
  hasResume,
  isOverdue,
  perDayNeeded,
  stalledStage,
  weeklyCounts,
  FOLLOW_UP_METER_DAYS,
} from "@/lib/homeData";
import type { FollowUp, StageKey } from "@/lib/homeData";
import { formatPosted, formatSalary } from "@/lib/jobText";
import { loadSavedCriteria, toApiCriteria } from "@/lib/searchCriteria";
import type { JobOut, JobSearchResultOut } from "@/types/api";

const DEFAULT_GOAL = 5;
const HIDE_PROFILE_KEY = "home-hide-profile-banner";
const TOP_SCORE = 0.9;
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface Step {
  key: string;
  title: string;
  hint: string;
  done: boolean;
  to: string;
  cta: string;
}

const STAGES: { key: StageKey; label: string }[] = [
  { key: "scored", label: "Scored" },
  { key: "going", label: "Going after" },
  { key: "ready", label: "Ready to apply" },
  { key: "progress", label: "In progress" },
  { key: "applied", label: "Completed" },
];

const ageText = (days: number) => (days === 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`);

/**
 * Home: how the week is going, where every job stands, the best new matches
 * and the follow-ups that are due. Each fact appears once. New people see the
 * get-started checklist until every step is done.
 */
export function Home() {
  const queryClient = useQueryClient();
  const now = useMemo(() => new Date(), []);

  const statusQuery = useQuery({ queryKey: ["automation-status"], queryFn: api.automationStatus });
  const masterQuery = useQuery({ queryKey: ["master-status"], queryFn: api.masterStatus });
  const profileQuery = useQuery({ queryKey: ["profile"], queryFn: api.getProfile, retry: false });
  const answersQuery = useQuery({ queryKey: ["answers"], queryFn: api.listAnswers, retry: false });
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const resultsQuery = useQuery({ queryKey: ["job-search-results"], queryFn: api.listSearchResults, retry: false });
  const extensionQuery = useQuery({ queryKey: ["extension-ping"], queryFn: pingExtension, staleTime: 60_000 });

  const toggle = useMutation<unknown, ApiError, void>({
    mutationFn: () => (statusQuery.data?.mode === "PAUSED" ? api.startAutomation() : api.pauseAutomation()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["automation-status"] }),
  });

  const jobs = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);
  const hasProfile = !!profileQuery.data;
  const missing = missingItems(profileQuery.data, answersQuery.data);
  const stages = useMemo(() => byStage(jobs), [jobs]);
  const stalled = stalledStage(stages, now);
  const due = useMemo(() => followUps(jobs, now), [jobs, now]);
  const { thisWeek, lastWeek } = weeklyCounts(jobs, now);
  const days = useMemo(() => dayCounts(jobs, now), [jobs, now]);
  const savedGoal = Number(answerValue(answersQuery.data, "weekly_goal"));
  const goal = Number.isFinite(savedGoal) && savedGoal >= 1 ? Math.min(30, Math.round(savedGoal)) : DEFAULT_GOAL;

  const scoredCount = jobs.filter((j) => j.evaluation).length;
  const resumes = jobs.filter(hasResume).length;
  const steps: Step[] = [
    {
      key: "resume",
      title: "Upload your master resume",
      hint: "Add your resume once. Every tailored version starts from it.",
      done: !!masterQuery.data?.saved && hasProfile,
      to: "/profile",
      cta: "Upload",
    },
    {
      key: "profile",
      title: "Complete your profile",
      hint:
        hasProfile && missing.length > 0
          ? `${missing.length} ${missing.length === 1 ? "thing needs" : "things need"} your attention.`
          : "Give your details a quick once-over.",
      done: hasProfile && missing.length === 0,
      to: "/profile",
      cta: "Review",
    },
    {
      key: "job",
      title: "Add a job you found",
      hint: "Paste a job link, or save one from the extension.",
      done: jobs.length > 0,
      to: "/jobs",
      cta: "Add a job",
    },
    {
      key: "score",
      title: "See how well it fits",
      hint: "See how well a job fits your resume.",
      done: scoredCount > 0,
      to: "/jobs",
      cta: "Score a job",
    },
    {
      key: "tailor",
      title: "Proceed and tailor your resume",
      hint: "Pick a job and get a resume tailored to it.",
      done: resumes > 0,
      to: "/jobs",
      cta: "Tailor a resume",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const nextIndex = steps.findIndex((s) => !s.done);
  const allDone = doneCount === steps.length;
  const loading = masterQuery.isLoading || profileQuery.isLoading || jobsQuery.isLoading;

  const matches = useMemo(
    () =>
      (resultsQuery.data ?? [])
        .filter((r) => r.status === "new")
        .sort((a, b) => (b.match_score ?? -1) - (a.match_score ?? -1) || b.id - a.id),
    [resultsQuery.data],
  );

  const name = (profileQuery.data?.preferred_name || profileQuery.data?.name || "").trim().split(/\s+/)[0];
  const hour = now.getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  const [openStage, setOpenStage] = useState<StageKey | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-ink-900">
            {greeting}
            {name ? `, ${name}` : ""}
          </h1>
          <p className="mt-1.5 text-sm text-ink-500">
            {now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2 rounded-full bg-white py-1.5 pl-3.5 pr-1.5 text-xs font-semibold text-ink-700 shadow-pill">
            <span
              className={`h-2 w-2 rounded-full ${extensionQuery.data?.ok ? "bg-emerald-500" : "bg-ink-300"}`}
              aria-hidden="true"
            />
            {extensionQuery.isLoading ? (
              "Checking extension"
            ) : extensionQuery.data?.ok ? (
              "Extension connected"
            ) : (
              <Link to="/pairing" className="hover:underline">
                Extension not detected
              </Link>
            )}
            {statusQuery.data && (
              <button
                type="button"
                onClick={() => toggle.mutate()}
                disabled={toggle.isPending}
                className="rounded-full px-3 py-1 text-xs font-bold text-brand-700 transition hover:bg-brand-50 disabled:opacity-50"
              >
                {statusQuery.data.mode === "PAUSED" ? "Start automation" : "Pause automation"}
              </button>
            )}
          </span>
          <Link to="/job-search">
            <Button variant="primary" tabIndex={-1}>
              Find new jobs
            </Button>
          </Link>
        </div>
      </div>

      {statusQuery.isError && (
        <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Can&apos;t reach the app. Make sure it&apos;s running, then refresh.
        </div>
      )}
      {toggle.isError && <p className="text-xs text-red-600">{toggle.error.message}</p>}

      {!allDone && !loading && <SetupChecklist steps={steps} doneCount={doneCount} nextIndex={nextIndex} />}

      {allDone && (
        <WeeklyGoal
          thisWeek={thisWeek}
          lastWeek={lastWeek}
          goal={goal}
          days={days}
          onSave={async (n) => {
            await api.saveAnswer("weekly_goal", { value_type: "number", value: n });
            await queryClient.invalidateQueries({ queryKey: ["answers"] });
          }}
        />
      )}

      {allDone && (
        <section aria-label="Pipeline">
          <h2 className="mb-3 text-base font-bold text-ink-900">Pipeline</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5 lg:gap-8">
            {STAGES.map((s, i) => {
              const on = openStage === s.key;
              return (
                <button
                  key={s.key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setOpenStage(on ? null : s.key)}
                  className={`relative rounded-2xl border-2 bg-white px-5 py-4 text-left shadow-soft transition hover:border-brand-200 ${
                    on ? "border-brand-500" : "border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-brand-200" aria-hidden="true" />
                    <span className={`text-xs font-semibold ${on ? "text-brand-600" : "text-ink-500"}`}>{s.label}</span>
                  </div>
                  <div className="mt-1.5 text-4xl font-extrabold tracking-tight text-ink-900">{stages[s.key].length}</div>
                  {stalled === s.key && (
                    <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-bold text-amber-700">
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                      Waiting longest
                    </div>
                  )}
                  {i < STAGES.length - 1 && (
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute -right-[30px] top-1/2 hidden h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full border border-[#ddd8f3] bg-white text-brand-500 shadow-pill lg:flex"
                    >
                      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12h13M13 6l6 6-6 6" />
                      </svg>
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {openStage && (
            <StagePanel stage={openStage} jobs={stages[openStage]} now={now} onClose={() => setOpenStage(null)} />
          )}
        </section>
      )}

      {allDone && (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <MatchesCard matches={matches} loading={resultsQuery.isLoading} />
          <FollowUpCard items={due} />
        </div>
      )}

      {loading && <p className="text-xs text-ink-400">Checking what's saved…</p>}

      {hasProfile && missing.length > 0 && <ProfileBanner profile={profileQuery.data} answers={answersQuery.data} />}
    </div>
  );
}

function SetupChecklist({ steps, doneCount, nextIndex }: { steps: Step[]; doneCount: number; nextIndex: number }) {
  return (
    <Card className="overflow-hidden">
      <div className="bg-gradient-to-br from-brand-50 via-white to-sky-50 p-6 md:p-7">
        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          <Ring value={doneCount / steps.length} size={92} stroke={9} color="#5b57f5">
            <div className="text-xl font-bold text-ink-900">
              {doneCount}/{steps.length}
            </div>
          </Ring>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-ink-900">Get started</h2>
            <p className="mt-1 text-sm font-semibold text-ink-500">
              {doneCount} of {steps.length} done
            </p>
          </div>
        </div>
      </div>
      <ol className="divide-y divide-ink-900/5">
        {steps.map((step, i) => {
          const isNext = i === nextIndex;
          return (
            <li key={step.key} className={`flex items-center gap-4 px-6 py-4 md:px-7 ${isNext ? "bg-brand-50/50" : ""}`}>
              <span
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                  step.done
                    ? "bg-emerald-500 text-white"
                    : isNext
                      ? "bg-brand-500 text-white shadow-glow"
                      : "bg-ink-900/5 text-ink-400"
                }`}
              >
                {step.done ? <CheckIcon className="h-4 w-4 animate-pop" /> : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className={`text-sm font-semibold ${step.done ? "text-ink-400 line-through" : "text-ink-900"}`}>
                  {step.title}
                </div>
                {!step.done && <div className="mt-0.5 text-xs text-ink-500">{step.hint}</div>}
              </div>
              {step.done ? (
                <Badge tone="success">Done</Badge>
              ) : (
                <Link to={step.to}>
                  <Button variant={isNext ? "primary" : "secondary"} size="sm" tabIndex={-1}>
                    {step.cta}
                  </Button>
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function WeeklyGoal({
  thisWeek,
  lastWeek,
  goal,
  days,
  onSave,
}: {
  thisWeek: number;
  lastWeek: number;
  goal: number;
  days: { counts: number[]; today: number };
  onSave: (n: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(goal));
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => setDraft(String(goal)), [goal]);

  const left = Math.max(0, goal - thisWeek);
  const hit = left === 0;
  const per = perDayNeeded(thisWeek, goal, days.today);
  const pace = hit
    ? thisWeek > goal
      ? `Goal reached, ${thisWeek - goal} to spare`
      : "Goal reached"
    : thisWeek === 0
      ? `About ${per} a day gets you there`
      : `${left} to go. ${per <= 1 ? "One a day" : `About ${per} a day`} does it`;
  const bubble = hit
    ? "Goal reached! Time to celebrate, then keep it going."
    : thisWeek === 0
      ? "Fresh week. Let's get the first one in today."
      : thisWeek >= goal / 2
        ? "More than halfway. Keep it going!"
        : "Nice start. You're building momentum.";

  const save = async () => {
    const n = Math.round(Number(draft));
    if (!Number.isFinite(n) || n < 1 || n > 30) return;
    setSaving(true);
    setFailed(false);
    try {
      await onSave(n);
      setEditing(false);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className={`p-6 md:p-7 ${hit ? "bg-gradient-to-br from-white to-emerald-50" : ""}`}>
      <div className="grid items-center gap-x-10 gap-y-5 md:grid-cols-[minmax(230px,300px)_minmax(0,1fr)]">
        <div className="flex flex-col gap-2">
          <h2 className="text-base font-bold text-ink-900">Weekly goal</h2>
          <div className="flex items-baseline gap-2.5">
            <strong className="text-5xl font-extrabold leading-none tracking-tight text-ink-900">{thisWeek}</strong>
            <span className="text-sm font-semibold text-ink-700">of {goal} sent this week</span>
          </div>
          <div>
            <span
              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                hit ? "bg-emerald-50 text-emerald-700" : "bg-brand-50 text-brand-700"
              }`}
            >
              {pace}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-500">
            {lastWeek > 0 && (
              <>
                <span>Last week: {lastWeek} sent</span>
                <span aria-hidden="true">&middot;</span>
              </>
            )}
            {editing ? (
              <span className="flex flex-wrap items-center gap-2">
                <label className="sr-only" htmlFor="goal-input">
                  Applications per week
                </label>
                <input
                  id="goal-input"
                  type="number"
                  min={1}
                  max={30}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="w-20 rounded-xl border border-[#ddd8f3] bg-white px-3 py-1.5 text-sm"
                />
                <Button size="sm" variant="primary" onClick={save} disabled={saving}>
                  {saving ? "Saving…" : "Save"}
                </Button>
                <Button size="sm" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="rounded-lg px-1 py-1 text-xs font-bold text-brand-600 hover:underline"
              >
                Change goal
              </button>
            )}
          </div>
          {failed && <p className="text-xs text-red-600">Couldn't save the goal. Try again.</p>}
        </div>

        <div className="min-w-0">
          <div className="mb-3.5 flex items-center justify-start gap-4 md:justify-end">
            <p
              role="status"
              className="relative m-0 max-w-[260px] rounded-2xl border border-[#ddd8f3] bg-white px-4 py-3 text-[13.5px] font-semibold leading-snug text-ink-900 shadow-pill"
            >
              {bubble}
              <span
                aria-hidden="true"
                className="absolute -right-[8px] top-1/2 h-3.5 w-3.5 -translate-y-1/2 rotate-45 rounded-tr border-r border-t border-[#ddd8f3] bg-white"
              />
            </p>
            <OtterTile size={64} className="shrink-0 drop-shadow-lg" />
          </div>
          <div className="mb-3 flex gap-2" role="img" aria-label={`${thisWeek} of ${goal} applications sent this week`}>
            {Array.from({ length: goal }, (_, i) => (
              <div
                key={i}
                className={`h-3.5 flex-1 rounded-full ${
                  i < thisWeek
                    ? hit
                      ? "bg-emerald-500"
                      : "bg-gradient-to-r from-brand-400 to-brand-500 shadow-glow"
                    : "bg-brand-100"
                }`}
              />
            ))}
          </div>
          <ul className="grid grid-cols-7 gap-1.5" aria-label="Applications sent each day this week">
            {DAY_NAMES.map((d, i) => {
              const c = days.counts[i];
              const isToday = i === days.today;
              return (
                <li
                  key={d}
                  aria-label={`${d}: ${c} sent`}
                  className={`flex flex-col items-center gap-1 text-[11px] font-bold ${isToday ? "text-brand-700" : "text-ink-500"}`}
                >
                  <b
                    className={`grid h-[30px] w-[30px] place-items-center rounded-full text-xs ${
                      c > 0 ? (hit ? "bg-emerald-500 text-white" : "bg-brand-500 text-white") : "bg-brand-50 text-ink-400"
                    } ${isToday ? "ring-2 ring-brand-500 ring-offset-2" : ""}`}
                  >
                    {c > 0 ? c : ""}
                  </b>
                  <span>{d}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function StagePanel({
  stage,
  jobs,
  now,
  onClose,
}: {
  stage: StageKey;
  jobs: JobOut[];
  now: Date;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const label = STAGES.find((s) => s.key === stage)?.label ?? "";
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["jobs"] });
  const [note, setNote] = useState<string | null>(null);

  const proceed = useMutation<JobOut, ApiError, number>({ mutationFn: (id) => api.proceedWithApplication(id), onSuccess: refresh });
  const markApplied = useMutation<JobOut, ApiError, number>({ mutationFn: (id) => api.markApplied(id), onSuccess: refresh });

  const openAndFill = async (job: JobOut) => {
    setNote(null);
    const reply = await completeApplication(job.id, job.canonical_application_url);
    if (reply === null) setNote("The extension isn't answering. Reload it in Chrome, then refresh.");
    else if (!reply.ok) setNote(reply.error ?? "Couldn't start the application.");
    else setNote("Opened in a new tab and filling now. We'll let you know when it's done.");
  };

  const shown = jobs.slice(0, 5);
  const sees = stage === "scored" ? "/jobs" : `/jobs?stage=${stage}`;

  const detail = (j: JobOut): string => {
    const parts = [j.company];
    if (j.evaluation) parts.push(`Score ${Math.round(j.evaluation.overall_score * 100)}`);
    if (stage === "applied") parts.push(`Applied ${ageText(daysSince(j.applied_at, now))}`);
    else if (stage === "progress") parts.push(`Started ${ageText(daysSince(j.application_started_at, now))}`);
    else parts.push(`Added ${ageText(daysSince(j.first_seen, now))}`);
    return parts.join(". ");
  };

  return (
    <div className="relative mt-5 rounded-2xl border-2 border-brand-500 bg-white px-6 pb-2 pt-3">
      <div className="flex items-center justify-between py-2">
        <div className="text-sm font-bold text-ink-900">{label}</div>
        <div className="flex items-center gap-3">
          <Link to={sees} className="text-xs font-bold text-brand-600 hover:underline">
            {jobs.length > shown.length ? `See all ${jobs.length} in Jobs` : "Open in Jobs"}
          </Link>
          <Button size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
      {shown.length === 0 && <p className="py-4 text-sm text-ink-500">Nothing here yet.</p>}
      <ul>
        {shown.map((j) => (
          <li key={j.id} className="flex items-center gap-4 border-t border-ink-900/5 py-3.5 first:border-t-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-bold text-ink-900">{j.title}</div>
              <div className="mt-0.5 text-xs text-ink-500">{detail(j)}</div>
            </div>
            {stage === "scored" && (
              <Button size="sm" onClick={() => proceed.mutate(j.id)} disabled={proceed.isPending}>
                Go after it
              </Button>
            )}
            {stage === "going" && (
              <Link to="/jobs?stage=going">
                <Button size="sm" tabIndex={-1}>
                  Choose resume
                </Button>
              </Link>
            )}
            {stage === "ready" && (
              <Button size="sm" variant="primary" onClick={() => void openAndFill(j)}>
                Open and fill
              </Button>
            )}
            {stage === "progress" && (
              <Button size="sm" onClick={() => markApplied.mutate(j.id)} disabled={markApplied.isPending}>
                Mark as applied
              </Button>
            )}
            {stage === "applied" && (
              <a href={j.canonical_application_url} target="_blank" rel="noreferrer">
                <Button size="sm" tabIndex={-1}>
                  View posting
                </Button>
              </a>
            )}
          </li>
        ))}
      </ul>
      {(note || proceed.isError || markApplied.isError) && (
        <p className="pb-3 text-xs text-ink-700">{note ?? proceed.error?.message ?? markApplied.error?.message}</p>
      )}
    </div>
  );
}

function ScoreDot({ score }: { score: number | null | undefined }) {
  if (score == null) {
    return (
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-ink-900/5 text-center text-[10px] font-semibold leading-tight text-ink-400">
        Not
        <br />
        scored
      </div>
    );
  }
  return (
    <Ring value={score} size={48} stroke={5} color={scoreColor(score)}>
      <span className="text-sm font-bold text-ink-900">{Math.round(score * 100)}</span>
    </Ring>
  );
}

function MatchesCard({ matches, loading }: { matches: JobSearchResultOut[]; loading: boolean }) {
  const queryClient = useQueryClient();
  const saved = useMemo(loadSavedCriteria, []);
  const canRefresh = !!(saved.titles && saved.titles.trim());
  const [notice, setNotice] = useState<string | null>(null);
  const [onlyTop, setOnlyTop] = useState(false);

  const refresh = useMutation<unknown, ApiError, void>({
    mutationFn: async () => {
      const r = await api.runJobSearch(toApiCriteria(saved));
      setNotice(
        r.found > 0
          ? `Found ${r.found} new ${r.found === 1 ? "match" : "matches"}.`
          : "No new matches this time.",
      );
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["job-search-results"] }),
  });
  const add = useMutation<unknown, ApiError, number>({
    mutationFn: (id) => api.addSearchResult(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["job-search-results"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const pool = onlyTop ? matches.filter((r) => (r.match_score ?? 0) >= TOP_SCORE) : matches;
  const top = pool.slice(0, 3);
  const chip = (on: boolean) =>
    `rounded-full border px-3.5 py-1.5 text-[13px] font-semibold shadow-pill transition ${
      on ? "border-brand-500 bg-brand-100 text-brand-700" : "border-[#ddd8f3] bg-white text-ink-700 hover:bg-brand-50"
    }`;
  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h2 className="text-base font-bold text-ink-900">Best new matches</h2>
          {matches.length > 0 && <Badge tone="brand">{matches.length} new</Badge>}
        </div>
        {canRefresh ? (
          <button
            type="button"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            className="rounded-lg px-1 py-1 text-xs font-bold text-brand-600 hover:underline disabled:opacity-50"
          >
            {refresh.isPending ? "Searching…" : "Refresh"}
          </button>
        ) : (
          <Link to="/job-search" className="text-xs font-bold text-brand-600 hover:underline">
            Open Job Search
          </Link>
        )}
      </div>
      {matches.length > 0 && (
        <div className="mt-3 flex gap-2" role="group" aria-label="Filter matches">
          <button type="button" aria-pressed={!onlyTop} onClick={() => setOnlyTop(false)} className={chip(!onlyTop)}>
            All
          </button>
          <button type="button" aria-pressed={onlyTop} onClick={() => setOnlyTop(true)} className={chip(onlyTop)}>
            {Math.round(TOP_SCORE * 100)}%+
          </button>
        </div>
      )}
      {refresh.isPending && <p className="mt-3 animate-pulse text-xs text-ink-500">Searching the web. This can take a minute.</p>}
      {refresh.isError && <p className="mt-3 text-xs text-red-600">{refresh.error.message}</p>}
      {notice && !refresh.isPending && !refresh.isError && <p className="mt-3 text-xs text-ink-700">{notice}</p>}
      {loading && <p className="mt-4 text-sm text-ink-400">Loading…</p>}
      {!loading && matches.length === 0 && (
        <div className="flex flex-col items-center gap-1.5 px-3 py-7 text-center text-sm text-ink-500">
          <b className="text-[15px] text-ink-900">No new matches waiting</b>
          <span>{canRefresh ? "Refresh your saved search to look again." : "Run a search and your matches show up here."}</span>
        </div>
      )}
      {!loading && matches.length > 0 && top.length === 0 && (
        <p className="mt-4 text-sm text-ink-500">None at {Math.round(TOP_SCORE * 100)}% or higher right now.</p>
      )}
      <ul className="mt-2">
        {top.map((r) => {
          const meta = [r.company, r.location, formatSalary(r.salary_text ? { text: r.salary_text } : null) ?? "Pay not listed"];
          const posted = formatPosted(r.posted_at);
          return (
            <li key={r.id} className="flex items-center gap-4 border-t border-ink-900/5 py-3.5 first:border-t-0">
              <ScoreDot score={r.match_score} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold text-ink-900">{r.title}</div>
                <div className="mt-0.5 text-xs text-ink-500">
                  {meta.filter(Boolean).join(" \u00b7 ")}
                  {posted ? ` \u00b7 Posted ${posted}` : ""}
                </div>
              </div>
              <Button size="sm" onClick={() => add.mutate(r.id)} disabled={add.isPending} aria-label={`Add ${r.title} to jobs`}>
                Add
              </Button>
            </li>
          );
        })}
      </ul>
      {pool.length > top.length && (
        <div className="mt-1.5 border-t border-ink-900/5 pt-3">
          <Link to="/job-search" className="text-xs font-bold text-brand-600 hover:underline">
            See all {pool.length} matches
          </Link>
        </div>
      )}
      {add.isError && <p className="mt-2 text-xs text-red-600">{add.error.message}</p>}
    </Card>
  );
}

function FollowUpCard({ items }: { items: FollowUp[] }) {
  const queryClient = useQueryClient();
  const [draftFor, setDraftFor] = useState<number | null>(null);
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const make = useMutation<{ subject: string; body: string }, ApiError, FollowUp>({
    mutationFn: (f) => api.draftFollowUp(f.job.id, f.kind),
    onSuccess: (d) => {
      setDraft(d);
      setCopied(false);
    },
  });
  const done = useMutation<JobOut, ApiError, number>({
    mutationFn: (id) => api.followUpDone(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const start = (f: FollowUp) => {
    setDraftFor(f.job.id);
    setDraft(null);
    make.mutate(f);
  };
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const shown = items.slice(0, 5);
  return (
    <Card className="p-6">
      <div className="flex items-center gap-2.5">
        <h2 className="text-base font-bold text-ink-900">Follow up</h2>
        {items.length > 0 && <Badge>{items.length} waiting</Badge>}
      </div>
      {shown.length === 0 && (
        <div className="flex flex-col items-center gap-1.5 px-3 py-7 text-center text-sm text-ink-500">
          <span className="grid h-11 w-11 place-items-center rounded-full bg-emerald-50 text-emerald-700" aria-hidden="true">
            <CheckIcon className="h-5 w-5" />
          </span>
          <b className="text-[15px] text-ink-900">All caught up</b>
          <span>Nobody to follow up with right now.</span>
        </div>
      )}
      <ul className="mt-3 space-y-2.5">
        {shown.map((f) => {
          const overdue = isOverdue(f.days);
          const fill = Math.min(100, Math.round((f.days / FOLLOW_UP_METER_DAYS) * 100));
          const initial = (f.job.company.trim()[0] ?? "?").toUpperCase();
          return (
            <li key={f.job.id} className="rounded-2xl border border-[#ddd8f3] bg-brand-50/60 px-4 py-3.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-100 text-[15px] font-extrabold text-brand-700"
                  aria-hidden="true"
                >
                  {initial}
                </span>
                <div className="min-w-[8rem] flex-1">
                  <div className="text-sm font-bold text-ink-900">{f.job.company}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-500">
                    <span>Applied {f.days} days ago</span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        overdue ? "bg-red-50 text-red-700" : "bg-ink-900/5 text-ink-500"
                      }`}
                    >
                      {overdue ? "Overdue" : "Due now"}
                    </span>
                  </div>
                </div>
                <Button size="sm" onClick={() => start(f)} disabled={make.isPending && draftFor === f.job.id}>
                  {make.isPending && draftFor === f.job.id ? "Writing…" : "Draft message"}
                </Button>
                <button
                  type="button"
                  onClick={() => done.mutate(f.job.id)}
                  disabled={done.isPending}
                  aria-label={`Mark ${f.job.company} done`}
                  title="Mark done"
                  className="grid h-8 w-8 place-items-center rounded-full border border-[#ddd8f3] bg-white text-ink-500 transition hover:bg-brand-50 hover:text-brand-700 disabled:opacity-50"
                >
                  <CheckIcon className="h-4 w-4" />
                </button>
              </div>
              <div className="relative mt-3 h-1.5 overflow-hidden rounded-full bg-brand-100" aria-hidden="true">
                <div
                  className={`h-full rounded-full ${overdue ? "bg-red-500" : "bg-brand-400"}`}
                  style={{ width: `${fill}%` }}
                />
                <span className="absolute inset-y-0 left-1/2 w-0.5 bg-white" />
              </div>
              {draftFor === f.job.id && make.isError && (
                <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{make.error.message}</p>
              )}
              {draftFor === f.job.id && draft && (
                <div className="mt-3 rounded-2xl bg-white p-4">
                  <div className="text-xs font-bold text-ink-900">{draft.subject}</div>
                  <label className="sr-only" htmlFor={`draft-${f.job.id}`}>
                    Message
                  </label>
                  <textarea
                    id={`draft-${f.job.id}`}
                    value={draft.body}
                    onChange={(e) => {
                      setDraft({ ...draft, body: e.target.value });
                      setCopied(false);
                    }}
                    rows={6}
                    className="mt-2 w-full rounded-xl border border-[#ddd8f3] bg-white px-3 py-2 text-sm leading-relaxed text-ink-900"
                  />
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button size="sm" variant="primary" onClick={() => void copy(`Subject: ${draft.subject}\n\n${draft.body}`)}>
                      {copied ? "Copied" : "Copy message"}
                    </Button>
                    <Button size="sm" onClick={() => make.mutate(f)} disabled={make.isPending}>
                      {make.isPending ? "Writing…" : "Write another"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setDraftFor(null)}>
                      Close
                    </Button>
                  </div>
                  <p className="mt-2 text-xs text-ink-500">You send it yourself. Edit it first if you like.</p>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {items.length > shown.length && <p className="mt-2 text-xs text-ink-500">And {items.length - shown.length} more.</p>}
      {done.isError && <p className="mt-2 text-xs text-red-600">{done.error.message}</p>}
    </Card>
  );
}

function ProfileBanner({
  profile,
  answers,
}: {
  profile: Parameters<typeof profilePercent>[0];
  answers: Parameters<typeof profilePercent>[1];
}) {
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(HIDE_PROFILE_KEY) === "1";
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  const percent = profilePercent(profile, answers);
  const hide = () => {
    setHidden(true);
    try {
      window.localStorage.setItem(HIDE_PROFILE_KEY, "1");
    } catch {
      // hiding is a convenience only
    }
  };
  return (
    <section aria-label="Profile completeness" className="relative flex flex-wrap items-center gap-4 rounded-2xl bg-white px-6 py-4 shadow-soft">
      <Ring value={percent / 100} size={48} stroke={6} color="#5b57f5">
        <span className="text-[11px] font-extrabold text-ink-900">{percent}%</span>
      </Ring>
      <h2 className="min-w-[12rem] flex-1 text-[15px] font-bold text-ink-900">Your profile is almost there</h2>
      <Link to="/profile">
        <Button variant="primary" size="sm" tabIndex={-1}>
          Finish profile
        </Button>
      </Link>
      <button
        type="button"
        onClick={hide}
        aria-label="Hide profile reminder"
        className="grid h-8 w-8 place-items-center rounded-full text-lg text-ink-500 transition hover:bg-brand-50 hover:text-brand-700"
      >
        &times;
      </button>
    </section>
  );
}
