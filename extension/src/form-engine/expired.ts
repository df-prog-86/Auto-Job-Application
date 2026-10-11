/**
 * True when the open SmartRecruiters page says the job is closed ("This job has expired"). Such a page has no Apply link
 * and no form, so the extension tells the person instead of silently doing nothing.
 *
 * This function is sent into the page as it is, so it must not use anything declared outside it.
 */
export function pageIsExpiredSmartRecruiters(): boolean {
  if (location.hostname !== "jobs.smartrecruiters.com") return false;
  if (/\/expired\/?$/.test(location.pathname)) return true;
  // Only the top of the page: a live posting's own text is never mistaken for the notice.
  const top = (document.body?.innerText ?? "").slice(0, 600);
  return /this job( ad)? has expired/i.test(top) || /^this job ad has expired/i.test(document.title);
}
