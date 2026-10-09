/**
 * The only sites the extension may open and fill on its own. Keep in sync
 * with host_permissions in public/manifest.json (Chrome enforces that list
 * too, so a mismatch fails closed rather than open).
 */
const SUPPORTED_SUFFIXES = ["greenhouse.io", "myworkdayjobs.com"];
const SUPPORTED_EXACT = ["jobs.ashbyhq.com", "jobs.lever.co", "jobs.eu.lever.co"];

export function isSupportedApplicationUrl(raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (url.protocol !== "https:") return false;
  const host = url.hostname.toLowerCase();
  return (
    SUPPORTED_EXACT.includes(host) ||
    SUPPORTED_SUFFIXES.some((s) => host === s || host.endsWith(`.${s}`))
  );
}
