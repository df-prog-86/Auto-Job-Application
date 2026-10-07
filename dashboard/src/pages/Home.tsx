import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { scoreColor } from "@/components/match";
import { Badge, Button, Card, CheckIcon, Ring } from "@/components/ui";
import { answerValue, missingItems, profilePercent } from "@/lib/completeness";
import { completeApplication, pingExtension } from "@/lib/extensionBridge";
import {
  byStage,
  daysSince,
  followUps,
  hasResume,
  stalledStage,
  weeklyCounts,
  FOLLOW_UP_AFTER_DAYS,
} from "@/lib/homeData";
import type { FollowUp, StageKey } from "@/lib/homeData";
import { formatPosted, formatSalary } from "@/lib/jobText";
import { loadSavedCriteria, toApiCriteria } from "@/lib/searchCriteria";
import type { JobOut, JobSearchResultOut } from "@/types/api";

const DEFAULT_GOAL = 5;
const HIDE_PROFILE_KEY = "home-hide-profile-banner";

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
  { key: "applied", label: "Applied" },
  { key: "interviewing", label: "Interviewing" },
];

const ageText = (days: number) => (days === 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`);

/**
 * Home: what to do next, how the week is going, where every job stands, and
 * the follow-ups that are due. Each fact appears once. New people see the
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
  const attentionQuery = useQuery({ queryKey: ["needs-attention"], queryFn: api.listNeedsAttention, retry: false });
  const resultsQuery = useQuery({ queryKey: ["job-search-results"], queryFn: api.listSearchResults, retry: false });
  const extensionQuery = useQuery({ queryKey: ["extension-ping"], queryFn: pingExtension, staleTime: 60_000 });

  const toggle = useMutation<unknown, ApiError, void>({
    mutationFn: () => (statusQuery.data?.mode === "PAUSED" ? api.startAutomation() : api.pauseAutomation()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["automation-status"] }),
  });

  const jobs = jobsQuery.data ?? [];
  const hasProfile = !!profileQuery.data;
  const missing = missingItems(profileQuery.data, answersQuery.data);
  const stages = useMemo(() => byStage(jobs), [jobs]);
  const stalled = stalledStage(stages, now);
  const due = useMemo(() => followUps(jobs, now), [jobs, now]);
  const { thisWeek, lastWeek } = weeklyCounts(jobs, now);
  const savedGoal = Number(answerValue(answersQuery.data, "weekly_goal"));
  const goal = Number.isFinite(savedGoal) && savedGoal >= 1 ? Math.min(30, Math.round(savedGoal)) : DEFAULT_GOAL;

  const scoredCount = jobs.filter((j) => j.evaluation).length;
  const resumes = jobs.filter(hasResume).length;
  const steps: Step[] = [
    {
      key: "resume",
      title: "Upload your master resume",
      hint: "A Word file. It is saved once on this computer and every tailored resume starts from it.",
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
          : "Check your details, work eligibility, experience and education.",
      done: hasProfile && missing.length === 0,
      to: "/profile",
      cta: "Review",
    },
    {
      key: "job",
      title: "Add a job you found",
      hint: "Paste a link to any posting, or use Save this job in the browser extension.",
      done: jobs.length > 0,
      to: "/jobs",
      cta: "Add a job",
    },
    {
      key: "score",
      title: "See how well it fits",
      hint: "Score a job to compare it with your resume. It only runs when you ask.",
      done: scoredCount > 0,
      to: "/jobs",
      cta: "Score a job",
    },
    {
      key: "tailor",
      title: "Proceed and tailor your resume",
      hint: "Pick a job to go after and get a Word resume tailored to it.",
      done: resumes > 0,
      to: "/jobs",
      cta: "Tailor a resume",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const nextIndex = steps.findIndex((s) => !s.done);
  const allDone = doneCount === steps.length;
  const loading = masterQuery.isLoading || profileQuery.isLoading || jobsQuery.isLoading;

  const questions = attentionQuery.data ?? [];
  const openQuestions = new Set(questions.map((q) => q.label.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim())).size;
  const blockedJobs = new Set(questions.map((q) => q.job_id)).size;

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

  const readyTop = stages.ready[0];
  const action = nextAction({
    openQuestions,
    blockedJobs,
    readyCount: stages.ready.length,
    readyTop,
    dueCount: due.length,
    matchCount: matches.length,
  });

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
            {now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}. Here is what moves
            your search forward today.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2 rounded-full bg-white px-3.5 py-2 text-xs font-semibold text-ink-700 shadow-soft">
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
          </span>
          {statusQuery.data && (
            <Button size="sm" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
              {statusQuery.data.mode === "PAUSED" ? "Start automation" : "Pause automation"}
            </Button>
          )}
          <Link to="/job-search">
            <Button variant="primary" tabIndex={-1}>
              Find new jobs
            </Button>
          </Link>
        </div>
      </div>

      {statusQuery.isError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Can't reach the app's backend. Make sure it is running, then refresh this page.
        </div>
      )}
      {toggle.isError && <p className="text-xs text-red-600">{toggle.error.message}</p>}

      {!allDone && !loading ? (
        <SetupChecklist steps={steps} doneCount={doneCount} nextIndex={nextIndex} />
      ) : (
        allDone && (
          <section className="flex flex-wrap items-center justify-between gap-5 rounded-3xl bg-brand-700 px-8 py-7 text-white shadow-glow">
            <div className="max-w-xl">
              <span className="inline-block rounded-full bg-white/15 px-3 py-1 text-xs font-bold text-brand-100">
                Do this first
              </span>
              <h2 className="mt-3 text-2xl font-extrabold leading-snug tracking-tight">{action.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-brand-100">{action.body}</p>
            </div>
            <Link
              to={action.to}
              className="rounded-full bg-white px-7 py-3.5 text-base font-extrabold text-brand-700 shadow-soft transition hover:bg-brand-50"
            >
              {action.cta}
            </Link>
          </section>
        )
      )}

      {allDone && (
        <WeeklyGoal
          thisWeek={thisWeek}
          lastWeek={lastWeek}
          goal={goal}
          onSave={async (n) => {
            await api.saveAnswer("weekly_goal", { value_type: "number", value: n });
            await queryClient.invalidateQueries({ queryKey: ["answers"] });
          }}
        />
      )}

      {allDone && (
        <section aria-label="Pipeline">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-base font-extrabold text-ink-900">Pipeline</h2>
            <span className="text-xs text-ink-500">Select a stage to see those jobs</span>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {STAGES.map((s) => {
              const on = openStage === s.key;
              return (
                <button
                  key={s.key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setOpenStage(on ? null : s.key)}
                  className={`relative rounded-2xl border-2 bg-white p-4 text-left shadow-soft transition hover:border-brand-200 ${
                    on ? "border-brand-500" : "border-transparent"
                  }`}
                >
                  <div className={`text-xs font-semibold ${on ? "text-brand-600" : "text-ink-500"}`}>{s.label}</div>
                  <div className="mt-0.5 text-3xl font-extrabold tracking-tight text-ink-900">{stages[s.key].length}</div>
                  {stalled === s.key && (
                    <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-bold text-amber-700">
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                      Waiting longest
                    </div>
                  )}
                </button>
              );
            })}
          </div>
          {openStage && <StagePanel stage={openStage} jobs={stages[openStage]} now={now} onClose={() => setOpenStage(null)} />}
        </section>
      )}

      {allDone && (
        <div className="grid items-stretch gap-6 lg:grid-cols-[3fr_2fr]">
          <MatchesCard matches={matches} loading={resultsQuery.isLoading} />
          <FollowUpCard items={due} />
        </div>
      )}

      {loading && <p className="text-xs text-ink-400">Checking what's saved…</p>}

      {hasProfile && missing.length > 0 && <ProfileBanner profile={profileQuery.data} answers={answersQuery.data} />}
    </div>
  );
}

function nextAction(a: {
  openQuestions: number;
  blockedJobs: number;
  readyCount: number;
  readyTop: JobOut | undefined;
  dueCount: number;
  matchCount: number;
}): { title: string; body: string; cta: string; to: string } {
  if (a.openQuestions > 0) {
    const jobsText = a.blockedJobs === 1 ? "1 application" : `${a.blockedJobs} applications`;
    return {
      title: `Answer ${a.openQuestions} ${a.openQuestions === 1 ? "question" : "questions"} to unblock ${jobsText}`,
      body: "Some applications are paused on questions your profile does not cover yet. Answer once and they are filled in every time after.",
      cta: "Answer now",
      to: "/needs-attention",
    };
  }
  if (a.readyCount > 0 && a.readyTop) {
    return {
      title: `Apply to ${a.readyTop.title} at ${a.readyTop.company}`,
      body: `${a.readyCount} ${a.readyCount === 1 ? "job is" : "jobs are"} ready, each with a resume. This one fits you best.`,
      cta: "See ready jobs",
      to: "/jobs?stage=ready",
    };
  }
  if (a.dueCount > 0) {
    return {
      title: `Follow up with ${a.dueCount} ${a.dueCount === 1 ? "employer" : "employers"}`,
      body: "A short, polite note keeps your application on their radar. A draft is one click away below.",
      cta: "See follow-ups",
      to: "/",
    };
  }
  if (a.matchCount > 0) {
    return {
      title: `Review ${a.matchCount} new ${a.matchCount === 1 ? "match" : "matches"}`,
      body: "Your saved search found jobs that are not in your list yet.",
      cta: "Open Job Search",
      to: "/job-search",
    };
  }
  return {
    title: "Find your next job",
    body: "Nothing is waiting on you. Run a search or paste a link to a posting you like.",
    cta: "Find new jobs",
    to: "/job-search",
  };
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
            <p className="mt-1 text-sm text-ink-500">
              {steps.length - doneCount} {steps.length - doneCount === 1 ? "step" : "steps"} left. Finish them in any
              order.
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
  onSave,
}: {
  thisWeek: number;
  lastWeek: number;
  goal: number;
  onSave: (n: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(goal));
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => setDraft(String(goal)), [goal]);

  const left = Math.max(0, goal - thisWeek);
  const caption =
    thisWeek >= goal
      ? `Goal reached${thisWeek > goal ? `, with ${thisWeek - goal} to spare` : ""}. Nice work.`
      : `${left} more by Sunday and you hit your goal.`;
  const last = lastWeek === 0 ? "" : ` Last week you sent ${lastWeek}.`;

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
    <Card className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <h2 className="text-base font-extrabold text-ink-900">Weekly goal</h2>
          <span className="text-sm text-ink-500">
            <b className="text-xl font-extrabold text-ink-900">{thisWeek}</b> of {goal} applications sent
          </span>
        </div>
        {editing ? (
          <div className="flex items-center gap-2">
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
              className="w-20 rounded-xl border border-ink-300/70 bg-white px-3 py-1.5 text-sm"
            />
            <Button size="sm" variant="primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button size="sm" onClick={() => setEditing(true)}>
            Change goal
          </Button>
        )}
      </div>
      <div className="mt-4 flex gap-2" role="img" aria-label={`${thisWeek} of ${goal} applications sent this week`}>
        {Array.from({ length: goal }, (_, i) => (
          <div key={i} className={`h-3.5 flex-1 rounded-full ${i < thisWeek ? "bg-emerald-500" : "bg-brand-100"}`} />
        ))}
      </div>
      <p className="mt-3 text-sm text-ink-500">
        {caption}
        {last}
      </p>
      {failed && <p className="mt-2 text-xs text-red-600">Couldn't save the goal. Try again.</p>}
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
  const interviewing = useMutation<JobOut, ApiError, number>({ mutationFn: (id) => api.markInterviewing(id), onSuccess: refresh });

  const openAndFill = async (job: JobOut) => {
    setNote(null);
    const reply = await completeApplication(job.id, job.canonical_application_url);
    if (reply === null) setNote("The browser extension didn't answer. Reload it on the extensions page, then refresh this page.");
    else if (!reply.ok) setNote(reply.error ?? "Couldn't start the application.");
    else setNote("Opened in a new tab and filling now. You will get a notification when it is done.");
  };

  const shown = jobs.slice(0, 5);
  const sees = stage === "ready" || stage === "applied" || stage === "interviewing" ? `/jobs?stage=${stage}` : stage === "going" ? "/jobs?stage=going" : "/jobs";

  const detail = (j: JobOut): string => {
    const parts = [j.company];
    if (j.evaluation) parts.push(`Score ${Math.round(j.evaluation.overall_score * 100)}`);
    if (stage === "applied") parts.push(`Applied ${ageText(daysSince(j.applied_at, now))}`);
    else if (stage === "interviewing") parts.push(`Interviewing since ${ageText(daysSince(j.interviewing_at, now))}`);
    else parts.push(`Added ${ageText(daysSince(j.first_seen, now))}`);
    return parts.join(". ");
  };

  return (
    <div className="relative mt-5 rounded-2xl border-2 border-brand-500 bg-white px-6 pb-2 pt-3">
      <div className="flex items-center justify-between py-2">
        <div className="text-sm font-extrabold text-brand-700">{label}</div>
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
            {stage === "applied" && (
              <Button size="sm" onClick={() => interviewing.mutate(j.id)} disabled={interviewing.isPending}>
                Got an interview
              </Button>
            )}
            {stage === "interviewing" && (
              <a href={j.canonical_application_url} target="_blank" rel="noreferrer">
                <Button size="sm" tabIndex={-1}>
                  View posting
                </Button>
              </a>
            )}
          </li>
        ))}
      </ul>
      {(note || proceed.isError || interviewing.isError) && (
        <p className="pb-3 text-xs text-ink-700">{note ?? proceed.error?.message ?? interviewing.error?.message}</p>
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

  const top = matches.slice(0, 4);
  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-extrabold text-ink-900">Best new matches</h2>
          <p className="mt-1 text-xs text-ink-500">From your saved search</p>
        </div>
        <div className="flex items-center gap-3">
          {canRefresh ? (
            <Button size="sm" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
              {refresh.isPending ? "Searching…" : "Refresh saved search"}
            </Button>
          ) : (
            <Link to="/job-search">
              <Button size="sm" tabIndex={-1}>
                Set up a search
              </Button>
            </Link>
          )}
          {matches.length > top.length && (
            <Link to="/job-search" className="text-xs font-bold text-brand-600 hover:underline">
              See all {matches.length}
            </Link>
          )}
        </div>
      </div>
      {refresh.isPending && <p className="mt-3 animate-pulse text-xs text-ink-500">Searching the web. This can take a minute.</p>}
      {refresh.isError && <p className="mt-3 text-xs text-red-600">{refresh.error.message}</p>}
      {notice && !refresh.isPending && !refresh.isError && <p className="mt-3 text-xs text-ink-700">{notice}</p>}
      {loading && <p className="mt-4 text-sm text-ink-400">Loading…</p>}
      {!loading && top.length === 0 && (
        <p className="mt-4 text-sm text-ink-500">
          No new matches waiting.{" "}
          {canRefresh ? "Refresh your saved search to look again." : "Run a search on the Job Search page to see matches here."}
        </p>
      )}
      <ul className="mt-2">
        {top.map((r) => {
          const meta = [r.company, r.location, formatSalary(r.salary_text ? { text: r.salary_text } : null) ?? "Pay not listed"];
          const posted = formatPosted(r.posted_at);
          return (
            <li key={r.id} className="flex items-center gap-4 border-t border-ink-900/5 py-3.5 first:border-t-0">
              <ScoreDot score={r.match_score} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-bold text-ink-900">{r.title}</div>
                <div className="mt-0.5 text-xs text-ink-500">
                  {meta.filter(Boolean).join(". ")}
                  {posted ? `. Posted ${posted}` : ""}
                </div>
              </div>
              <Button size="sm" onClick={() => add.mutate(r.id)} disabled={add.isPending}>
                Add to jobs
              </Button>
            </li>
          );
        })}
      </ul>
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
      <h2 className="text-base font-extrabold text-ink-900">Follow up</h2>
      <p className="mt-1 text-xs text-ink-500">
        Applications with no reply after {FOLLOW_UP_AFTER_DAYS} days, and interviews that need a thank you.
      </p>
      {shown.length === 0 && <p className="mt-4 text-sm text-ink-500">Nobody to follow up with right now.</p>}
      <ul className="mt-2">
        {shown.map((f) => (
          <li key={f.job.id} className="border-t border-ink-900/5 py-3.5 first:border-t-0">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-bold text-ink-900">{f.job.company}</div>
                <div className="mt-0.5 text-xs text-ink-500">
                  {f.kind === "after_interview"
                    ? `Interviewing since ${ageText(f.days)}`
                    : `Applied ${f.days} days ago, no reply`}
                </div>
              </div>
              <Button size="sm" onClick={() => start(f)} disabled={make.isPending && draftFor === f.job.id}>
                {make.isPending && draftFor === f.job.id
                  ? "Writing…"
                  : f.kind === "after_interview"
                    ? "Draft thank you"
                    : "Draft message"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => done.mutate(f.job.id)} disabled={done.isPending}>
                Done
              </Button>
            </div>
            {draftFor === f.job.id && make.isError && (
              <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{make.error.message}</p>
            )}
            {draftFor === f.job.id && draft && (
              <div className="mt-3 rounded-2xl bg-brand-50/60 p-4">
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
                  className="mt-2 w-full rounded-xl border border-ink-300/70 bg-white px-3 py-2 text-sm leading-relaxed text-ink-900"
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
        ))}
      </ul>
      {items.length > shown.length && <p className="mt-2 text-xs text-ink-500">And {items.length - shown.length} more.</p>}
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
  const missing = missingItems(profile, answers);
  const hide = () => {
    setHidden(true);
    try {
      window.localStorage.setItem(HIDE_PROFILE_KEY, "1");
    } catch {
      // hiding is a convenience only
    }
  };
  const next = missing.slice(0, 2).join(" and ").toLowerCase();
  const body: ReactNode = `Add your ${next}${missing.length > 2 ? ` and ${missing.length - 2} more` : ""} to fill more forms automatically.`;
  return (
    <section
      aria-label="Profile completeness"
      className="flex flex-wrap items-center gap-5 rounded-2xl bg-brand-100/70 px-7 py-6"
    >
      <Ring value={percent / 100} size={64} stroke={7} color="#5b57f5">
        <span className="text-sm font-extrabold text-ink-900">{percent}%</span>
      </Ring>
      <div className="min-w-[16rem] flex-1">
        <h2 className="text-base font-extrabold text-ink-900">Your profile is almost there</h2>
        <p className="mt-1 text-sm text-ink-700">{body}</p>
      </div>
      <div className="flex items-center gap-2">
        <Link to="/profile">
          <Button variant="primary" tabIndex={-1}>
            Finish profile
          </Button>
        </Link>
        <Button variant="ghost" onClick={hide}>
          Hide
        </Button>
      </div>
    </section>
  );
}
