import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { Badge, Button, Card, CheckIcon, Ring } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";
import { missingItems } from "@/lib/completeness";

interface Step {
  key: string;
  title: string;
  hint: string;
  done: boolean;
  to: string;
  cta: string;
}

const MODE_COPY: Record<string, string> = {
  PAUSED: "Paused. Nothing runs on its own.",
  REVIEW: "On, in review mode. You approve each step.",
  AUTO: "On, in auto mode.",
};

/**
 * Home: a get-started checklist driven by what is really saved on this
 * computer (resume, profile, jobs, scores, tailored resumes), plus the
 * Start/Pause control.
 */
export function Home() {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({ queryKey: ["automation-status"], queryFn: api.automationStatus });
  const masterQuery = useQuery({ queryKey: ["master-status"], queryFn: api.masterStatus });
  const profileQuery = useQuery({ queryKey: ["profile"], queryFn: api.getProfile, retry: false });
  const answersQuery = useQuery({ queryKey: ["answers"], queryFn: api.listAnswers, retry: false });
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  const toggle = useMutation<unknown, ApiError, void>({
    mutationFn: () =>
      statusQuery.data?.mode === "PAUSED" ? api.startAutomation() : api.pauseAutomation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["automation-status"] }),
  });

  const isPaused = statusQuery.data?.mode === "PAUSED";
  const jobs = jobsQuery.data ?? [];
  const hasProfile = !!profileQuery.data;
  const missing = missingItems(profileQuery.data, answersQuery.data);
  const scored = jobs.filter((j) => j.evaluation).length;
  const resumes = jobs.filter((j) => j.documents.some((d) => d.document_type === "resume")).length;
  const proceeding = jobs.filter((j) => j.application_status === "proceeding").length;

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
      done: scored > 0,
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

  return (
    <div>
      <PageHeader
        title="Welcome back"
        description="Here is where your job search stands and what to do next."
      />

      {statusQuery.isError && (
        <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Can't reach the app's backend. Make sure it is running, then refresh this page.
        </div>
      )}

      <Card className="mb-6 overflow-hidden">
        <div className="bg-gradient-to-br from-brand-50 via-white to-sky-50 p-6 md:p-7">
          <div className="flex flex-col gap-6 md:flex-row md:items-center">
            <Ring value={doneCount / steps.length} size={92} stroke={9} color={allDone ? "#12b76a" : "#5b57f5"}>
              <div className="text-center leading-none">
                <div className="text-xl font-bold text-ink-900">
                  {doneCount}/{steps.length}
                </div>
              </div>
            </Ring>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-ink-900">
                {allDone ? "You're all set up" : "Get started"}
              </h2>
              <p className="mt-1 text-sm text-ink-500">
                {allDone
                  ? "Everything on the checklist is done. Add more jobs whenever you find them."
                  : `${steps.length - doneCount} ${steps.length - doneCount === 1 ? "step" : "steps"} left. Finish them in any order.`}
              </p>
            </div>
          </div>
        </div>

        <ol className="divide-y divide-ink-900/5">
          {steps.map((step, i) => {
            const isNext = i === nextIndex;
            return (
              <li
                key={step.key}
                className={`flex items-center gap-4 px-6 py-4 md:px-7 ${isNext ? "bg-brand-50/50" : ""}`}
              >
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
        {loading && <div className="px-7 pb-4 text-xs text-ink-400">Checking what's saved…</div>}
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <div className="text-sm font-semibold text-ink-500">Automation</div>
          <div className="mt-2 flex items-center gap-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${isPaused ? "bg-ink-300" : "bg-emerald-500"}`}
              aria-hidden="true"
            />
            <div className="text-base font-bold text-ink-900">
              {statusQuery.isLoading ? "Checking…" : isPaused ? "Paused" : "On"}
            </div>
          </div>
          <p className="mt-1.5 text-sm text-ink-500">
            {statusQuery.data ? (MODE_COPY[statusQuery.data.mode] ?? statusQuery.data.mode) : "Checking status."}
          </p>
          <Button
            className="mt-4"
            variant={isPaused ? "primary" : "secondary"}
            onClick={() => toggle.mutate()}
            disabled={toggle.isPending || statusQuery.isLoading}
          >
            {isPaused ? "Start" : "Pause"}
          </Button>
          {toggle.isError && <p className="mt-2 text-xs text-red-600">{toggle.error.message}</p>}
        </Card>

        <Card className="p-6">
          <div className="text-sm font-semibold text-ink-500">Your search so far</div>
          <dl className="mt-3 grid grid-cols-2 gap-4">
            <Stat label="Jobs saved" value={jobs.length} />
            <Stat label="Scored" value={scored} />
            <Stat label="Going after" value={proceeding} />
            <Stat label="Resumes ready" value={resumes} />
          </dl>
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dd className="text-2xl font-bold text-ink-900">{value}</dd>
      <dt className="text-xs text-ink-500">{label}</dt>
    </div>
  );
}
