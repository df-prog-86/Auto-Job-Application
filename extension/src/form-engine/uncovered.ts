/**
 * Safety net for Workday: a required question the filler did not recognise at all
 * (a custom radio set, a "How did you hear about us" picker, an unlabeled box) would
 * otherwise sit blank with no warning. Each one that is still empty is outlined and
 * reported so the candidate sees it. Nothing is ever filled here.
 */

import type { FormField } from "@/form-engine/discover";
import { mark } from "@/form-engine/highlight";
import type { FillReport } from "@/form-engine/types";

function text(n: Element | null | undefined): string {
  return (n?.textContent ?? "").replace(/[*✱∗]/g, " ").replace(/\s+/g, " ").trim();
}

function hasAnswer(block: HTMLElement): boolean {
  if (block.querySelector("[aria-checked='true'], input:checked, [data-automation-id='selectedItem'], [data-automation-id='selectedItemList'] > *")) return true;
  for (const i of Array.from(block.querySelectorAll<HTMLInputElement>("input, textarea"))) {
    if (["hidden", "radio", "checkbox", "button", "submit"].includes(i.type)) continue;
    if (i.value.trim() !== "") return true;
  }
  for (const b of Array.from(block.querySelectorAll<HTMLElement>("button[aria-haspopup='listbox']"))) {
    if (!/^select one$/i.test(text(b))) return true;
  }
  return false;
}

export function flagUncovered(doc: Document, fields: FormField[], report: FillReport): void {
  const claimed = (block: HTMLElement) =>
    fields.some((f) => block.contains(f.el) || f.outlineEl.contains(block) || (f.group ?? []).some((g) => block.contains(g)));
  const reported = new Set(report.flagged.map((f) => f.label.toLowerCase()));
  for (const block of Array.from(doc.querySelectorAll<HTMLElement>("[data-automation-id^='formField']"))) {
    if (block.closest("[hidden], [aria-hidden='true']")) continue;
    if (block.querySelector("[data-job-agent]") || claimed(block)) continue;
    const head = block.querySelector("label, legend");
    const label = text(head);
    if (!label || !/\*|required/i.test(head?.textContent ?? "") && block.querySelector("[aria-required='true'], input[required]") === null) continue;
    if (hasAnswer(block) || reported.has(label.toLowerCase())) continue;
    if (!block.querySelector("input, textarea, select, button, [role='radio']")) continue;
    report.flagged.push({ label, field_type: "other", options: [], required: true });
    mark(block, "flagged");
  }
}
