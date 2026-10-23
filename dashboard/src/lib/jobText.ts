/** Small helpers for showing a job's posted date and pay the same way on every page. */

const DAY_MS = 86_400_000;

/** A calendar day from "2026-10-02" or a full timestamp, read as a day on the viewer's own calendar. Null when it is not a date. */
function dayOf(value?: string | null): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  if (!m) return null;
  const hasTime = (value ?? "").length > 10;
  const d = hasTime ? new Date(value as string) : new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? null : new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** "Sep 22" for this year, "Sep 22, 2025" for another year. */
export function shortDate(d: Date, now: Date = new Date()): string {
  const base = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return d.getFullYear() === now.getFullYear() ? base : `${base}, ${d.getFullYear()}`;
}

/**
 * The one way every page writes a date: "Today", "Yesterday", "8 days ago" for the last 30 days, then a short date ("Sep 22").
 * Null when the value is not a date.
 */
export function formatPosted(date?: string | null, now: Date = new Date()): string | null {
  const d = dayOf(date);
  if (!d) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today.getTime() - d.getTime()) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return shortDate(d, now);
}

/** For detail views, both ways: "8 days ago (Oct 15)". Dates older than 30 days are just the short date. */
export function formatPostedBoth(date?: string | null, now: Date = new Date()): string | null {
  const rel = formatPosted(date, now);
  const d = dayOf(date);
  if (!rel || !d) return rel;
  return /ago$|^Yesterday$|^Today$/.test(rel) ? `${rel} (${shortDate(d, now)})` : rel;
}

/** Whole days since a posting date, or null when unknown. */
export function postedDaysAgo(date?: string | null, now: Date = new Date()): number | null {
  const d = dayOf(date);
  if (!d) return null;
  return Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - d.getTime()) / DAY_MS);
}

/** Postings this old may have been filled. */
export const MAY_BE_CLOSED_AFTER_DAYS = 60;
export const mayBeClosed = (date?: string | null, now: Date = new Date()): boolean => (postedDaysAgo(date, now) ?? 0) > MAY_BE_CLOSED_AFTER_DAYS;

const HOURS_PER_YEAR = 2080;

/** "$92.7K", "$150K", "$950" for a yearly amount. */
function compactMoney(n: number): string {
  if (n >= 1000) return `$${(Math.round(n / 100) / 10).toString().replace(/\.0$/, "")}K`;
  return `$${Math.round(n)}`;
}

/**
 * The one way every page writes pay: "$92.7K to $148.4K / yr". Hourly pay is turned into a yearly figure (2,080 hours), cents and
 * notes such as "Offers Equity" are dropped, and no dash is ever used. Null when the text has no dollar amount.
 */
export function formatPayText(text?: string | null): string | null {
  const t = (text ?? "").replace(/[\u2013\u2014]/g, "-");
  const amounts: number[] = [];
  const re = /\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?|(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*([kK])\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(t)) && amounts.length < 2) {
    const n = Number((m[1] ?? m[3]).replace(/,/g, ""));
    const k = m[2] ?? m[4];
    if (Number.isFinite(n) && n > 0) amounts.push(k ? n * 1000 : n);
  }
  if (amounts.length === 0) return null;
  const hourly = /(?:\/\s*h(?:ou)?r|per\s+hour|an\s+hour|hourly)/i.test(t) || Math.max(...amounts) < 1000;
  const yearly = hourly ? amounts.map((a) => a * HOURS_PER_YEAR) : amounts;
  const [lo, hi] = [Math.min(...yearly), Math.max(...yearly)];
  return lo === hi ? `${compactMoney(lo)} / yr` : `${compactMoney(lo)} to ${compactMoney(hi)} / yr`;
}

/** The pay range as the posting wrote it, or built from the saved numbers, in the one pay style. Null when there is none. */
export function formatSalary(salary?: Record<string, unknown> | null): string | null {
  if (!salary) return null;
  if (typeof salary.text === "string" && salary.text.trim()) {
    return formatPayText(salary.text) ?? salary.text.trim().replace(/[\u2013\u2014]/g, " to ");
  }
  const min = typeof salary.min === "number" ? salary.min : null;
  const max = typeof salary.max === "number" ? salary.max : null;
  if (min === null && max === null) return null;
  // Older saved jobs may say "hour" for a yearly range; real hourly pay is never in the thousands.
  const hourly = salary.period === "hour" && (max ?? min ?? 0) < 1000;
  const money = (n: number) => String(hourly ? n * HOURS_PER_YEAR : n);
  return formatPayText(min !== null && max !== null ? `$${money(min)} - $${money(max)}` : `$${money((min ?? max) as number)}`);
}

/** The location without placeholder words such as "Not specified". Null when nothing real is left. */
export function formatLocation(location?: string | null): string | null {
  const parts = (location ?? "")
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p && !/^(not specified|n\/a|none|unknown)$/i.test(p));
  return parts.length ? parts.join(", ") : null;
}

/** What makes two saved jobs the same posting: employer, title and place, ignoring case and punctuation. */
export function duplicateKey(j: { company: string; title: string; location?: string | null }): string {
  const squash = (t?: string | null) => (t ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  return `${squash(j.company)}|${squash(j.title)}|${squash(j.location)}`;
}
