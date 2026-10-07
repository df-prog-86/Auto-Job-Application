/**
 * Recognizes the employer's "your application was received" page, so a job
 * can be marked Applied without the person doing anything extra. Deliberately
 * strict: a wrong "applied" is worse than a missed one (the person can always
 * press "Mark as applied" in the app, and can undo a wrong one there too).
 */

const CONFIRMATION_PATHS = [
  /\/confirmation(\/|$)/i, // Greenhouse
  /\/jobTasks\/completed\/application/i, // Workday
];

const CONFIRMATION_PHRASES = [
  /thank you for applying/i,
  /thanks for applying/i,
  /your application (has been|was) (successfully )?(submitted|received|sent)/i,
  /we(?:'ve| have) received your application/i,
  /application (successfully )?(submitted|received)\b/i,
];

export function looksSubmitted(rawUrl: string, pageText: string): boolean {
  let path = "";
  try {
    path = new URL(rawUrl).pathname;
  } catch {
    return false;
  }
  const text = (pageText || "").slice(0, 4000);
  const phraseHit = CONFIRMATION_PHRASES.some((re) => re.test(text));
  if (phraseHit) return true;
  // A confirmation address alone is enough only if the page isn't still asking for input.
  return CONFIRMATION_PATHS.some((re) => re.test(path)) && !/\b(submit application|next|continue)\b/i.test(text.slice(0, 600));
}
