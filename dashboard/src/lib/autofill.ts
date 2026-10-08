/**
 * Sites the browser extension can open and fill on its own. Keep in sync with
 * extension/src/security/ats-hosts.ts. Used only to label search results, so a
 * mismatch here changes a badge, never what the extension is allowed to do.
 */
const SUFFIXES: { suffix: string; name: string }[] = [
  { suffix: "greenhouse.io", name: "Greenhouse" },
  { suffix: "myworkdayjobs.com", name: "Workday" },
];
const EXACT: { host: string; name: string }[] = [{ host: "jobs.ashbyhq.com", name: "Ashby" }];

/** The site's name when the extension can fill applications there, otherwise null. */
export function autofillSite(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  const host = url.hostname.toLowerCase();
  for (const e of EXACT) if (host === e.host) return e.name;
  for (const s of SUFFIXES) if (host === s.suffix || host.endsWith(`.${s.suffix}`)) return s.name;
  return null;
}
