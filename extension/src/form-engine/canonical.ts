/**
 * Pure rules for deciding what a form field is and what value it should get.
 * No DOM access here, so every rule can be unit tested on its own.
 */

import type { ApplyContext } from "@/form-engine/types";

export type CanonicalKey =
  | "first_name"
  | "last_name"
  | "full_name"
  | "email"
  | "phone"
  | "location"
  | "linkedin"
  | "resume"
  | "work_authorization"
  | "sponsorship"
  | "security_clearance";

export type Classification =
  | { kind: "canonical"; key: CanonicalKey }
  | { kind: "voluntary" }
  | { kind: "unknown" };

export interface FieldSignature {
  label: string;
  name: string;
  id: string;
  autocomplete: string;
  inputType: string;
}

/**
 * Must stay identical to normalize_question in
 * backend/app/services/apply/questions.py.
 */
export function normalizeQuestion(label: string): string {
  const text = label.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return text.replace(/\s+(required|optional)$/, "").trim();
}

/** Voluntary self-identification (EEO) questions are never filled automatically. */
const VOLUNTARY =
  /\b(gender|race|ethnic\w*|hispanic|latino|latinx|veteran|disabilit\w*|sexual orientation|lgbt\w*|transgender|self[- ]identif\w*|protected class)\b/i;

export function classifyField(sig: FieldSignature): Classification {
  const label = sig.label.toLowerCase();
  const attrs = `${sig.name} ${sig.id}`.toLowerCase();
  const text = `${label} ${attrs}`;

  if (VOLUNTARY.test(label)) return { kind: "voluntary" };

  switch (sig.autocomplete) {
    case "given-name":
      return { kind: "canonical", key: "first_name" };
    case "family-name":
      return { kind: "canonical", key: "last_name" };
    case "name":
      return { kind: "canonical", key: "full_name" };
    case "email":
      return { kind: "canonical", key: "email" };
    case "tel":
    case "tel-national":
      return { kind: "canonical", key: "phone" };
    default:
      break;
  }

  if (sig.inputType === "file") {
    if (/resume|\bcv\b|curriculum/.test(text) && !/cover/.test(text)) return { kind: "canonical", key: "resume" };
    return { kind: "unknown" };
  }

  if (sig.inputType === "email" || /e-?mail/.test(label)) return { kind: "canonical", key: "email" };

  // Questions come before plain name/phone rules: "sponsorship" and
  // "authorized to work" must never be mistaken for a name or phone field.
  if (/sponsor/.test(label)) return { kind: "canonical", key: "sponsorship" };
  if (/security clearance|\bclearance\b/.test(label)) return { kind: "canonical", key: "security_clearance" };
  if (
    /(authori[sz]ed|eligible|legally|right|permitted|able) to work|work authori[sz]ation|employment eligibility/.test(label)
  ) {
    return { kind: "canonical", key: "work_authorization" };
  }

  if (/linkedin/.test(text)) return { kind: "canonical", key: "linkedin" };
  if (/^(legal |your )?first( name)?$|^given name$|^first_name$/.test(label.trim()) || /\bfirst_name\b/.test(attrs)) {
    return { kind: "canonical", key: "first_name" };
  }
  if (/^(legal |your )?(last|family)( name)?$|^surname$|^last_name$/.test(label.trim()) || /\blast_name\b/.test(attrs)) {
    return { kind: "canonical", key: "last_name" };
  }
  if (/^(your |legal |candidate )?(full )?name$/.test(label.trim())) return { kind: "canonical", key: "full_name" };
  if (
    (sig.inputType === "tel" || /\b(phone|mobile|cell)\b/.test(label)) &&
    !/type|country|code|extension|device/.test(label)
  ) {
    return { kind: "canonical", key: "phone" };
  }
  if (/^(current |your )?(location|city)( \(city\))?$|where are you (located|based)|current location/.test(label.trim())) {
    return { kind: "canonical", key: "location" };
  }

  return { kind: "unknown" };
}

const AUTHORIZED_STATUSES = new Set([
  "US citizen",
  "Permanent resident (green card)",
  "Work visa (such as H-1B or OPT)",
]);

function yesNo(options: string[], wantYes: boolean): string | null {
  const want = wantYes ? "yes" : "no";
  const hit = options.find((o) => normalizeQuestion(o) === want) ?? options.find((o) => normalizeQuestion(o).startsWith(`${want} `));
  return hit ?? null;
}

function isYesNoOptions(options: string[]): boolean {
  return options.some((o) => ["yes", "no"].includes(normalizeQuestion(o)));
}

/**
 * The value for a recognized question, or null when we must NOT guess
 * (the field is then left blank and flagged). `options` is the list of
 * choices for dropdowns and radio groups, empty for free text.
 */
export function resolveValue(
  key: CanonicalKey,
  ctx: ApplyContext,
  options: string[],
): string | null {
  const c = ctx.candidate;
  switch (key) {
    case "first_name":
      return c.first_name || null;
    case "last_name":
      return c.last_name || null;
    case "full_name":
      return c.full_name || null;
    case "email":
      return c.email || null;
    case "phone":
      return c.phone || null;
    case "location":
      return c.location || null;
    case "linkedin":
      return c.linkedin_url || null;
    case "resume":
      return null; // handled as a file upload
    case "sponsorship": {
      const needs = ctx.answers["sponsorship_required"];
      if (typeof needs !== "boolean") return null;
      if (options.length === 0) return needs ? "Yes" : "No";
      return yesNo(options, needs);
    }
    case "work_authorization": {
      const status = ctx.answers["work_authorization"];
      if (typeof status !== "string" || !status) return null;
      if (options.length === 0 || isYesNoOptions(options)) {
        if (!AUTHORIZED_STATUSES.has(status)) return null; // "Other" is never guessed
        return options.length === 0 ? "Yes" : yesNo(options, true);
      }
      // The question asks for the status itself, not yes or no.
      const patterns: Record<string, RegExp> = {
        "US citizen": /citizen/i,
        "Permanent resident (green card)": /green card|permanent resident/i,
        "Work visa (such as H-1B or OPT)": /visa|h-?1b|\bopt\b/i,
      };
      const pattern = patterns[status];
      return (pattern && options.find((o) => pattern.test(o))) || null;
    }
    case "security_clearance": {
      const level = ctx.answers["security_clearance"];
      if (typeof level !== "string" || !level) return null;
      if (options.length === 0) return level === "None" ? "No" : "Yes";
      if (isYesNoOptions(options)) return yesNo(options, level !== "None");
      return options.find((o) => normalizeQuestion(o) === normalizeQuestion(level)) ?? null;
    }
  }
}

/** The candidate's own saved answer for this exact question, if they gave one. */
export function learnedAnswer(label: string, ctx: ApplyContext, options: string[]): string | null {
  const text = ctx.learned_answers[normalizeQuestion(label)];
  if (!text) return null;
  if (options.length === 0) return text;
  const wanted = normalizeQuestion(text);
  return options.find((o) => normalizeQuestion(o) === wanted) ?? null;
}
