/** Small helpers for showing a job's posted date and pay the same way on every page. */

/** "Oct 2, 2026" for a plain date such as "2026-10-02" (read as a calendar day, not shifted by time zone). */
export function formatPosted(date?: string | null): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? "");
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** The pay range as the posting wrote it, or built from the saved numbers. Null when there is none. */
export function formatSalary(salary?: Record<string, unknown> | null): string | null {
  if (!salary) return null;
  if (typeof salary.text === "string" && salary.text.trim()) return salary.text.trim();
  const min = typeof salary.min === "number" ? salary.min : null;
  const max = typeof salary.max === "number" ? salary.max : null;
  if (min === null && max === null) return null;
  const hourly = salary.period === "hour";
  const money = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  const range = min !== null && max !== null ? `${money(min)} - ${money(max)}` : money((min ?? max) as number);
  return hourly ? `${range} per hour` : range;
}
