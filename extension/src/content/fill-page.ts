/**
 * Injected into the application tab only when the candidate clicks "Fill
 * this application" (see service-worker.ts). It defines one function and
 * does nothing until it is called.
 */

import { MAX_ADVANCES, canAdvance, isWorkdayPage, pageSignature, stepSignature } from "@/form-engine/advance";
import { fillPage } from "@/form-engine/engine";
import { runWorkday } from "@/form-engine/workday-run";
import type { ResumePayload } from "@/form-engine/engine";
import type { ApplyContext, FillReport } from "@/form-engine/types";

declare global {
  interface Window {
    __jobAgentFill?: (ctx: ApplyContext, resume: ResumePayload | null) => Promise<FillReport>;
    __jobAgentWorkday?: (ctx: ApplyContext, resume: ResumePayload | null) => string;
    __jobAgentRunning?: boolean;
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Fills this page; on Workday it also moves on page by page while it is safe to (see advance.ts). */
async function fillAndAdvance(ctx: ApplyContext, resume: ResumePayload | null, advance = true): Promise<FillReport> {
  let report = await fillPage(document, ctx, resume);
  if (!advance || !isWorkdayPage(document)) return report;
  const filled = [...report.filled];
  let advanced = 0;
  let stopped = "";
  while (advanced < MAX_ADVANCES) {
    const verdict = canAdvance(document, report);
    if (!verdict.ok) {
      stopped = verdict.reason;
      break;
    }
    const before = pageSignature(document);
    verdict.button.click();
    let moved = false;
    for (let i = 0; i < 48 && !moved; i++) {
      await sleep(250);
      moved = pageSignature(document) !== before;
    }
    if (!moved) {
      stopped = "Workday did not move to the next page.";
      break;
    }
    advanced++;
    await sleep(900);
    report = await fillPage(document, ctx, resume);
    filled.push(...report.filled);
  }
  if (advanced >= MAX_ADVANCES && !stopped) stopped = "Stopped after several pages. Check where you are.";
  return { ...report, filled, pagesAdvanced: advanced, stoppedBecause: stopped };
}

/**
 * After a fill, keep watching a Workday application. If the person fixes something by hand and moves
 * to the next step themselves, that new step is filled too (the same rules apply: nothing they
 * typed is overwritten, and nothing is submitted). Re-arming replaces the earlier watcher.
 */
let watcher: number | undefined;
function watchSteps(ctx: ApplyContext, resume: ResumePayload | null): void {
  if (!isWorkdayPage(document)) return;
  if (watcher !== undefined) window.clearInterval(watcher);
  let known = stepSignature(document);
  let candidate = "";
  let busy = false;
  watcher = window.setInterval(() => {
    if (busy || window.__jobAgentRunning) return;
    const now = stepSignature(document);
    if (now === known) {
      candidate = "";
      return;
    }
    if (now !== candidate) {
      candidate = now; // wait one more tick so the new step has finished drawing
      return;
    }
    busy = true;
    void (async () => {
      try {
        await sleep(700);
        // Fill only: the person is driving now, so Next is theirs to press.
        await fillAndAdvance(ctx, resume, false);
      } catch {
        /* the page changed under us; the next change will try again */
      } finally {
        known = stepSignature(document);
        candidate = "";
        busy = false;
      }
    })();
  }, 800);
}

window.__jobAgentFill = async (ctx, resume) => {
  const report = await fillAndAdvance(ctx, resume);
  watchSteps(ctx, resume);
  return report;
};

function tell(message: Record<string, unknown>): void {
  (window as unknown as { __jobAgentOutcome?: unknown }).__jobAgentOutcome = message;
  try {
    if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage) void chrome.runtime.sendMessage(message);
  } catch {
    /* the extension may have been reloaded; nothing to tell */
  }
}

/**
 * Starts the walk from the posting to the form (see workday-run.ts) and returns
 * at once; the result is sent to the extension when it ends. Starting twice on the
 * same page is ignored.
 */
window.__jobAgentWorkday = (ctx, resume) => {
  if (window.__jobAgentRunning) return "already running";
  window.__jobAgentRunning = true;
  void runWorkday(
    document,
    ctx,
    () => fillAndAdvance(ctx, resume),
    () => tell({ type: "WORKDAY_WAITING" }),
  )
    .then((outcome) => {
      watchSteps(ctx, resume);
      tell({ type: "WORKDAY_DONE", report: outcome.report, stoppedBecause: outcome.stoppedBecause });
    })
    .catch((err: Error) => tell({ type: "WORKDAY_DONE", report: null, stoppedBecause: err.message }))
    .finally(() => {
      window.__jobAgentRunning = false;
    });
  return "started";
};
