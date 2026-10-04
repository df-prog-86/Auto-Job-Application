import type { AnswerOut, ProfileOut } from "@/types/api";

/** The three work eligibility answers stored in the candidate answer library. */
export const ELIGIBILITY_KEYS = ["work_authorization", "sponsorship_required", "security_clearance", "phone_country", "phone_device_type", "address_line1", "postal_code", "eeo_gender", "eeo_race", "eeo_veteran"] as const;

export function answerValue(answers: AnswerOut[] | undefined, key: string): unknown {
  return answers?.find((a) => a.answer_key === key)?.value;
}

const filled = (v: unknown) => v !== null && v !== undefined && String(v).trim() !== "";

/**
 * Everything the profile still needs. A profile counts as complete when this
 * list is empty. Security clearance and LinkedIn are optional.
 */
export function missingItems(profile: ProfileOut | undefined, answers: AnswerOut[] | undefined): string[] {
  if (!profile) return ["Upload your resume"];
  const missing: string[] = [];
  if (!filled(profile.name)) missing.push("Name");
  if (!filled(profile.email)) missing.push("Email");
  if (!filled(profile.phone)) missing.push("Phone");
  if (!filled(answerValue(answers, "phone_country"))) missing.push("Phone country code");
  if (!filled(profile.location)) missing.push("Location");
  if (!filled(answerValue(answers, "work_authorization"))) missing.push("Work authorization");
  if (!filled(answerValue(answers, "sponsorship_required"))) missing.push("Sponsorship answer");
  if (profile.employment_history.length === 0) missing.push("At least one role");
  profile.employment_history.forEach((job, i) => {
    if (!filled(job.title)) missing.push(`Role ${i + 1} title`);
    if (!filled(job.employer)) missing.push(`Role ${i + 1} company`);
    if (!filled(job.start_date)) missing.push(`Role ${i + 1} start date`);
  });
  if (profile.education.length === 0) missing.push("At least one school");
  profile.education.forEach((edu, i) => {
    if (!filled(edu.institution)) missing.push(`School ${i + 1} name`);
    if (!filled(edu.degree)) missing.push(`School ${i + 1} degree`);
  });
  return missing;
}
