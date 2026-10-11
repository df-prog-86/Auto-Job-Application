/**
 * SmartRecruiters' Experience and Education sections. Each starts empty with an "Add" button; pressing it opens a small
 * form for one entry (Title, Company, dates and so on) that is saved with the form's own Save button, which only keeps
 * that entry in the application. This file adds one entry per job or school from the person's saved resume.
 *
 * Rules, the same as the other sites:
 *   - A section that already has an entry, or an open form, is never touched.
 *   - Only the buttons Add, the entry's own Save, and the "currently work here" tick are ever pressed. Never Submit.
 *   - Type-ahead boxes (Title, Company, ...) are filled by typing and then picking the row that matches what was typed
 *     exactly; a suggestion that merely looks similar is never picked.
 *   - A date is written only when the saved resume has the month and year. Nothing is guessed. If a required value is
 *     missing, the form is left open for the person with that field flagged, and no further entries are added.
 * It runs only on jobs.smartrecruiters.com.
 */

import { deepQueryAll, shadowHost } from "@/form-engine/deep";
import { setNativeValue } from "@/form-engine/fill";
import { mark } from "@/form-engine/highlight";
import type { ApplyContext, ApplyEducation, ApplyExperience, FillReport } from "@/form-engine/types";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const clean = (t: string | null | undefined) => (t ?? "").replace(/[*✱∗]/g, " ").replace(/\s+/g, " ").trim();
const MAX_JOBS = 6;
const MAX_SCHOOLS = 3;

type Kind = "experience" | "education";
type Box = HTMLInputElement | HTMLTextAreaElement;

/** Everything matching `selector` under a custom element: its own children and its shadow root, at any depth. */
function inside(host: Element, selector: string): HTMLElement[] {
  const out = deepQueryAll<HTMLElement>(host, selector);
  if (host.shadowRoot) out.push(...deepQueryAll<HTMLElement>(host.shadowRoot, selector));
  return out;
}

/** All the text under an element, including text inside shadow roots. */
function deepText(node: Node): string {
  if (node.nodeType === 3) return node.textContent ?? "";
  if (node.nodeType !== 1 && node.nodeType !== 11) return "";
  const el = node as Element;
  if (/^(style|script)$/i.test(el.tagName ?? "")) return "";
  const parts: string[] = [];
  const shadow = (el as Element).shadowRoot;
  if (shadow) parts.push(deepText(shadow));
  for (const child of Array.from(node.childNodes)) parts.push(deepText(child));
  return parts.join(" ");
}

/** The question a box belongs to: the label on the nearest custom element around it, else its own aria-label. */
function labelOf(el: Element): string {
  let host = shadowHost(el);
  while (host) {
    const label = host.getAttribute("label");
    if (label && label.trim()) return clean(label);
    host = shadowHost(host);
  }
  return clean(el.getAttribute("aria-label"));
}

function box(form: Element, label: string): Box | null {
  const want = label.toLowerCase();
  const hit = inside(form, "input, textarea").find((e) => {
    const type = (e as HTMLInputElement).type;
    return type !== "number" && type !== "checkbox" && labelOf(e).toLowerCase() === want;
  });
  return (hit as Box | undefined) ?? null;
}

/** The real <button> inside one of the page's button components. */
function pressable(root: Element, selector: string): HTMLElement | null {
  const host = inside(root, selector)[0];
  if (!host) return null;
  return inside(host, "button")[0] ?? host;
}

const isDisabled = (el: HTMLElement) => (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true";

async function waitFor<T>(find: () => T | null | undefined, tries = 24, gap = 125): Promise<T | null> {
  for (let i = 0; i < tries; i++) {
    const hit = find();
    if (hit) return hit;
    await sleep(gap);
  }
  return find() ?? null;
}

function typed(el: Box, text: string): void {
  el.focus();
  setNativeValue(el, text);
  el.dispatchEvent(new InputEvent("input", { bubbles: true, composed: true, data: text, inputType: "insertText" }));
}

/**
 * A type-ahead box: types the text and picks the row that matches it exactly (the list always offers the typed text itself
 * as a row). True only when the box ends up holding that text. On failure the box is emptied again.
 */
async function pickTyped(input: HTMLInputElement, text: string): Promise<boolean> {
  const want = clean(text).toLowerCase();
  typed(input, text.trim());
  const id = input.getAttribute("aria-controls");
  const rowFor = (): HTMLElement | null => {
    if (!id) return null;
    const list = deepQueryAll<HTMLElement>(input.ownerDocument, `#${CSS.escape(id)}`)[0];
    if (!list) return null;
    return inside(list, "spl-select-option").find((r) => clean(deepText(r)).toLowerCase() === want) ?? null;
  };
  const row = await waitFor(rowFor, 24, 125);
  if (row) {
    row.click();
    await sleep(300);
    if (clean(input.value).toLowerCase() === want) return true;
  }
  typed(input, "");
  input.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
  return false;
}

/** Writes "MM/YYYY" into a month-and-year box and checks the page's date picker understood it. */
async function writeMonth(input: HTMLInputElement, date: string | null | undefined): Promise<boolean> {
  const m = /^(\d{4})-(\d{2})/.exec(date ?? "");
  if (!m) return false;
  const text = `${m[2]}/${m[1]}`;
  input.focus();
  setNativeValue(input, text);
  input.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
  await sleep(200);
  let host: Element | null = shadowHost(input);
  while (host && host.tagName.toLowerCase() !== "spl-date-picker") host = shadowHost(host);
  const parsed = host ? (host as unknown as { value?: unknown }).value : true;
  return input.value === text && !!parsed;
}

function dateBox(form: Element, label: "From" | "To"): HTMLInputElement | null {
  const want = label.toLowerCase();
  const hit = inside(form, "input").find((e) => (e as HTMLInputElement).type === "text" && labelOf(e).toLowerCase() === want);
  return (hit as HTMLInputElement | undefined) ?? null;
}

function currentBox(form: Element, kind: Kind): HTMLInputElement | null {
  const host = inside(form, `oc-checkbox[data-test="${kind}-current"]`)[0];
  return host ? ((inside(host, "input[type='checkbox']")[0] as HTMLInputElement | undefined) ?? null) : null;
}

function flag(report: FillReport, label: string): void {
  report.flagged.push({ label, field_type: "text", options: [], required: true });
}

interface Progress {
  section: HTMLElement;
  report: FillReport;
  tag: string;
  needs: string[];
}

function ok(p: Progress, label: string): void {
  p.report.filled.push(`${p.tag}: ${label}`);
}

async function fillText(p: Progress, el: Box | null, label: string, value: string | null | undefined): Promise<void> {
  if (!el || !value?.trim()) return;
  typed(el, value.trim());
  el.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
  await sleep(60);
  if (el.value.trim() !== "") ok(p, label);
}

async function fillTypeahead(p: Progress, el: Box | null, label: string, value: string | null | undefined, required: boolean): Promise<void> {
  if (!el) {
    if (required) p.needs.push(label);
    return;
  }
  if (!value?.trim()) {
    if (required) p.needs.push(label);
    return;
  }
  if (await pickTyped(el as HTMLInputElement, value)) ok(p, label);
  else p.needs.push(`${label} (pick it from the list)`);
}

async function fillDate(p: Progress, el: HTMLInputElement | null, label: string, value: string | null | undefined, required: boolean): Promise<void> {
  if (!el) return;
  if (value && (await writeMonth(el, value))) ok(p, label);
  else if (required) p.needs.push(`${label} (month and year)`);
}

async function fillJob(form: Element, job: ApplyExperience, p: Progress): Promise<void> {
  await fillTypeahead(p, box(form, "Title"), "Title", job.title, true);
  await fillTypeahead(p, box(form, "Company"), "Company", job.employer, false);
  await fillTypeahead(p, box(form, "Office location"), "Office location", job.location, false);
  await fillText(p, box(form, "Description"), "Description", job.description);
  await fillDate(p, dateBox(form, "From"), "From", job.start_date, true);
  const current = currentBox(form, "experience");
  if (job.current && current) {
    if (!current.checked) {
      current.click();
      await sleep(250);
    }
    if (current.checked) ok(p, "I currently work here");
    else p.needs.push("I currently work here");
  } else {
    await fillDate(p, dateBox(form, "To"), "To", job.end_date, true);
  }
}

async function fillSchool(form: Element, school: ApplyEducation, p: Progress): Promise<void> {
  await fillTypeahead(p, box(form, "Institution"), "Institution", school.institution, true);
  await fillText(p, box(form, "Major"), "Major", school.field);
  await fillText(p, box(form, "Degree"), "Degree", school.degree ?? school.degree_short);
  // The page asks for a month and a year. A saved year alone is not enough to write, and these boxes are optional.
  await fillDate(p, dateBox(form, "From"), "From", school.start_date, false);
  await fillDate(p, dateBox(form, "To"), "To", school.end_date, false);
}

/** Adds one entry. True when it was saved; false leaves any open form for the person and stops the section. */
async function addEntry(doc: Document, section: HTMLElement, kind: Kind, n: number, data: ApplyExperience | ApplyEducation, report: FillReport): Promise<boolean> {
  const tag = kind === "experience" ? `Experience ${n}` : `Education ${n}`;
  const add = pressable(section, `oc-button[data-test="add-${kind}"]`);
  if (!add) return false;
  add.click();
  const form = await waitFor(() => inside(section, `oc-${kind}-edit-form`)[0]);
  if (!form) {
    flag(report, `${tag}: the form would not open`);
    return false;
  }
  await sleep(150);

  const p: Progress = { section, report, tag, needs: [] };
  if (kind === "experience") await fillJob(form, data as ApplyExperience, p);
  else await fillSchool(form, data as ApplyEducation, p);

  if (p.needs.length > 0) {
    for (const need of p.needs) flag(report, `${tag}: ${need}`);
    return false;
  }
  const save = pressable(form, `oc-button[data-test="${kind}-save"]`);
  if (!save || isDisabled(save)) {
    flag(report, `${tag}: Save`);
    return false;
  }
  save.click();
  const closed = await waitFor(() => (inside(section, `oc-${kind}-edit-form`).length === 0 ? true : null), 40, 125);
  if (!closed) {
    flag(report, `${tag}: finish and save this entry`);
    return false;
  }
  report.filled.push(`${tag}: saved`);
  return true;
}

/** True when the section already holds something beyond its title and Add button. */
function hasEntries(section: HTMLElement): boolean {
  return clean(deepText(section).replace(/\b(experience|education|add)\b/gi, " ")) !== "";
}

async function fillSection(doc: Document, kind: Kind, items: Array<ApplyExperience | ApplyEducation>, report: FillReport): Promise<void> {
  if (items.length === 0) return;
  const section = await waitFor(() => {
    const s = deepQueryAll<HTMLElement>(doc, `oc-${kind}`)[0];
    return s && pressable(s, `oc-button[data-test="add-${kind}"]`) ? s : null;
  }, 24, 125);
  if (!section) return;
  if (inside(section, `oc-${kind}-edit-form`).length > 0 || hasEntries(section)) return;

  const before = { filled: report.filled.length, flagged: report.flagged.length };
  for (const [i, item] of items.entries()) {
    if (!(await addEntry(doc, section, kind, i + 1, item, report))) break;
  }
  mark(section, report.flagged.length > before.flagged ? "flagged" : report.filled.length > before.filled ? "filled" : "flagged");
}

export async function fillSmartRecruitersHistory(doc: Document, ctx: ApplyContext, report: FillReport): Promise<void> {
  if (doc.location?.hostname !== "jobs.smartrecruiters.com") return;
  await fillSection(doc, "experience", (ctx.experience ?? []).slice(0, MAX_JOBS), report);
  await fillSection(doc, "education", (ctx.education ?? []).slice(0, MAX_SCHOOLS), report);
}
