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
export function missingItems(profile: ProfileOut | undefined, answers: AnswerOut[] | undefined, autofillFields = true): string[] {
  if (!profile) return ["Upload your resume"];
  const missing: string[] = [];
  if (!filled(profile.name)) missing.push("Name");
  if (!filled(profile.email)) missing.push("Email");
  if (!filled(profile.phone)) missing.push("Phone");
  if (!filled(answerValue(answers, "phone_country"))) missing.push("Phone country code");
  if (!filled(profile.location)) missing.push("Location");
  if (!filled(answerValue(answers, "work_authorization"))) missing.push("Work authorization");
  if (!filled(answerValue(answers, "sponsorship_required"))) missing.push("Sponsorship answer");
  // The answers autofill reads for eligibility and screening questions. Left out of the get-started checklist (autofillFields = false),
  // which only asks for the essentials, so an existing profile never drops back to "Get started" on this account.
  if (autofillFields) {
    if (!filled(answerValue(answers, "age_18_plus"))) missing.push("Age 18 or older");
    if (!filled(answerValue(answers, "background_check_ok"))) missing.push("Background check answer");
    if (!filled(answerValue(answers, "criminal_check_ok"))) missing.push("Criminal record check answer");
    if (!filled(answerValue(answers, "drug_screen_ok"))) missing.push("Drug screen answer");
    if (!filled(answerValue(answers, "desired_salary"))) missing.push("Desired salary");
    if (!filled(answerValue(answers, "available_to_start"))) missing.push("Start date");
  }
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
    if (autofillFields && !filled(edu.degree_short)) missing.push(`${filled(edu.institution) ? edu.institution.trim() : `School ${i + 1}`} degree abbreviation`);
  });
  return missing;
}

/** How much of the profile is filled in, 0 to 100, from the same checks as missingItems. */
export function profilePercent(profile: ProfileOut | undefined, answers: AnswerOut[] | undefined): number {
  if (!profile) return 0;
  const total = 8 + 6 + 3 * profile.employment_history.length + 1 + 3 * profile.education.length;
  const missing = missingItems(profile, answers).length;
  return Math.max(0, Math.min(100, Math.round(100 * (1 - missing / total))));
}
