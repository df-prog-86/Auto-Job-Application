/**
 * Pure rules for deciding what a form field is and what value it should get.
 * No DOM access here, so every rule can be unit tested on its own.
 */

import type { ApplyContext } from "@/form-engine/types";

export type CanonicalKey =
  | "first_name"
  | "preferred_name"
  | "recent_title"
  | "recent_employer"
  | "phone_country"
  | "last_name"
  | "full_name"
  | "email"
  | "phone"
  | "location"
  | "city"
  | "address_line1"
  | "postal_code"
  | "phone_device_type"
  | "state"
  | "linkedin"
  | "resume"
  | "work_authorization"
  | "sponsorship"
  | "security_clearance"
  | "background_check"
  | "criminal_check"
  | "drug_screen"
  | "age_18"
  | "years_experience"
  | "highest_education"
  | "relocation"
  | "desired_salary"
  | "start_availability";

export type VoluntaryTopic = "gender" | "race" | "hispanic" | "veteran" | "other";

export type Classification =
  | { kind: "canonical"; key: CanonicalKey }
  | { kind: "voluntary"; topic: VoluntaryTopic }
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
  /\b(gender|race|ethnic\w*|hispanic|latino|latinx|veteran|disabilit\w*|sexual orientation|lgbt\w*|transgender|self[- ]identif\w*|protected class|pronouns?)\b/i;

function voluntaryTopic(label: string): VoluntaryTopic {
  if (/transgender|sexual orientation|lgbt|pronoun|disabilit|protected class/.test(label)) return "other";
  if (/\bveteran\b/.test(label)) return "veteran";
  if (/\brace\b/.test(label)) return "race";
  if (/hispanic|latino|latinx/.test(label)) return "hispanic";
  if (/ethnic/.test(label)) return "race";
  if (/\bgender\b/.test(label)) return "gender";
  return "other";
}

export function classifyField(sig: FieldSignature): Classification {
  const label = sig.label.toLowerCase();
  const attrs = `${sig.name} ${sig.id}`.toLowerCase();
  const text = `${label} ${attrs}`;

  if (VOLUNTARY.test(label)) return { kind: "voluntary", topic: voluntaryTopic(label) };

  switch (sig.autocomplete) {
    case "given-name":
      return { kind: "canonical", key: "first_name" };
    case "family-name":
      return { kind: "canonical", key: "last_name" };
    case "name":
      return { kind: "canonical", key: "full_name" };
    case "email":
      return { kind: "canonical", key: "email" };
    case "address-line1":
      return { kind: "canonical", key: "address_line1" };
    case "postal-code":
      return { kind: "canonical", key: "postal_code" };
    case "tel-country-code":
      return { kind: "canonical", key: "phone_country" };
    case "nickname":
      return { kind: "canonical", key: "preferred_name" };
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
  // "Are you willing to ..." questions the person has answered once on their Profile.
  // Questions about history ("ever failed", "convicted") are never matched here.
  const willing = /\b(willing|able|agree)\b/.test(label) && !/\b(ever|failed|convicted|positive|refused|arrest\w*|charged)\b/.test(label);
  if (willing && /drug (screen|test)|drug and alcohol|substance (screen|test)/.test(label)) return { kind: "canonical", key: "drug_screen" };
  if (willing && /criminal (record|background|history)? ?check|criminal record/.test(label)) return { kind: "canonical", key: "criminal_check" };
  if (willing && /background (check|investigation|screening)/.test(label)) return { kind: "canonical", key: "background_check" };
  // Preferences the person saved once on their Profile. Never matched on a date picker.
  if (/\brelocat/.test(label) && !/assistance|reimburs|package|stipend|bonus|cost/.test(label)) {
    return { kind: "canonical", key: "relocation" };
  }
  if (
    /(desired|expected|target|required|preferred|minimum|anticipated)\s+(annual\s+|base\s+|yearly\s+)?(salary|compensation|pay)|salary\s+(range|expectations?|requirements?|desired)|compensation\s+expectations?|pay\s+expectations?/.test(label)
  ) {
    return { kind: "canonical", key: "desired_salary" };
  }
  if (
    sig.inputType !== "date" &&
    /available to start|availability to start|when (would|can|are|will) you (be )?(available|start|able to start)|earliest (possible )?(start )?date|date available|when can you start/.test(label)
  ) {
    return { kind: "canonical", key: "start_availability" };
  }
  // Total years of work, only when the question is about the whole field, not one tool ("years of SQL").
  if (
    /years of (\w+ ){0,2}experience|experience.{0,30}\byears\b|how many years/.test(label) &&
    /in the field|in this field|in your field|in the industry|total|overall|professional|relevant|work experience|applying/.test(label) &&
    !/\b(with|using|managing|supervis\w*|leading|manag\w*|of experience (with|in) [a-z]{3,} (?!field))/.test(label.replace(/in the field|in this field|in your field|in the industry/g, ""))
  ) {
    return { kind: "canonical", key: "years_experience" };
  }
  if (/highest (level of )?(education|degree)|highest education|level of education (completed|attained)/.test(label)) {
    return { kind: "canonical", key: "highest_education" };
  }
  if (/(?:\b18\b|eighteen)[^?]{0,20}(years|yrs|age|older|over)|at least (18|eighteen)|over (the age of )?(18|eighteen)/.test(label) && !/\b(ever|convicted)\b/.test(label)) {
    return { kind: "canonical", key: "age_18" };
  }
  if (/security clearance|\bclearance\b/.test(label)) return { kind: "canonical", key: "security_clearance" };
  if (
    /(authori[sz]ed|eligible|legally|right|permitted|able) to work|work authori[sz]ation|employment eligibility/.test(label)
  ) {
    return { kind: "canonical", key: "work_authorization" };
  }

  if (/^\s*(street )?address( line)?( 1| one)?\s*\*?\s*$/.test(label) && !/\b(2|two)\b/.test(label)) return { kind: "canonical", key: "address_line1" };
  if (/^\s*(zip|postal)([ /]*(zip|postal))?( code)?\s*\*?\s*$/.test(label)) return { kind: "canonical", key: "postal_code" };
  if (/phone (device )?type|type of phone/.test(label)) return { kind: "canonical", key: "phone_device_type" };
  if (/^\s*city\s*\*?\s*$/.test(label)) return { kind: "canonical", key: "city" };
  if (/^\s*state(\s*\/\s*province)?\s*\*?\s*$/.test(label)) return { kind: "canonical", key: "state" };

  if (/linkedin/.test(text)) return { kind: "canonical", key: "linkedin" };
  if (/most recent (job )?title|current (job )?title|current position|present title/.test(label)) {
    return { kind: "canonical", key: "recent_title" };
  }
  if (/most recent (employer|company)|current (employer|company)|present employer/.test(label)) {
    return { kind: "canonical", key: "recent_employer" };
  }
  if (/preferred (first )?name|nickname|goes by|what should we call you|what name do you go by/.test(label)) {
    return { kind: "canonical", key: "preferred_name" };
  }
  if (
    /country (calling )?code|phone country|mobile country|dial(l?ing)? code|country dial/.test(label) ||
    (/\bcountry\b/.test(label) && /\b(phone|mobile|cell|tel)\b/.test(label))
  ) {
    return { kind: "canonical", key: "phone_country" };
  }
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

/** Months since year 0 for "YYYY-MM" or "YYYY-MM-DD"; null when unreadable. */
function monthIndex(d?: string | null): number | null {
  const m = /^(\d{4})-(\d{2})/.exec(d ?? "");
  return m ? Number(m[1]) * 12 + Number(m[2]) - 1 : null;
}

/** Years of work, with overlapping roles counted once. Null if no role has a readable start. */
export function totalYears(ctx: ApplyContext, now: Date = new Date()): number | null {
  const nowIdx = now.getFullYear() * 12 + now.getMonth();
  const spans: [number, number][] = [];
  for (const e of ctx.experience ?? []) {
    const start = monthIndex(e.start_date);
    if (start === null) continue;
    const end = e.current || !e.end_date ? nowIdx : (monthIndex(e.end_date) ?? nowIdx);
    if (end >= start) spans.push([start, end]);
  }
  if (spans.length === 0) return null;
  spans.sort((a, b) => a[0] - b[0]);
  let months = 0;
  let [curS, curE] = spans[0];
  for (const [s, e] of spans.slice(1)) {
    if (s <= curE) curE = Math.max(curE, e);
    else {
      months += curE - curS;
      [curS, curE] = [s, e];
    }
  }
  months += curE - curS;
  return months / 12;
}

/** Picks the one range ("1-3 years", "10+ years", "Less than 1 year") that holds the value; none if it is on a boundary. */
export function yearsBucket(years: number | null, options: string[]): string | null {
  if (years === null) return null;
  const hits = options.filter((o) => {
    const t = o.toLowerCase();
    if (/^select/.test(t)) return false;
    let m: RegExpExecArray | null;
    if (/\bno experience\b|^none$/.test(t)) return years === 0;
    if ((m = /less than (\d+)/.exec(t))) return years > 0 && years < Number(m[1]);
    if ((m = /(\d+)\s*(?:\+|or more|and (?:above|over))/.exec(t))) return years > Number(m[1]);
    if ((m = /(\d+)\s*(?:-|to|–)\s*(\d+)/.exec(t))) return years > Number(m[1]) && years < Number(m[2]);
    return false;
  });
  return hits.length === 1 ? hits[0] : null;
}

const DEGREE_RANK: [RegExp, number][] = [
  [/doctor|ph\.?\s?d|\bj\.?d\b|\bm\.?d\b/i, 5],
  [/master|\bmba\b|\bm\.?\s?[as]\b|\bm\.?sc?\b/i, 4],
  [/bachelor|\bb\.?\s?[as]\b|\bb\.?sc?\b/i, 3],
  [/associate|\ba\.?\s?[as]\b/i, 2],
  [/certificate/i, 1],
  [/high school|\bged\b|secondary/i, 0],
];

/** The highest finished degree in the profile (a graduation date still in the future does not count). */
export function highestDegree(ctx: ApplyContext, now: Date = new Date()): number | null {
  const nowIdx = now.getFullYear() * 12 + now.getMonth();
  let best: number | null = null;
  for (const e of ctx.education ?? []) {
    const end = monthIndex(e.end_date);
    if (end !== null && end > nowIdx) continue;
    const hit = DEGREE_RANK.find(([re]) => re.test(e.degree ?? ""));
    if (hit && (best === null || hit[1] > best)) best = hit[1];
  }
  return best;
}

export function educationChoice(rank: number | null, options: string[]): string | null {
  if (rank === null) return null;
  const word: Record<number, RegExp> = {
    5: /doctor|ph\.?d/i,
    4: /master/i,
    3: /bachelor/i,
    2: /associate/i,
    1: /certificate/i,
    0: /high school|\bged\b|secondary/i,
  };
  const hits = options.filter((o) => word[rank].test(o));
  return hits.length === 1 ? hits[0] : null;
}

const US_STATES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut",
  DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois",
  IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana",
  NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania",
  RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
  VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};

/**
 * "Boston, MA" -> what to type ("Boston") and the full entries a place list
 * would show ("Boston, Massachusetts, United States"). Anything that is not
 * "City, <US state code>" gets no help and is matched as written.
 */
export function expandLocation(loc: string): { typeText: string; alternates: string[] } | null {
  const m = /^\s*([^,]+?)\s*,\s*([A-Za-z]{2})\s*(?:,\s*(?:USA?|United States))?\s*$/.exec(loc);
  const state = m ? US_STATES[m[2].toUpperCase()] : undefined;
  if (!m || !state) return null;
  return { typeText: m[1], alternates: [`${m[1]}, ${state}, United States`, `${m[1]}, ${state}`] };
}

/** "United States (+1)" -> "United States" (used to narrow a long country list). */
export function phoneCountryName(saved: unknown): string | null {
  return typeof saved === "string" && saved.trim() ? saved.replace(/\(.*\)/, "").trim() : null;
}

/**
 * The saved phone country looks like "United States (+1)". A plain text box
 * gets the dial code; a list gets the matching entry, or nothing when the
 * list is ambiguous (several +1 countries and no name match).
 */
export function resolvePhoneCountry(saved: unknown, options: string[]): string | null {
  if (typeof saved !== "string" || !saved.trim()) return null;
  const dial = /\+(\d+)/.exec(saved)?.[1];
  const name = saved.replace(/\(.*\)/, "").trim().toLowerCase();
  if (options.length === 0) return dial ? `+${dial}` : null;

  const dialPattern = dial ? new RegExp(`\\+${dial}(?!\\d)`) : null;
  let hits = options.filter((o) => o.toLowerCase().includes(name));
  if (hits.length > 1 && dialPattern) {
    const narrowed = hits.filter((o) => dialPattern.test(o));
    if (narrowed.length > 0) hits = narrowed;
  }
  if (hits.length > 1) {
    const exact = hits.filter((o) => o.toLowerCase().replace(/\(.*?\)|\+\d+/g, "").trim() === name);
    if (exact.length === 1) hits = exact;
  }
  return hits.length === 1 ? hits[0] : null;
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
    case "preferred_name":
      return c.preferred_name?.trim() || c.first_name || null;
    case "recent_title":
      return c.recent_title?.trim() || null;
    case "recent_employer":
      return c.recent_employer?.trim() || null;
    case "phone_country":
      return resolvePhoneCountry(ctx.answers["phone_country"], options);
    case "last_name":
      return c.last_name || null;
    case "full_name":
      return c.full_name || null;
    case "email":
      return c.email || null;
    case "phone":
      return c.phone || null;
    case "address_line1": {
      const v = ctx.answers["address_line1"];
      return typeof v === "string" && v.trim() ? v.trim() : null;
    }
    case "postal_code": {
      const v = ctx.answers["postal_code"];
      return typeof v === "string" && v.trim() ? v.trim() : null;
    }
    case "phone_device_type": {
      const v = ctx.answers["phone_device_type"];
      if (typeof v !== "string" || !v.trim()) return null;
      if (options.length === 0) return v.trim();
      const hits = options.filter((o) => o.trim().toLowerCase() === v.trim().toLowerCase());
      return hits.length === 1 ? hits[0] : null;
    }
    case "city": {
      const m = /^\s*([^,]+?)\s*,\s*[A-Za-z]{2}\b/.exec(c.location ?? "");
      return m ? m[1] : null;
    }
    case "state": {
      const m = /,\s*([A-Za-z]{2})\b/.exec(c.location ?? "");
      const name = m ? US_STATES[m[1].toUpperCase()] : undefined;
      if (!name) return null;
      if (options.length === 0) return name;
      const hits = options.filter((o) => o.trim().toLowerCase() === name.toLowerCase());
      return hits.length === 1 ? hits[0] : null;
    }
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
    case "background_check":
    case "criminal_check":
    case "drug_screen":
    case "age_18": {
      const saved = ctx.answers[{ background_check: "background_check_ok", criminal_check: "criminal_check_ok", drug_screen: "drug_screen_ok", age_18: "age_18_plus" }[key]];
      if (typeof saved !== "boolean") return null; // never guessed
      if (options.length === 0) return saved ? "Yes" : "No";
      return yesNo(options, saved);
    }
    case "relocation": {
      const saved = ctx.answers["relocation_ok"];
      if (typeof saved !== "boolean") return null; // never guessed
      if (options.length === 0) return saved ? "Yes" : "No";
      return yesNo(options, saved);
    }
    case "desired_salary": {
      const v = ctx.answers["desired_salary"];
      if (typeof v !== "string" || !v.trim()) return null;
      if (options.length === 0) return v.trim();
      return options.find((o) => normalizeQuestion(o) === normalizeQuestion(v)) ?? null;
    }
    case "start_availability": {
      const v = ctx.answers["available_to_start"];
      if (typeof v !== "string" || !v.trim()) return null;
      if (options.length === 0) return v.trim();
      return options.find((o) => normalizeQuestion(o) === normalizeQuestion(v)) ?? null;
    }
    case "years_experience":
      return yearsBucket(totalYears(ctx), options);
    case "highest_education":
      return educationChoice(highestDegree(ctx), options);
    case "security_clearance": {
      const level = ctx.answers["security_clearance"];
      if (typeof level !== "string" || !level) return null;
      if (options.length === 0) return level === "None" ? "No" : "Yes";
      if (isYesNoOptions(options)) return yesNo(options, level !== "None");
      return options.find((o) => normalizeQuestion(o) === normalizeQuestion(level)) ?? null;
    }
  }
}

const DECLINE = /decline|prefer not|do not wish|don't wish|choose not|not to (say|answer|disclose)/i;

function only(options: string[], test: RegExp): string | null {
  const hits = options.filter((o) => test.test(o));
  return hits.length === 1 ? hits[0] : null;
}

/**
 * The choice on a voluntary self-identification question that matches what the
 * person saved on their Profile, or null when nothing was saved, they chose to
 * skip it, or the form's wording does not clearly match (never guessed).
 * Saved codes: gender male|female|decline; race hispanic|white|black|pacific|
 * asian|native|two_or_more|decline; veteran protected|not_protected|decline.
 */
export function resolveVoluntary(topic: VoluntaryTopic, answers: Record<string, unknown>, options: string[]): string | null {
  if (options.length === 0) return null;
  const saved = (key: string) => {
    const v = answers[key];
    return typeof v === "string" && v && v !== "skip" ? v : null;
  };
  const race = saved("eeo_race");

  if (topic === "gender") {
    const g = saved("eeo_gender");
    if (!g) return null;
    if (g === "decline") return only(options, DECLINE);
    return only(options, g === "male" ? /^(male|man)$/i : /^(female|woman)$/i);
  }
  if (topic === "veteran") {
    const v = saved("eeo_veteran");
    if (!v) return null;
    if (v === "decline") return only(options, DECLINE);
    // "Not a veteran" and "a veteran who is not protected" are different answers; a form that mixes them
    // is only answered when exactly one choice fits.
    if (v === "not_veteran") {
      return only(options, /\b(am|is) not an? veteran\b|\bnon-?veteran\b|^not an? veteran\b/i) ?? only(options, /not an? protected veteran/i);
    }
    if (v === "not_protected") {
      return only(options, /(just|but|yet) not an? protected veteran/i) ?? only(options, /^(?!.*\bnot an? veteran\b).*not an? protected veteran/i);
    }
    return only(options, /identify as one or more|\b(am|is) a (protected )?veteran\b|^yes\b/i);
  }
  if (topic === "hispanic") {
    if (!race) return null;
    if (race === "decline") return only(options, DECLINE);
    return yesNo(options, race === "hispanic");
  }
  if (topic === "race") {
    if (!race) return null;
    if (race === "decline") return only(options, DECLINE);
    const patterns: Record<string, RegExp> = {
      hispanic: /^hispanic|^latino/i,
      white: /^white/i,
      black: /black|african american/i,
      pacific: /pacific|hawaiian/i,
      asian: /^asian/i,
      native: /american indian|alaska/i,
      two_or_more: /two or more|multiracial|more than one/i,
    };
    const pattern = patterns[race];
    return pattern ? only(options, pattern) : null;
  }
  return null;
}

/** The candidate's own saved answer for this exact question, if they gave one. */
export function learnedAnswer(label: string, ctx: ApplyContext, options: string[]): string | null {
  const text = ctx.learned_answers[normalizeQuestion(label)];
  if (!text) return null;
  if (options.length === 0) return text;
  const wanted = normalizeQuestion(text);
  return options.find((o) => normalizeQuestion(o) === wanted) ?? null;
}
