/**
 * Injected into the application tab only when the candidate clicks "Fill
 * this application" (see service-worker.ts). It defines one function and
 * does nothing until it is called.
 */

import { MAX_ADVANCES, canAdvance, isWorkdayPage, pageSignature } from "@/form-engine/advance";
import { fillPage } from "@/form-engine/engine";
import type { ResumePayload } from "@/form-engine/engine";
import type { ApplyContext, FillReport } from "@/form-engine/types";

declare global {
  interface Window {
    __jobAgentFill?: (ctx: ApplyContext, resume: ResumePayload | null) => Promise<FillReport>;
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Fills this page; on Workday it also moves on page by page while it is safe to (see advance.ts). */
window.__jobAgentFill = async (ctx, resume) => {
  let report = await fillPage(document, ctx, resume);
  if (!isWorkdayPage(document)) return report;
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
};
