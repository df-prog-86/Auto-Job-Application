import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, ApiError } from "@/api/client";
import { EditableField, SelectField } from "@/components/EditableField";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Button, Card, CheckIcon, inputClass } from "@/components/ui";
import { answerValue, missingItems } from "@/lib/completeness";
import type {
  AnswerOut,
  DraftClaim,
  CertificationOut,
  EducationOut,
  EmploymentHistoryOut,
  MasterRole,
  ProfileOut,
  ResumeExtraction,
  ResumeParseResponse,
} from "@/types/api";

const AUTHORIZATION_OPTIONS = [
  "US citizen",
  "Permanent resident (green card)",
  "Work visa (such as H-1B or OPT)",
  "Other",
].map((o) => ({ value: o, label: o }));
const CLEARANCE_OPTIONS = ["None", "Public Trust", "Secret", "Top Secret", "Top Secret/SCI"].map((o) => ({
  value: o,
  label: o,
}));
const PHONE_COUNTRY_OPTIONS = [
  "United States (+1)",
  "Canada (+1)",
  "United Kingdom (+44)",
  "Ireland (+353)",
  "India (+91)",
  "Australia (+61)",
  "Germany (+49)",
  "France (+33)",
  "Mexico (+52)",
  "Philippines (+63)",
].map((o) => ({ value: o, label: o }));
const SKIP = { value: "skip", label: "Don't fill this in" };
const GENDER_OPTIONS = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "decline", label: "Decline to self-identify" },
  SKIP,
];
const RACE_OPTIONS = [
  { value: "hispanic", label: "Hispanic or Latino" },
  { value: "white", label: "White (Not Hispanic or Latino)" },
  { value: "black", label: "Black or African American (Not Hispanic or Latino)" },
  { value: "pacific", label: "Native Hawaiian or Other Pacific Islander (Not Hispanic or Latino)" },
  { value: "asian", label: "Asian (Not Hispanic or Latino)" },
  { value: "native", label: "American Indian or Alaska Native (Not Hispanic or Latino)" },
  { value: "two_or_more", label: "Two or More Races (Not Hispanic or Latino)" },
  { value: "decline", label: "Decline to self-identify" },
  SKIP,
];
const VETERAN_OPTIONS = [
  { value: "protected", label: "I identify as one or more of the classifications of protected veteran" },
  { value: "not_protected", label: "I am not a protected veteran" },
  { value: "decline", label: "I decline to self-identify for protected veteran status" },
  SKIP,
];
const PHONE_TYPE_OPTIONS = ["Mobile", "Landline"].map((o) => ({ value: o, label: o }));
const SPONSORSHIP_OPTIONS = [
  { value: "no", label: "No" },
  { value: "yes", label: "Yes" },
];

/** "2021-04-01" or "2021-04" -> "2021-04" (what a month input wants). */
function toMonth(value?: string | null): string {
  return value ? value.slice(0, 7) : "";
}

function formatDay(value: string): string {
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return value;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatMonth(value: string): string {
  const [y, m] = value.split("-").map(Number);
  if (!y || !m) return value;
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

/**
 * Pairs each saved role with its bullets from the master resume. Matches on
 * company (then job title) appearing in the lines above a bullet list, then
 * falls back to document order when every role is left unmatched and the
 * counts line up. Anything uncertain shows no bullets rather than the wrong ones.
 */
function bulletsByRole(jobs: EmploymentHistoryOut[], roles: MasterRole[]): (string[] | null)[] {
  const used = new Set<number>();
  const result: (string[] | null)[] = jobs.map(() => null);
  const find = (needle: string) => {
    const n = needle.trim().toLowerCase();
    if (n.length < 3) return -1;
    return roles.findIndex((r, i) => !used.has(i) && r.context.toLowerCase().includes(n));
  };
  jobs.forEach((job, i) => {
    let idx = find(job.employer);
    if (idx === -1) idx = find(job.title);
    if (idx !== -1) {
      used.add(idx);
      result[i] = roles[idx].bullets;
    }
  });
  if (used.size === 0 && jobs.length > 0 && jobs.length === roles.length) {
    return roles.map((r) => r.bullets);
  }
  return result;
}

export function Profile() {
  const queryClient = useQueryClient();
  const [reviewData, setReviewData] = useState<ResumeParseResponse | null>(null);
  const [reviewFilename, setReviewFilename] = useState<string>("resume");

  const profileQuery = useQuery({ queryKey: ["profile"], queryFn: api.getProfile, retry: false });
  const noProfileYet = profileQuery.isError && (profileQuery.error as ApiError)?.status === 404;
  const profile = noProfileYet ? undefined : profileQuery.data;

  const answersQuery = useQuery({
    queryKey: ["answers"],
    queryFn: api.listAnswers,
    enabled: !!profile,
    retry: false,
  });
  const rolesQuery = useQuery({ queryKey: ["master-roles"], queryFn: api.masterRoles, enabled: !!profile });

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
        <p className="text-sm text-ink-400">Loading…</p>
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
          void queryClient.invalidateQueries({ queryKey: ["profile"] });
          void queryClient.invalidateQueries({ queryKey: ["master-status"] });
          void queryClient.invalidateQueries({ queryKey: ["master-roles"] });
        }}
        onCancel={() => setReviewData(null)}
      />
    );
  }

  if (profileQuery.isError && !noProfileYet) {
    return (
      <div>
        <PageHeader title="Profile" />
        <p className="text-sm text-red-600">{(profileQuery.error as ApiError).message}</p>
      </div>
    );
  }

  if (!profile) {
    return (
      <div>
        <PageHeader
          title="Profile"
          description="Start with your resume. We read it and fill in your profile for you to check."
        />
        <ResumeDrop parseMutation={parseMutation} hasProfile={false} />
      </div>
    );
  }

  const answers = answersQuery.data;
  const missing = missingItems(profile, answers);
  const bullets = bulletsByRole(profile.employment_history, rolesQuery.data ?? []);

  /** Runs a profile edit and puts the fresh profile straight into the cache. */
  const applyProfile = async (call: Promise<ProfileOut>) => {
    const updated = await call;
    queryClient.setQueryData(["profile"], updated);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        description="This is what applications are filled out from. Click any field to change it."
      />

      <SectionNav />

      <div id="profile-resume" className="scroll-mt-20">
        <ResumeDrop parseMutation={parseMutation} hasProfile />
      </div>

      <CompletionBanner missing={missing} />

      <Card className="p-6">
        <h2 id="profile-details" className="mb-4 scroll-mt-20 text-base font-bold text-ink-900">Personal details</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <EditableField
            label="Name"
            value={profile.name}
            required
            bold
            onSave={(v) => applyProfile(api.updateProfile({ name: v }))}
          />
          <EditableField
            label="Preferred first name"
            value={profile.preferred_name ?? ""}
            emptyLabel="Same as your first name"
            onSave={(v) => applyProfile(api.updateProfile({ preferred_name: v || null }))}
          />
          <EditableField
            label="Email"
            value={profile.email}
            required
            type="email"
            onSave={(v) => applyProfile(api.updateProfile({ email: v }))}
          />
          <EditableField
            label="Phone"
            value={profile.phone ?? ""}
            required
            type="tel"
            onSave={(v) => applyProfile(api.updateProfile({ phone: v || null }))}
          />
          <EditableField
            label="Location"
            value={profile.location ?? ""}
            required
            onSave={(v) => applyProfile(api.updateProfile({ location: v || null }))}
          />
          <EditableField
            label="LinkedIn"
            value={profile.linkedin_url ?? ""}
            type="url"
            className="sm:col-span-2"
            onSave={(v) => applyProfile(api.updateProfile({ linkedin_url: v || null }))}
          />
        </div>
      </Card>

      <div id="profile-answers" className="scroll-mt-20">
        <EligibilityCard answers={answers} loading={answersQuery.isLoading} />
      </div>

      <div id="profile-selfid" className="scroll-mt-20">
        <SelfIdCard answers={answers} loading={answersQuery.isLoading} />
      </div>

      <section id="profile-experience" className="scroll-mt-20">
        <SectionTitle
          title="Experience"
          action={
            <Button
              size="sm"
              onClick={() => void applyProfile(api.addEmployment({}))}
            >
              Add a role
            </Button>
          }
        />
        <div className="space-y-4">
          {profile.employment_history.length === 0 && (
            <EmptyNote>
              No roles yet. Add one, or upload your resume again to read them from it.
            </EmptyNote>
          )}
          {profile.employment_history.map((job, i) => (
            <RoleCard key={job.id} job={job} bullets={bullets[i]} onChange={applyProfile} />
          ))}
        </div>
        {rolesQuery.data && rolesQuery.data.length > 0 && (
          <p className="mt-3 text-xs text-ink-400">
            Bullets are read from your saved master resume. To change them, upload an updated
            resume.
          </p>
        )}
      </section>

      <section id="profile-education" className="scroll-mt-20">
        <SectionTitle
          title="Education"
          action={
            <Button size="sm" onClick={() => void applyProfile(api.addEducation({}))}>
              Add a school
            </Button>
          }
        />
        <div className="space-y-4">
          {profile.education.length === 0 && <EmptyNote>No education yet. Add a school above.</EmptyNote>}
          {profile.education.map((edu) => (
            <EducationCard key={edu.id} edu={edu} onChange={applyProfile} />
          ))}
        </div>
      </section>

      <div id="profile-skills" className="scroll-mt-20">
        <SkillsCard skills={profile.skills} onChange={applyProfile} />
      </div>

      <section id="profile-certs" className="scroll-mt-20">
        <SectionTitle
          title="Certifications"
          action={
            <Button size="sm" onClick={() => void applyProfile(api.addCertification({}))}>
              Add a certification
            </Button>
          }
        />
        <div className="space-y-4">
          {profile.certifications.length === 0 && (
            <EmptyNote>No certifications yet. Add one above if the applications you fill ask for them.</EmptyNote>
          )}
          {profile.certifications.map((cert) => (
            <CertificationCard key={cert.id} cert={cert} onChange={applyProfile} />
          ))}
        </div>
      </section>
    </div>
  );
}

const PROFILE_SECTIONS: { id: string; label: string }[] = [
  { id: "profile-resume", label: "Resume" },
  { id: "profile-details", label: "Details" },
  { id: "profile-answers", label: "Answers" },
  { id: "profile-selfid", label: "Self-ID" },
  { id: "profile-experience", label: "Experience" },
  { id: "profile-education", label: "Education" },
  { id: "profile-skills", label: "Skills" },
  { id: "profile-certs", label: "Certifications" },
];

/** Jump links that stay in view while the page scrolls. */
function SectionNav() {
  return (
    <nav
      aria-label="Profile sections"
      className="sticky top-0 z-10 -mx-1 flex gap-1.5 overflow-x-auto rounded-2xl border border-white bg-white/90 px-2 py-2 shadow-soft backdrop-blur"
    >
      {PROFILE_SECTIONS.map((sec) => (
        <button
          key={sec.id}
          type="button"
          onClick={() => document.getElementById(sec.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
          className="shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold text-ink-500 transition hover:bg-brand-50 hover:text-brand-700"
        >
          {sec.label}
        </button>
      ))}
    </nav>
  );
}

function SectionTitle({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-base font-bold text-ink-900">{title}</h2>
      {action}
    </div>
  );
}

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-300 bg-white/60 p-6 text-center text-sm text-ink-500">
      {children}
    </div>
  );
}

function CompletionBanner({ missing }: { missing: string[] }) {
  if (missing.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-3.5 text-sm font-semibold text-emerald-800">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white">
          <CheckIcon />
        </span>
        Your profile is complete.
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4">
      <div className="text-sm font-bold text-amber-900">
        {missing.length} {missing.length === 1 ? "thing needs" : "things need"} completion
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {missing.map((m) => (
          <span key={m} className="rounded-full bg-white px-2.5 py-0.5 text-xs font-medium text-amber-800">
            {m}
          </span>
        ))}
      </div>
    </div>
  );
}

function EligibilityCard({ answers, loading }: { answers: AnswerOut[] | undefined; loading: boolean }) {
  const queryClient = useQueryClient();

  const save = async (key: string, type: "str" | "bool", value: string) => {
    await api.saveAnswer(key, {
      value_type: type,
      value: type === "bool" ? value === "yes" : value,
    });
    await queryClient.invalidateQueries({ queryKey: ["answers"] });
  };

  const sponsor = answerValue(answers, "sponsorship_required");
  const yesNo = (key: string) => {
    const v = answerValue(answers, key);
    return v === true ? "yes" : v === false ? "no" : "";
  };

  const yesNoOptions = SPONSORSHIP_OPTIONS.slice().reverse();

  return (
    <Card className="p-6">
      <h2 className="text-base font-bold text-ink-900">Answers used on every application</h2>
      <p className="mb-4 mt-1 text-xs text-ink-500">
        Saved only on this computer. The app never guesses an answer you haven't given.
      </p>
      {loading ? (
        <p className="text-sm text-ink-400">Loading…</p>
      ) : (
        <div className="space-y-6">
          <AnswerGroup title="Work eligibility">
            <SelectField
              label="Work authorization"
              required
              value={(answerValue(answers, "work_authorization") as string | undefined) ?? ""}
              options={AUTHORIZATION_OPTIONS}
              onSave={(v) => save("work_authorization", "str", v)}
            />
            <SelectField
              label="Need visa sponsorship now or later?"
              required
              value={sponsor === true ? "yes" : sponsor === false ? "no" : ""}
              options={SPONSORSHIP_OPTIONS}
              onSave={(v) => save("sponsorship_required", "bool", v)}
            />
            <SelectField
              label="Are you 18 or older?"
              value={yesNo("age_18_plus")}
              options={yesNoOptions}
              onSave={(v) => save("age_18_plus", "bool", v)}
            />
            <SelectField
              label="Security clearance (optional)"
              value={(answerValue(answers, "security_clearance") as string | undefined) ?? ""}
              options={CLEARANCE_OPTIONS}
              onSave={(v) => save("security_clearance", "str", v)}
            />
          </AnswerGroup>

          <AnswerGroup title="Background and screening">
            <SelectField
              label="Willing to complete a background check?"
              value={yesNo("background_check_ok")}
              options={yesNoOptions}
              onSave={(v) => save("background_check_ok", "bool", v)}
            />
            <SelectField
              label="Willing to complete a criminal record check?"
              value={yesNo("criminal_check_ok")}
              options={yesNoOptions}
              onSave={(v) => save("criminal_check_ok", "bool", v)}
            />
            <SelectField
              label="Willing to complete a drug screen?"
              value={yesNo("drug_screen_ok")}
              options={yesNoOptions}
              onSave={(v) => save("drug_screen_ok", "bool", v)}
            />
          </AnswerGroup>

          <AnswerGroup title="Address and phone">
            <EditableField
              label="Street address (line 1)"
              value={(answerValue(answers, "address_line1") as string | undefined) ?? ""}
              emptyLabel="Not set"
              onSave={(v) => save("address_line1", "str", v)}
            />
            <EditableField
              label="Postal code"
              value={(answerValue(answers, "postal_code") as string | undefined) ?? ""}
              emptyLabel="Not set"
              onSave={(v) => save("postal_code", "str", v)}
            />
            <SelectField
              label="Phone country code"
              required
              value={(answerValue(answers, "phone_country") as string | undefined) ?? ""}
              options={PHONE_COUNTRY_OPTIONS}
              onSave={(v) => save("phone_country", "str", v)}
            />
            <SelectField
              label="Phone type"
              value={(answerValue(answers, "phone_device_type") as string | undefined) ?? ""}
              options={PHONE_TYPE_OPTIONS}
              onSave={(v) => save("phone_device_type", "str", v)}
            />
          </AnswerGroup>
        </div>
      )}
    </Card>
  );
}

function AnswerGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-3 border-b border-ink-900/5 pb-1.5 text-sm font-bold text-ink-700">{title}</h3>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </div>
  );
}

function SelfIdCard({ answers, loading }: { answers: AnswerOut[] | undefined; loading: boolean }) {
  const queryClient = useQueryClient();

  const save = async (key: string, value: string) => {
    await api.saveAnswer(key, { value_type: "str", value });
    await queryClient.invalidateQueries({ queryKey: ["answers"] });
  };

  return (
    <Card className="p-6">
      <h2 className="text-base font-bold text-ink-900">Voluntary self-identification (optional)</h2>
      <p className="mb-4 mt-1 text-xs text-ink-500">
        Many applications ask these. They are only filled in if you choose an answer here, and they are saved only on
        this computer. Leave one blank, or pick "Don't fill this in", and it stays yours to answer on each form.
      </p>
      {loading ? (
        <p className="text-sm text-ink-400">Loading…</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label="Gender"
            value={(answerValue(answers, "eeo_gender") as string | undefined) ?? ""}
            options={GENDER_OPTIONS}
            onSave={(v) => save("eeo_gender", v)}
          />
          <SelectField
            label="Race"
            value={(answerValue(answers, "eeo_race") as string | undefined) ?? ""}
            options={RACE_OPTIONS}
            onSave={(v) => save("eeo_race", v)}
          />
          <SelectField
            label="Veteran status"
            value={(answerValue(answers, "eeo_veteran") as string | undefined) ?? ""}
            options={VETERAN_OPTIONS}
            onSave={(v) => save("eeo_veteran", v)}
          />
        </div>
      )}
    </Card>
  );
}

function RoleCard({
  job,
  bullets,
  onChange,
}: {
  job: EmploymentHistoryOut;
  bullets: string[] | null;
  onChange: (call: Promise<ProfileOut>) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const edit = (patch: Parameters<typeof api.updateEmployment>[1]) =>
    onChange(api.updateEmployment(job.id, patch));

  return (
    <Card className="p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <EditableField label="Job title" value={job.title} required bold onSave={(v) => edit({ title: v })} />
        <EditableField label="Company" value={job.employer} required onSave={(v) => edit({ employer: v })} />
        <EditableField
          label="Start date"
          value={toMonth(job.start_date)}
          required
          type="month"
          format={formatMonth}
          onSave={(v) => edit({ start_date: v })}
        />
        <EditableField
          label="End date"
          value={toMonth(job.end_date)}
          type="month"
          emptyLabel="Present"
          format={formatMonth}
          onSave={(v) => edit({ end_date: v })}
        />
        <EditableField
          label="Location"
          value={job.location ?? ""}
          className="sm:col-span-2"
          onSave={(v) => edit({ location: v })}
        />
      </div>

      {bullets && bullets.length > 0 ? (
        <ul className="mt-5 space-y-2 border-t border-ink-900/5 pt-4">
          {bullets.map((b, i) => (
            <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-ink-700">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
              {b}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-5 border-t border-ink-900/5 pt-4 text-xs text-ink-400">
          No bullets found for this role in your saved resume.
        </p>
      )}

      <div className="mt-4 flex justify-end">
        {confirming ? (
          <span className="flex items-center gap-2 text-xs text-ink-500">
            Remove this role from your profile?
            <Button
              size="sm"
              variant="danger"
              onClick={() => void onChange(api.deleteEmployment(job.id))}
            >
              Remove
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
            Remove role
          </Button>
        )}
      </div>
    </Card>
  );
}

function CertificationCard({
  cert,
  onChange,
}: {
  cert: CertificationOut;
  onChange: (call: Promise<ProfileOut>) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const edit = (patch: Parameters<typeof api.updateCertification>[1]) =>
    onChange(api.updateCertification(cert.id, patch));

  return (
    <Card className="p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <EditableField
          label="Certification"
          value={cert.certification}
          required
          bold
          onSave={(v) => edit({ certification: v })}
        />
        <EditableField label="Issued by" value={cert.issuer ?? ""} emptyLabel="Add issuer (optional)" onSave={(v) => edit({ issuer: v })} />
        <EditableField
          label="Issued"
          value={cert.date ?? ""}
          type="date"
          emptyLabel="Add date (optional)"
          format={formatDay}
          onSave={(v) => edit({ date: v })}
        />
        <EditableField
          label="Expires"
          value={cert.expiration ?? ""}
          type="date"
          emptyLabel="No expiry"
          format={formatDay}
          onSave={(v) => edit({ expiration: v })}
        />
      </div>
      <div className="mt-4 flex justify-end">
        {confirming ? (
          <span className="flex items-center gap-2 text-xs text-ink-500">
            Remove this certification from your profile?
            <Button size="sm" variant="danger" onClick={() => void onChange(api.deleteCertification(cert.id))}>
              Remove
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
            Remove certification
          </Button>
        )}
      </div>
    </Card>
  );
}

/** Short list that maps cleanly onto the degree choices employers show. */
const DEGREES = [
  "High School or GED",
  "Some College",
  "Certificate",
  "Associate's Degree",
  "Bachelor's Degree",
  "Master's Degree",
  "MBA",
  "Doctorate",
];

/** The standard degrees, plus a degree saved earlier in other words so it is not lost. */
function degreeOptions(current?: string | null) {
  const list = current && !DEGREES.includes(current) ? [current, ...DEGREES] : DEGREES;
  return list.map((d) => ({ value: d, label: d }));
}

/** Typing suggestions only. Employers' own lists differ, so any text is still allowed. */
const FIELD_OF_STUDY_SUGGESTIONS = [
  "Accounting",
  "Biology",
  "Business Administration",
  "Business Analytics",
  "Business Management",
  "Communications",
  "Computer Science",
  "Data Science",
  "Economics",
  "Education",
  "Engineering",
  "English",
  "Finance",
  "Health Information Management",
  "Healthcare Administration",
  "Information Systems",
  "Management Information Systems",
  "Marketing",
  "Mathematics",
  "Nursing",
  "Political Science",
  "Psychology",
  "Public Health",
  "Sociology",
  "Statistics",
];

function EducationCard({
  edu,
  onChange,
}: {
  edu: EducationOut;
  onChange: (call: Promise<ProfileOut>) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const edit = (patch: Parameters<typeof api.updateEducation>[1]) =>
    onChange(api.updateEducation(edu.id, patch));

  return (
    <Card className="p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <EditableField
          label="School"
          value={edu.institution}
          required
          bold
          onSave={(v) => edit({ institution: v })}
        />
        <SelectField
          label="Degree"
          value={edu.degree ?? ""}
          required
          options={degreeOptions(edu.degree)}
          onSave={(v) => edit({ degree: v })}
        />
        <EditableField
          label="Field of study"
          value={edu.field ?? ""}
          suggestions={FIELD_OF_STUDY_SUGGESTIONS}
          onSave={(v) => edit({ field: v })}
        />
        <EditableField
          label="Year started"
          value={(edu.start_date ?? "").slice(0, 4)}
          type="year"
          emptyLabel="Add year"
          onSave={(v) => edit({ start_date: v })}
        />
        <EditableField
          label="Year graduated (or expected)"
          value={(edu.end_date ?? "").slice(0, 4)}
          type="year"
          emptyLabel="Add year"
          onSave={(v) => edit({ end_date: v })}
        />
        <EditableField label="GPA" value={edu.gpa ?? ""} emptyLabel="Add GPA (optional)" onSave={(v) => edit({ gpa: v })} />
      </div>
      <div className="mt-4 flex justify-end">
        {confirming ? (
          <span className="flex items-center gap-2 text-xs text-ink-500">
            Remove this school from your profile?
            <Button size="sm" variant="danger" onClick={() => void onChange(api.deleteEducation(edu.id))}>
              Remove
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
            Remove school
          </Button>
        )}
      </div>
    </Card>
  );
}

function SkillsCard({
  skills,
  onChange,
}: {
  skills: ProfileOut["skills"];
  onChange: (call: Promise<ProfileOut>) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function add() {
    const name = draft.trim();
    if (!name) return;
    setError(null);
    try {
      await onChange(api.addSkill(name));
      setDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add that skill.");
    }
  }

  return (
    <Card className="p-6">
      <h2 className="mb-4 text-base font-bold text-ink-900">Skills</h2>
      {skills.length === 0 && <p className="mb-3 text-sm text-ink-400">No skills yet. Add your first one below.</p>}
      <div className="mb-4 flex flex-wrap gap-2">
        {skills.map((skill) => (
          <span
            key={skill.id}
            className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 py-1 pl-3 pr-1.5 text-xs font-semibold text-brand-700"
          >
            {skill.canonical_skill}
            <button
              type="button"
              aria-label={`Remove ${skill.canonical_skill}`}
              onClick={() => void onChange(api.deleteSkill(skill.id))}
              className="flex h-5 w-5 items-center justify-center rounded-full text-brand-600 transition hover:bg-brand-100"
            >
              <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" aria-hidden="true">
                <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </span>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a skill"
          className={`${inputClass} max-w-xs`}
        />
        <Button type="submit" size="sm" disabled={!draft.trim()}>
          Add
        </Button>
      </form>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </Card>
  );
}

function ResumeDrop({
  parseMutation,
  hasProfile,
}: {
  parseMutation: UseMutationResult<ResumeParseResponse, ApiError, File>;
  hasProfile: boolean;
}) {
  const masterQuery = useQuery({ queryKey: ["master-status"], queryFn: api.masterStatus });
  const [pending, setPending] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const saved = !!masterQuery.data?.saved;

  function choose(file: File | undefined) {
    if (!file) return;
    // The first upload starts right away. Replacing a saved resume asks first.
    if (saved) {
      setPending(file);
    } else {
      parseMutation.mutate(file);
    }
  }

  const busy = parseMutation.isPending;

  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-bold text-ink-900">Master resume</h2>
        {saved ? (
          <Badge tone="success">
            <CheckIcon className="h-3 w-3" />
            Saved{masterQuery.data?.updated_at ? ` on ${new Date(masterQuery.data.updated_at).toLocaleDateString()}` : ""}
          </Badge>
        ) : (
          <Badge tone="warning">Not saved yet</Badge>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(e.dataTransfer.files?.[0]);
        }}
        className={`mt-4 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed text-center transition ${
          hasProfile ? "px-6 py-5" : "px-6 py-12"
        } ${dragging ? "border-brand-400 bg-brand-50" : "border-brand-200 bg-brand-50/40"}`}
      >
        {busy ? (
          <div className="animate-pulse text-sm font-semibold text-brand-700">
            Reading your resume… this can take a minute.
          </div>
        ) : pending ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-700">
              Replace your saved resume with <span className="font-semibold">{pending.name}</span>?
            </p>
            <div className="flex justify-center gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  parseMutation.mutate(pending);
                  setPending(null);
                }}
              >
                Replace and read it
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setPending(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm font-semibold text-ink-900">
              {hasProfile ? "Drop an updated resume here" : "Drop your resume here"}
            </p>
            <p className="mt-1 max-w-md text-xs text-ink-500">
              Use a Word (.docx) file. It is saved once on this computer and every tailored resume is
              made from it with the same layout. A PDF will build your profile, but tailored resumes
              need the Word file.
            </p>
            <Button
              variant={hasProfile ? "secondary" : "primary"}
              size="sm"
              className="mt-4"
              onClick={() => inputRef.current?.click()}
            >
              Choose a file
            </Button>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          onChange={(e) => {
            choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>

      {parseMutation.isError && <p className="mt-3 text-sm text-red-600">{parseMutation.error.message}</p>}
    </Card>
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
        title="Check what we found"
        description="Correct anything that looks wrong, uncheck any fact you don't want used, then save. You can edit everything later on your profile."
      />

      {data.used_ocr && (
        <div className="mb-4 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
          This file had to be read as an image, so double-check the details below carefully.
        </div>
      )}

      <Card className="mb-6 p-6">
        <h2 className="mb-4 text-base font-bold text-ink-900">Contact information</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <LabeledInput label="Name" value={extraction.contact.name} onChange={(v) => updateContact("name", v)} />
          <LabeledInput label="Email" value={extraction.contact.email ?? ""} onChange={(v) => updateContact("email", v)} />
          <LabeledInput label="Phone" value={extraction.contact.phone ?? ""} onChange={(v) => updateContact("phone", v)} />
          <LabeledInput
            label="Location"
            value={extraction.contact.location ?? ""}
            onChange={(v) => updateContact("location", v)}
          />
        </div>
      </Card>

      <Card className="mb-6 p-6">
        <h2 className="text-base font-bold text-ink-900">Facts from your resume ({data.draft_claims.length})</h2>
        <p className="mb-3 mt-1 text-xs text-ink-500">
          Short statements the app can rely on later. Uncheck anything inaccurate or that you'd rather
          not use.
        </p>
        <ul className="divide-y divide-ink-900/5">
          {data.draft_claims.map((claim, i) => (
            <ClaimRow
              key={i}
              claim={claim}
              approved={approved[i]}
              onToggle={() => setApproved((prev) => prev.map((v, j) => (j === i ? !v : v)))}
            />
          ))}
        </ul>
      </Card>

      <div className="flex gap-3">
        <Button variant="primary" onClick={() => commitMutation.mutate()} disabled={commitMutation.isPending}>
          {commitMutation.isPending ? "Saving…" : "Save profile"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
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
      <span className="mb-1 block text-xs font-semibold text-ink-500">{label}</span>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} className={inputClass} />
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
      <input type="checkbox" checked={approved} onChange={onToggle} className="mt-1 h-4 w-4 accent-brand-500" />
      <div>
        <div className={`text-sm ${approved ? "text-ink-900" : "text-ink-400 line-through"}`}>
          {claim.canonical_text}
        </div>
        <div className="text-xs text-ink-400">From your resume: "{claim.source_text}"</div>
      </div>
    </li>
  );
}
