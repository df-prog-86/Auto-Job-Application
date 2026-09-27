import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import type { DraftClaim, ResumeExtraction, ResumeParseResponse } from "@/types/api";

/**
 * Milestone 2 onboarding flow (spec §4.2, §15 steps 1-3): upload -> review
 * extracted profile + verified claims -> commit. Per spec, the candidate
 * must be able to correct extracted information before automation is
 * enabled — this pass covers contact-field edits and per-claim
 * approve/discard, which is the minimum "correction" surface; richer
 * per-field editing across employment/education entries is a Milestone 10
 * polish item, not required for the onboarding acceptance test.
 */
export function Profile() {
  const queryClient = useQueryClient();
  const [reviewData, setReviewData] = useState<ResumeParseResponse | null>(null);
  const [reviewFilename, setReviewFilename] = useState<string>("resume");

  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: api.getProfile,
    retry: false,
  });

  const noProfileYet = profileQuery.isError && (profileQuery.error as ApiError)?.status === 404;

  const parseMutation = useMutation<ResumeParseResponse, ApiError, File>({
    mutationFn: api.parseResume,
    onSuccess: (data, file) => {
      setReviewData(data);
      setReviewFilename(file.name);
    },
  });

  if (profileQuery.isLoading) {
    return (
      <div>
        <PageHeader title="Profile" />
        <p className="text-sm text-slate-400">Loading…</p>
      </div>
    );
  }

  if (reviewData) {
    return (
      <ReviewAndCommit
        data={reviewData}
        filename={reviewFilename}
        onDone={() => {
          setReviewData(null);
          queryClient.invalidateQueries({ queryKey: ["profile"] });
        }}
        onCancel={() => setReviewData(null)}
      />
    );
  }

  if (profileQuery.data && !noProfileYet) {
    const profile = profileQuery.data;
    return (
      <div>
        <PageHeader title="Profile" description="Your candidate profile, extracted from your resume." />
        <div className="max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <dl className="space-y-2 text-sm">
            <Row label="Name" value={profile.name} />
            <Row label="Email" value={profile.email} />
            <Row label="Phone" value={profile.phone} />
            <Row label="Location" value={profile.location} />
            <Row label="LinkedIn" value={profile.linkedin_url} />
          </dl>
        </div>
        <UploadForm parseMutation={parseMutation} buttonLabel="Upload a new resume" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Profile"
        description="Upload your resume to build your candidate profile."
      />
      <UploadForm parseMutation={parseMutation} buttonLabel="Parse resume" />
    </div>
  );
}

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between border-b border-slate-100 py-1 last:border-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900">{value || "—"}</dd>
    </div>
  );
}

function UploadForm({
  parseMutation,
  buttonLabel,
}: {
  parseMutation: UseMutationResult<ResumeParseResponse, ApiError, File>;
  buttonLabel: string;
}) {
  const [file, setFile] = useState<File | null>(null);

  return (
    <div className="mt-6 max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <input
        type="file"
        accept=".pdf,.docx"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        className="mb-4 block w-full text-sm"
      />
      <button
        onClick={() => file && parseMutation.mutate(file)}
        disabled={!file || parseMutation.isPending}
        className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
      >
        {parseMutation.isPending ? "Parsing…" : buttonLabel}
      </button>

      {parseMutation.isError && (
        <p className="mt-3 text-sm text-red-600">{parseMutation.error.message}</p>
      )}
    </div>
  );
}

function ReviewAndCommit({
  data,
  filename,
  onDone,
  onCancel,
}: {
  data: ResumeParseResponse;
  filename: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [extraction, setExtraction] = useState<ResumeExtraction>(data.extraction);
  const [approved, setApproved] = useState<boolean[]>(data.draft_claims.map(() => true));

  const commitMutation = useMutation({
    mutationFn: () =>
      api.commitProfile({
        extraction,
        approved_claims: data.draft_claims.filter((_, i) => approved[i]),
        resume_filename: filename,
      }),
    onSuccess: onDone,
  });

  function updateContact<K extends keyof ResumeExtraction["contact"]>(
    field: K,
    value: ResumeExtraction["contact"][K],
  ) {
    setExtraction((prev) => ({ ...prev, contact: { ...prev.contact, [field]: value } }));
  }

  return (
    <div>
      <PageHeader
        title="Review your profile"
        description="Correct anything that looks wrong, uncheck any claim you don't want used, then confirm."
      />

      {data.used_ocr && (
        <div className="mb-4 rounded-md bg-amber-50 px-4 py-2 text-sm text-amber-700">
          This file needed OCR to read — double-check the extracted text carefully below.
        </div>
      )}

      <div className="mb-6 max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Contact information</h2>
        <div className="space-y-3">
          <LabeledInput
            label="Name"
            value={extraction.contact.name}
            onChange={(v) => updateContact("name", v)}
          />
          <LabeledInput
            label="Email"
            value={extraction.contact.email ?? ""}
            onChange={(v) => updateContact("email", v)}
          />
          <LabeledInput
            label="Phone"
            value={extraction.contact.phone ?? ""}
            onChange={(v) => updateContact("phone", v)}
          />
          <LabeledInput
            label="Location"
            value={extraction.contact.location ?? ""}
            onChange={(v) => updateContact("location", v)}
          />
        </div>
      </div>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          Verified claims ({data.draft_claims.length})
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          These are the atomic facts your tailored resumes and application answers will draw
          from later. Uncheck anything inaccurate or that you'd rather not use.
        </p>
        <ul className="divide-y divide-slate-100">
          {data.draft_claims.map((claim, i) => (
            <ClaimRow
              key={i}
              claim={claim}
              approved={approved[i]}
              onToggle={() =>
                setApproved((prev) => prev.map((v, j) => (j === i ? !v : v)))
              }
            />
          ))}
        </ul>
      </div>

      <div className="flex gap-3">
        <button
          onClick={() => commitMutation.mutate()}
          disabled={commitMutation.isPending}
          className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {commitMutation.isPending ? "Saving…" : "Confirm and save profile"}
        </button>
        <button
          onClick={onCancel}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>

      {commitMutation.isError && (
        <p className="mt-3 text-sm text-red-600">{(commitMutation.error as ApiError).message}</p>
      )}
    </div>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-3 py-1.5"
      />
    </label>
  );
}

function ClaimRow({
  claim,
  approved,
  onToggle,
}: {
  claim: DraftClaim;
  approved: boolean;
  onToggle: () => void;
}) {
  return (
    <li className="flex items-start gap-3 py-3">
      <input
        type="checkbox"
        checked={approved}
        onChange={onToggle}
        className="mt-1 h-4 w-4 accent-brand-500"
      />
      <div>
        <div className={`text-sm ${approved ? "text-slate-900" : "text-slate-400 line-through"}`}>
          {claim.canonical_text}
        </div>
        <div className="text-xs text-slate-400">
          {claim.category} · from: "{claim.source_text}"
        </div>
      </div>
    </li>
  );
}
