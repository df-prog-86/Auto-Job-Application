import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Button, Card, CheckIcon, inputClass } from "@/components/ui";
import type { PendingQuestionOut } from "@/types/api";

/**
 * Questions the browser extension left blank because it wasn't sure how to
 * answer them. Your answer is remembered, so the same question is filled in
 * automatically the next time it appears.
 */
export function NeedsAttention() {
  const query = useQuery({ queryKey: ["needs-attention"], queryFn: api.listNeedsAttention });
  const items = query.data ?? [];

  return (
    <div>
      <PageHeader
        title="Needs Attention"
        description="Questions the extension wasn't sure how to answer. Answer once and it remembers."
        action={items.length > 0 ? <Badge tone="warning">{items.length} open</Badge> : undefined}
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

      <ul className="space-y-4">
        {items.map((q) => (
          <QuestionCard key={q.id} q={q} />
        ))}
      </ul>
    </div>
  );
}

function QuestionCard({ q }: { q: PendingQuestionOut }) {
  const queryClient = useQueryClient();
  const [answer, setAnswer] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["needs-attention"] });

  const save = useMutation<PendingQuestionOut, ApiError, void>({
    mutationFn: () => api.answerQuestion(q.id, answer),
    onSuccess: refresh,
  });
  const skip = useMutation<PendingQuestionOut, ApiError, void>({
    mutationFn: () => api.dismissQuestion(q.id),
    onSuccess: refresh,
  });

  const error = save.error ?? skip.error;

  return (
    <li>
      <Card className="p-6">
        <div className="mb-1 text-xs font-semibold text-ink-400">
          {q.job_title} at {q.company}
        </div>
        <h2 className="text-base font-bold leading-snug text-ink-900">
          {q.label}
          {q.required && <span className="ml-2 align-middle"><Badge tone="warning">Required</Badge></span>}
        </h2>

        <form
          className="mt-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (answer.trim()) save.mutate();
          }}
        >
          {q.options.length > 0 ? (
            <select value={answer} onChange={(e) => setAnswer(e.target.value)} className={inputClass}>
              <option value="">Choose an answer</option>
              {q.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <textarea
              rows={q.field_type === "textarea" ? 4 : 2}
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
            <Button type="button" variant="ghost" size="sm" onClick={() => skip.mutate()} disabled={skip.isPending}>
              Skip this question
            </Button>
          </div>
        </form>
        <p className="mt-3 text-xs text-ink-400">
          After you save, fill that field on the application yourself, or run Fill again from the extension.
        </p>
        {error && <p className="mt-2 text-sm text-red-600">{error.message}</p>}
      </Card>
    </li>
  );
}
