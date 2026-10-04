/**
 * Walks a Workday application from the job posting to the first form page,
 * then hands over to the normal fill-and-advance. In order:
 *   listing page  -> presses "Apply"
 *   start choices -> presses "Apply Manually" (never autofill or last application)
 *   sign-in page  -> types the person's email only, then WAITS for them to sign in
 *   form page     -> fills and moves on while it is safe (see advance.ts)
 * It never types a password, never creates an account and never submits. Sign-in
 * stays with the person (Chrome's password manager does the rest); once they are
 * through, this carries on by itself.
 */

import { isWorkdayPage } from "@/form-engine/advance";
import { setNativeValue } from "@/form-engine/fill";
import type { ApplyContext, FillReport } from "@/form-engine/types";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** The only buttons this runner may press before the form: they open the form, nothing more. */
const ALLOWED_ENTRY = new Set(["adventureButton", "applyManually"]);

export type Stage = "form" | "choose" | "signin" | "listing" | "unknown";

const present = (doc: Document, selector: string): HTMLElement | null => {
  const el = doc.querySelector<HTMLElement>(selector);
  return el && !el.closest("[hidden], [aria-hidden='true']") ? el : null;
};

export function detectStage(doc: Document): Stage {
  if (present(doc, "[data-automation-id='pageFooterNextButton']")) return "form";
  if (present(doc, "[data-automation-id='applyManually']")) return "choose";
  if (present(doc, "input[type='password']")) return "signin";
  if (present(doc, "[data-automation-id='adventureButton']")) return "listing";
  return "unknown";
}

function pressEntry(el: HTMLElement): boolean {
  const id = el.getAttribute("data-automation-id") ?? "";
  if (!ALLOWED_ENTRY.has(id)) return false;
  el.click();
  return true;
}

export interface WorkdayOutcome {
  report: FillReport | null;
  stoppedBecause: string;
}

export async function runWorkday(
  doc: Document,
  ctx: ApplyContext,
  fillAndAdvance: () => Promise<FillReport>,
  onWaitingForSignIn: () => void,
  maxMs = 15 * 60_000,
): Promise<WorkdayOutcome> {
  const deadline = Date.now() + maxMs;
  let announced = false;
  let lastPress = 0;
  while (Date.now() < deadline) {
    if (!isWorkdayPage(doc)) return { report: null, stoppedBecause: "The tab left Workday." };
    const stage = detectStage(doc);
    if (stage === "form") {
      await sleep(600); // let the page finish drawing
      return { report: await fillAndAdvance(), stoppedBecause: "" };
    }
    if (stage === "choose" || stage === "listing") {
      if (Date.now() - lastPress > 4000) {
        const id = stage === "choose" ? "applyManually" : "adventureButton";
        const el = present(doc, `[data-automation-id='${id}']`);
        if (el && pressEntry(el)) lastPress = Date.now();
      }
    } else if (stage === "signin") {
      const email = doc.querySelector<HTMLInputElement>("input[data-automation-id='email'], input[type='email']");
      if (email && !email.value && ctx.candidate.email) setNativeValue(email, ctx.candidate.email);
      if (!announced) {
        announced = true;
        onWaitingForSignIn();
      }
    }
    await sleep(800);
  }
  return { report: null, stoppedBecause: "Timed out waiting for the application form." };
}
