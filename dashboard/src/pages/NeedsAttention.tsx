import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Button, Card, CheckIcon, inputClass } from "@/components/ui";
import type { PendingQuestionOut } from "@/types/api";

/** Same wording rule the extension uses to tell two questions apart. */
function questionKey(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

interface Group {
  key: string;
  label: string;
  required: boolean;
  fieldType: string;
  options: string[];
  items: PendingQuestionOut[];
}

/** One card per question, however many jobs asked it. */
function groupQuestions(items: PendingQuestionOut[]): Group[] {
  const byKey = new Map<string, Group>();
  for (const q of items) {
    const key = questionKey(q.label);
    const existing = byKey.get(key);
    if (existing) {
      existing.items.push(q);
      existing.required = existing.required || q.required;
      if (existing.options.length === 0 && q.options.length > 0) existing.options = q.options;
    } else {
      byKey.set(key, {
        key,
        label: q.label,
        required: q.required,
        fieldType: q.field_type,
        options: q.options,
        items: [q],
      });
    }
  }
  return Array.from(byKey.values());
}

/**
 * Questions the browser extension left blank because it wasn't sure how to
 * answer them. Your answer is remembered, so the same question is filled in
 * automatically the next time it appears.
 */
export function NeedsAttention() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["needs-attention"], queryFn: api.listNeedsAttention });
  const [search, setSearch] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);
  const items = query.data ?? [];
  const groups = useMemo(() => groupQuestions(items), [items]);
  const needle = search.trim().toLowerCase();
  const shown = needle ? groups.filter((g) => g.label.toLowerCase().includes(needle)) : groups;

  const clearAll = useMutation<{ cleared: number }, ApiError, void>({
    mutationFn: () => api.clearQuestions(),
    onSuccess: async () => {
      setConfirmAll(false);
      await queryClient.invalidateQueries({ queryKey: ["needs-attention"] });
    },
  });

  return (
    <div>
      <PageHeader
        title="Needs Attention"
        description="Questions the extension wasn't sure how to answer. Answer once and it remembers. After you save, fill that field on the application yourself, or run Fill again."
        action={groups.length > 0 ? <Badge tone="warning">{groups.length} to review</Badge> : undefined}
      />

      {query.isLoading && <p className="text-sm text-ink-400">Loading…</p>}
      {query.isError && <p className="text-sm text-red-600">Couldn't load your questions. Make sure the backend is running.</p>}

      {query.data && items.length === 0 && (
        <Card className="p-10 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600">
            <CheckIcon className="h-7 w-7" />
          </div>
          <h2 className="text-base font-bold text-ink-900">Nothing needs your attention</h2>
          <p className="mx-auto mt-1 max-w-sm text-sm text-ink-500">
            When the extension fills an application and isn't sure about a question, it shows up here.
          </p>
        </Card>
      )}

      {groups.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search questions"
            aria-label="Search questions"
            className={`${inputClass} max-w-xs`}
          />
          <div className="ml-auto flex items-center gap-2">
            {confirmAll ? (
              <>
                <span className="text-xs text-ink-500">Clear all {groups.length} questions? Nothing is answered or saved.</span>
                <Button size="sm" variant="danger" disabled={clearAll.isPending} onClick={() => clearAll.mutate()}>
                  {clearAll.isPending ? "Clearing…" : "Yes, clear all"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmAll(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button size="sm" onClick={() => setConfirmAll(true)}>
                Clear all
              </Button>
            )}
          </div>
        </div>
      )}
      {clearAll.error && <p className="mb-3 text-sm text-red-600">{clearAll.error.message}</p>}
      {needle && shown.length === 0 && groups.length > 0 && <p className="text-sm text-ink-400">No questions match "{search}".</p>}

      <ul className="space-y-4">
        {shown.map((g) => (
          <QuestionCard key={g.key} group={g} />
        ))}
      </ul>

      <SavedAnswers />
    </div>
  );
}

/** Answers the app remembers from earlier applications. Forget one and it is asked again next time. */
function SavedAnswers() {
  const queryClient = useQueryClient();
  const answers = useQuery({ queryKey: ["answers"], queryFn: api.listAnswers });
  const forget = useMutation<void, ApiError, string>({
    mutationFn: (key) => api.forgetAnswer(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["answers"] }),
  });
  const saved = (answers.data ?? []).filter((a) => a.answer_key.startsWith("q:") && typeof a.value === "string");
  if (saved.length === 0) return null;

  return (
    <section className="mt-10">
      <h2 className="text-base font-bold text-ink-900">Answers I remember</h2>
      <p className="mb-3 mt-1 text-xs text-ink-500">
        Filled in automatically when the same question appears. Forget one if it is wrong or out of date.
      </p>
      <Card className="divide-y divide-ink-900/5">
        {saved.map((a) => (
          <div key={a.answer_key} className="flex items-center justify-between gap-4 px-5 py-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-ink-900">{a.explanatory_text || a.answer_key.slice(2)}</div>
              <div className="truncate text-sm text-ink-500">{String(a.value)}</div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={forget.isPending}
              onClick={() => forget.mutate(a.answer_key)}
            >
              Forget
            </Button>
          </div>
        ))}
      </Card>
      {forget.error && <p className="mt-2 text-sm text-red-600">{forget.error.message}</p>}
    </section>
  );
}

function QuestionCard({ group }: { group: Group }) {
  const queryClient = useQueryClient();
  const [answer, setAnswer] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["needs-attention"] });
  const first = group.items[0];

  // Saving once settles every job that asked the same question.
  const save = useMutation<PendingQuestionOut, ApiError, void>({
    mutationFn: () => api.answerQuestion(first.id, answer),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["answers"] });
      await refresh();
    },
  });
  const clear = useMutation<{ cleared: number }, ApiError, void>({
    mutationFn: () => api.clearQuestions(group.items.map((q) => q.id)),
    onSuccess: refresh,
  });

  const error = save.error ?? clear.error;
  const jobs = Array.from(new Set(group.items.map((q) => `${q.job_title} at ${q.company}`)));

  return (
    <li>
      <Card className="p-6">
        <div className="mb-1 text-xs font-semibold text-ink-400">
          {jobs.length === 1 ? jobs[0] : `Asked on ${jobs.length} applications`}
        </div>
        {jobs.length > 1 && <div className="mb-1 truncate text-xs text-ink-400">{jobs.slice(0, 3).join(", ")}{jobs.length > 3 ? ", …" : ""}</div>}
        <h2 className="text-base font-bold leading-snug text-ink-900">
          {group.label}
          {group.required && (
            <span className="ml-2 align-middle">
              <Badge tone="warning">Required</Badge>
            </span>
          )}
        </h2>

        <form
          className="mt-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (answer.trim()) save.mutate();
          }}
        >
          {group.options.length > 0 ? (
            <select value={answer} onChange={(e) => setAnswer(e.target.value)} className={inputClass}>
              <option value="">Choose an answer</option>
              {group.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <textarea
              rows={group.fieldType === "textarea" ? 4 : 2}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type your answer"
              className={inputClass}
            />
          )}
          <div className="mt-3 flex items-center gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={!answer.trim() || save.isPending}>
              {save.isPending ? "Saving…" : "Save answer"}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => clear.mutate()} disabled={clear.isPending}>
              {clear.isPending ? "Clearing…" : "Clear"}
            </Button>
          </div>
        </form>
        {error && <p className="mt-2 text-sm text-red-600">{error.message}</p>}
      </Card>
    </li>
  );
}
