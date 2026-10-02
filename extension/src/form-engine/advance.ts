/**
 * Workday applications are several pages long. After a page is filled, this
 * decides whether it is safe to press "Save and Continue" for the person, and
 * does so only when every one of these holds:
 *   - the button says exactly Save and Continue, Continue or Next (never
 *     Submit, Apply, Finish or anything else, and never on the Review page),
 *   - nothing on the page still needs the person (no flagged question, no empty
 *     required field, no unticked required box, no error message),
 *   - it is not the federal disability form, which the person signs themselves.
 * It never presses the final Submit.
 */

import { discoverFields } from "@/form-engine/discover";
import { currentValue } from "@/form-engine/fill";
import { isFinalActionText } from "@/form-engine/safety";
import type { FillReport } from "@/form-engine/types";

const NEXT_LABEL = /^(save and continue|continue|next)$/i;
const MAX_PAGES = 8;

export const MAX_ADVANCES = MAX_PAGES;

export function isWorkdayPage(doc: Document): boolean {
  const host = doc.location?.hostname ?? "";
  return host === "myworkdayjobs.com" || host.endsWith(".myworkdayjobs.com");
}

export type Verdict = { ok: true; button: HTMLButtonElement } | { ok: false; reason: string };

export function canAdvance(doc: Document, report: FillReport): Verdict {
  const button = doc.querySelector<HTMLButtonElement>("[data-automation-id='pageFooterNextButton']");
  if (!button) return { ok: false, reason: "There is no Next button on this page." };
  const label = (button.textContent ?? "").replace(/\s+/g, " ").trim();
  if (isFinalActionText(label) || !NEXT_LABEL.test(label)) {
    return { ok: false, reason: `This is the last step ("${label}"). Review it and submit it yourself.` };
  }
  const headings = Array.from(doc.querySelectorAll("h2, h3")).map((h) => (h.textContent ?? "").trim());
  if (headings.some((h) => /^review$/i.test(h) && !doc.querySelector("[data-automation-id='applyFlowMyInfoPage']"))) {
    return { ok: false, reason: "This is the Review page. Check it and submit it yourself." };
  }
  if (/self-identification of disability/i.test(doc.body?.innerText ?? "")) {
    return { ok: false, reason: "This is the disability form, which you complete yourself." };
  }
  if (report.flagged.length > 0) {
    return { ok: false, reason: `${report.flagged.length} question${report.flagged.length === 1 ? " needs" : "s need"} you.` };
  }
  if (doc.querySelector("[data-automation-id='errorBanner']") || /\bErrors? Found\b/.test(doc.body?.innerText ?? "")) {
    return { ok: false, reason: "Workday is showing an error on this page." };
  }
  for (const field of discoverFields(doc)) {
    if (!field.required) continue;
    if (field.kind === "checkbox") {
      if (!(field.el as HTMLInputElement).checked) return { ok: false, reason: `"${field.label}" needs your tick.` };
    } else if (currentValue(field) === "") {
      return { ok: false, reason: `"${field.label}" is still empty.` };
    }
  }
  return { ok: true, button };
}

/** A cheap fingerprint of the current step, to notice when Workday has moved on. */
export function pageSignature(doc: Document): string {
  const heads = Array.from(doc.querySelectorAll("h2")).map((h) => (h.textContent ?? "").trim()).join("|");
  const first = doc.querySelector("[data-automation-id^='formField']")?.getAttribute("data-automation-id") ?? "";
  const count = doc.querySelectorAll("[data-automation-id^='formField']").length;
  return `${heads}#${first}#${count}`;
}
