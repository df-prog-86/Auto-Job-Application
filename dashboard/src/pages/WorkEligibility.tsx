import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import type { AnswerOut } from "@/types/api";

const AUTHORIZATION_OPTIONS = [
  "US citizen",
  "Permanent resident (green card)",
  "Work visa (such as H-1B or OPT)",
  "Other",
];
const CLEARANCE_OPTIONS = ["None", "Public Trust", "Secret", "Top Secret", "Top Secret/SCI"];

function answerValue(answers: AnswerOut[] | undefined, key: string): unknown {
  return answers?.find((a) => a.answer_key === key)?.value;
}

/**
 * Work authorization, sponsorship, and security clearance. Saved on this
 * computer as the candidate's own answers (the same answer library used for
 * application questions). Leaving a field "Not set" is fine and different
 * from answering "No": the app never guesses a missing answer.
 */
export function WorkEligibility() {
  const queryClient = useQueryClient();
  const answersQuery = useQuery({ queryKey: ["answers"], queryFn: api.listAnswers, retry: false });

  const [authorization, setAuthorization] = useState("");
  const [sponsorship, setSponsorship] = useState<"" | "yes" | "no">("");
  const [clearance, setClearance] = useState("");

  useEffect(() => {
    if (!answersQuery.data) return;
    setAuthorization((answerValue(answersQuery.data, "work_authorization") as string) ?? "");
    const sponsor = answerValue(answersQuery.data, "sponsorship_required");
    setSponsorship(sponsor === true ? "yes" : sponsor === false ? "no" : "");
    setClearance((answerValue(answersQuery.data, "security_clearance") as string) ?? "");
  }, [answersQuery.data]);

  const saveMutation = useMutation<void, ApiError, void>({
    mutationFn: async () => {
      if (authorization) {
        await api.saveAnswer("work_authorization", { value_type: "str", value: authorization });
      }
      if (sponsorship) {
        await api.saveAnswer("sponsorship_required", { value_type: "bool", value: sponsorship === "yes" });
      }
      if (clearance) {
        await api.saveAnswer("security_clearance", { value_type: "str", value: clearance });
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["answers"] }),
  });

  const noProfileYet = answersQuery.isError && (answersQuery.error as ApiError).status === 404;

  return (
    <div>
      <PageHeader
        title="Work Eligibility"
        description="Your work authorization, sponsorship needs, and security clearance. Saved only on this computer and used later when applications are filled out."
      />

      {noProfileYet && (
        <div className="max-w-lg rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
          Upload your resume on the Profile page first. These answers attach to your profile.
        </div>
      )}

      {answersQuery.isError && !noProfileYet && (
        <p className="text-sm text-red-600">{(answersQuery.error as ApiError).message}</p>
      )}

      {answersQuery.data && (
        <form
          className="max-w-lg space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
          onSubmit={(e) => {
            e.preventDefault();
            saveMutation.mutate();
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">Work authorization</span>
            <select
              value={authorization}
              onChange={(e) => setAuthorization(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5"
            >
              <option value="">Not set</option>
              {AUTHORIZATION_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">
              Will you now or in the future need an employer to sponsor your work visa?
            </span>
            <select
              value={sponsorship}
              onChange={(e) => setSponsorship(e.target.value as "" | "yes" | "no")}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5"
            >
              <option value="">Not set</option>
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </select>
          </label>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">Security clearance you hold</span>
            <select
              value={clearance}
              onChange={(e) => setClearance(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5"
            >
              <option value="">Not set</option>
              {CLEARANCE_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>

          <p className="text-xs text-slate-400">
            "Not set" means the app won't answer that question for you. It never guesses.
          </p>

          <button
            type="submit"
            disabled={saveMutation.isPending}
            className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {saveMutation.isPending ? "Saving…" : "Save"}
          </button>
          {saveMutation.isSuccess && <p className="text-sm text-emerald-600">Saved.</p>}
          {saveMutation.isError && <p className="text-sm text-red-600">{saveMutation.error.message}</p>}
        </form>
      )}
    </div>
  );
}
