/**
 * Workday's "My Experience" page: the repeating Work Experience and Education
 * rows (plus an empty Websites row). Rows are only filled when every row on the
 * page is still empty, so nothing the person typed (or Workday saved from an
 * earlier visit) is ever touched. Extra rows come from pressing "Add Another",
 * which is the only button this file ever presses.
 *
 * The page structure here was read from screenshots, so every step checks its
 * own result and reports what it could not do instead of guessing.
 */

import { normalizeQuestion } from "@/form-engine/canonical";
import { discoverFields } from "@/form-engine/discover";
import type { FormField } from "@/form-engine/discover";
import { currentValue, fillField, readDropdownOptions, setNativeValue } from "@/form-engine/fill";
import { mark } from "@/form-engine/highlight";
import type { ApplyContext, ApplyEducation, ApplyExperience, FillReport } from "@/form-engine/types";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const MAX_ROWS = 6;

const clean = (t: string | null | undefined) => (t ?? "").replace(/[*✱∗]/g, " ").replace(/\s+/g, " ").trim();

type Kind = "work" | "edu" | "web";

const PANEL: Record<Kind, RegExp> = {
  work: /^workExperience-\d+$/,
  edu: /^education-\d+$/,
  web: /^websites?-\d+$/,
};
const HEADING: Record<Kind, RegExp> = {
  work: /^work experience \d+$/i,
  edu: /^education \d+$/i,
  web: /^websites? \d+$/i,
};

const DATE_SELECTOR =
  "input[data-automation-id*='dateSection' i], input[placeholder*='MM'], input[placeholder*='YYYY'], input[aria-label*='month' i], input[aria-label*='year' i]";

export function isDateInput(el: Element): boolean {
  return el.matches(DATE_SELECTOR);
}

function ownText(el: Element): string {
  return clean(
    Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join(" "),
  );
}

const isAddAnother = (b: Element) => /^add another$/i.test(clean(b.textContent));

/** The containers of each numbered row, in page order. */
export function findRows(doc: Document, kind: Kind): HTMLElement[] {
  const byId = Array.from(doc.querySelectorAll<HTMLElement>("[data-automation-id]")).filter((e) =>
    PANEL[kind].test(e.getAttribute("data-automation-id") ?? ""),
  );
  if (byId.length > 0) return byId;

  const all = (k: Kind) => Array.from(doc.querySelectorAll("*")).filter((e) => HEADING[k].test(ownText(e)));
  const mine = all(kind);
  const others = (["work", "edu", "web"] as Kind[]).filter((k) => k !== kind).flatMap(all);
  const rows: HTMLElement[] = [];
  for (const h of mine) {
    let box = h as HTMLElement;
    while (box.parentElement) {
      const up = box.parentElement;
      const mineIn = mine.filter((m) => up.contains(m)).length;
      const hasOther = others.some((o) => up.contains(o));
      const hasAdd = Array.from(up.querySelectorAll("button")).some(isAddAnother);
      if (mineIn !== 1 || hasOther || hasAdd || up === doc.body) break;
      box = up;
    }
    if (box !== h && box.querySelector("input, textarea, button[aria-haspopup]")) rows.push(box);
  }
  return rows;
}

function rowFields(row: HTMLElement, doc: Document): FormField[] {
  return discoverFields(doc).filter((f) => row.contains(f.el) && !isDateInput(f.el));
}

function find(fields: FormField[], pattern: RegExp): FormField | undefined {
  return fields.find((f) => pattern.test(normalizeQuestion(f.label)));
}

function rowIsEmpty(row: HTMLElement, doc: Document): boolean {
  const fields = rowFields(row, doc).filter((f) => f.kind !== "checkbox");
  if (fields.some((f) => currentValue(f) !== "")) return false;
  const dates = Array.from(row.querySelectorAll<HTMLInputElement>(DATE_SELECTOR));
  return dates.every((d) => d.value.trim() === "");
}

async function clickAddAnother(doc: Document, last: HTMLElement): Promise<boolean> {
  const btn = Array.from(doc.querySelectorAll<HTMLButtonElement>("button")).find(
    (b) => isAddAnother(b) && !last.contains(b) && !!(last.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING),
  );
  if (!btn) return false;
  const form = btn.closest("form");
  const block = (e: Event) => {
    e.preventDefault();
    e.stopImmediatePropagation();
  };
  form?.addEventListener("submit", block, true);
  try {
    btn.click();
    await sleep(200);
  } finally {
    form?.removeEventListener("submit", block, true);
  }
  return true;
}

/** Makes sure there are `want` rows, pressing "Add Another" as needed. */
async function ensureRows(doc: Document, kind: Kind, want: number): Promise<HTMLElement[]> {
  let rows = findRows(doc, kind);
  while (rows.length > 0 && rows.length < want) {
    const before = rows.length;
    if (!(await clickAddAnother(doc, rows[rows.length - 1]))) break;
    for (let i = 0; i < 24 && rows.length === before; i++) {
      await sleep(125);
      rows = findRows(doc, kind);
    }
    if (rows.length === before) break;
    await sleep(150);
  }
  return rows;
}

// ---- dates -----------------------------------------------------------------

interface DateWidget {
  label: "from" | "to";
  inputs: HTMLInputElement[];
}

/** Each From / To date box in the row, found by the From / To label that sits with it. */
function dateWidgets(row: HTMLElement): DateWidget[] {
  const inputs = Array.from(row.querySelectorAll<HTMLInputElement>(DATE_SELECTOR)).filter((i) => !i.disabled && !i.readOnly);
  const groups = new Map<HTMLElement, { label: "from" | "to"; inputs: HTMLInputElement[] }>();
  for (const input of inputs) {
    let p: HTMLElement | null = input.parentElement;
    while (p && p !== row) {
      const labels = Array.from(p.querySelectorAll("label, legend"))
        .map((l) => clean(l.textContent).toLowerCase())
        .filter((t) => /^(from|to)\b/.test(t));
      const kinds = new Set(labels.map((t) => (t.startsWith("from") ? "from" : "to")));
      if (kinds.size === 1) {
        const label = [...kinds][0] as "from" | "to";
        const g = groups.get(p) ?? { label, inputs: [] };
        g.inputs.push(input);
        groups.set(p, g);
        break;
      }
      if (kinds.size > 1) break;
      p = p.parentElement;
    }
  }
  return Array.from(groups.values());
}

const attrs = (i: HTMLInputElement) =>
  `${i.getAttribute("data-automation-id") ?? ""} ${i.getAttribute("aria-label") ?? ""} ${i.getAttribute("placeholder") ?? ""} ${i.id}`;

/** Writes "YYYY-MM" (or just the year) into a date box and checks it took. */
async function writeDate(w: DateWidget, ym: string, yearOnly: boolean): Promise<boolean> {
  const [year, month] = ym.split("-");
  if (!/^\d{4}$/.test(year ?? "")) return false;
  const set = (i: HTMLInputElement, v: string) => {
    i.focus();
    setNativeValue(i, v);
    i.dispatchEvent(new Event("blur", { bubbles: true }));
  };
  const monthBox = w.inputs.find((i) => /month|^MM$/i.test(attrs(i)) && !/MM\s*\/\s*YYYY/i.test(attrs(i)));
  const yearBox = w.inputs.find((i) => /year|^YYYY$/i.test(attrs(i)) && !/MM\s*\/\s*YYYY/i.test(attrs(i)));
  if (monthBox && yearBox && !yearOnly) {
    if (!/^\d{2}$/.test(month ?? "")) return false;
    set(monthBox, month);
    set(yearBox, year);
    await sleep(60);
    return monthBox.value.trim() !== "" && yearBox.value.includes(year);
  }
  const single = w.inputs[0];
  if (!single) return false;
  if (yearOnly || (yearBox && !monthBox)) {
    set(yearBox ?? single, year);
    await sleep(60);
    return (yearBox ?? single).value.includes(year);
  }
  if (!/^\d{2}$/.test(month ?? "")) return false;
  set(single, `${month}/${year}`);
  await sleep(60);
  return single.value.includes(year);
}

// ---- reporting ---------------------------------------------------------------

function done(report: FillReport, label: string, el: HTMLElement): void {
  report.filled.push(label);
  mark(el, "filled");
}

function flag(report: FillReport, label: string, el: HTMLElement | null, required = true): void {
  report.flagged.push({ label, field_type: "text", options: [], required });
  if (el) mark(el, "flagged");
}

async function putText(report: FillReport, field: FormField | undefined, label: string, value: string | null | undefined): Promise<void> {
  if (!field || !value?.trim() || currentValue(field) !== "") return;
  if (await fillField(field, value.trim())) done(report, label, field.outlineEl);
}

// ---- rows ----------------------------------------------------------------------

async function fillWorkRow(doc: Document, row: HTMLElement, n: number, e: ApplyExperience, report: FillReport): Promise<void> {
  const tag = `Work Experience ${n}`;
  const fields = rowFields(row, doc);
  await putText(report, find(fields, /^job title$/), `${tag}: Job Title`, e.title);
  await putText(report, find(fields, /^company( name)?$/), `${tag}: Company`, e.employer);
  await putText(report, find(fields, /^location$/), `${tag}: Location`, e.location);
  await putText(report, find(fields, /role description|description/), `${tag}: Role Description`, e.description);

  const box = fields.find((f) => f.kind === "checkbox" && /currently work/i.test(f.label))?.el as HTMLInputElement | undefined;
  if (e.current && box && !box.checked) {
    box.click();
    await sleep(250);
    if (box.checked) done(report, `${tag}: I currently work here`, box);
  }

  const widgets = dateWidgets(row);
  const from = widgets.find((w) => w.label === "from");
  if (!e.start_date) {
    flag(report, `${tag}: From (month and year)`, from?.inputs[0] ?? null);
  } else if (from && (await writeDate(from, e.start_date, false))) {
    done(report, `${tag}: From`, from.inputs[0]);
  } else {
    flag(report, `${tag}: From (month and year)`, from?.inputs[0] ?? null);
  }
  if (!(box?.checked ?? e.current)) {
    const to = dateWidgets(row).find((w) => w.label === "to");
    if (!e.end_date) {
      flag(report, `${tag}: To (month and year)`, to?.inputs[0] ?? null);
    } else if (to && (await writeDate(to, e.end_date, false))) {
      done(report, `${tag}: To`, to.inputs[0]);
    } else {
      flag(report, `${tag}: To (month and year)`, to?.inputs[0] ?? null);
    }
  }
}

/** Picks the dropdown choice for a degree, only when exactly one fits. */
export function degreeChoice(degree: string | null | undefined, options: string[]): string | null {
  const d = clean(degree).toLowerCase();
  if (!d) return null;
  let keyword = "";
  if (/\bmba\b|master|\bm\.?\s?s\.?c?\b|\bm\.?a\.?\b/.test(d)) keyword = /\bmba\b/.test(d) ? "mba" : "master";
  else if (/bachelor|\bb\.?\s?s\.?c?\b|\bb\.?a\.?\b/.test(d)) keyword = "bachelor";
  else if (/ph\.?\s?d|doctor/.test(d)) keyword = "doctor";
  else if (/associate|\ba\.?a\.?s?\b/.test(d)) keyword = "associate";
  else if (/high school|\bged\b/.test(d)) keyword = "high school";
  if (!keyword) return null;
  const hits = options.filter((o) => normalizeQuestion(o).includes(keyword));
  if (hits.length === 1) return hits[0];
  if (hits.length > 1) {
    const words = normalizeQuestion(d).split(" ").slice(0, 3).join(" ");
    const closer = hits.filter((o) => normalizeQuestion(o).includes(words));
    if (closer.length === 1) return closer[0];
  }
  return null;
}

async function fillEduRow(doc: Document, row: HTMLElement, n: number, e: ApplyEducation, report: FillReport): Promise<void> {
  const tag = `Education ${n}`;
  const fields = rowFields(row, doc);
  await putText(report, find(fields, /^school( or university)?$|^institution$/), `${tag}: School or University`, e.institution);

  const degreeField = find(fields, /^degree$/);
  if (degreeField && degreeField.kind === "dropdown" && currentValue(degreeField) === "" && e.degree) {
    const pick = degreeChoice(e.degree, await readDropdownOptions(degreeField.el));
    if (pick && (await fillField(degreeField, pick))) done(report, `${tag}: Degree`, degreeField.outlineEl);
  }
  const study = find(fields, /^field of study$/);
  if (study && e.field && currentValue(study) === "") {
    if (await fillField(study, e.field, { typeText: e.field })) done(report, `${tag}: Field of Study`, study.outlineEl);
  }
  // Years only; both are optional on the page.
  const widgets = dateWidgets(row);
  const from = widgets.find((w) => w.label === "from");
  const to = widgets.find((w) => w.label === "to");
  if (from && e.start_date && (await writeDate(from, e.start_date, true))) done(report, `${tag}: From`, from.inputs[0]);
  if (to && e.end_date && (await writeDate(to, e.end_date, true))) done(report, `${tag}: To`, to.inputs[0]);
}

export interface HistoryResult {
  /** Row containers, so the general pass leaves their fields to this file. */
  rows: HTMLElement[];
}

/** Fills the repeating rows on the page, if it has any. Returns the rows it owns. */
export async function fillHistory(doc: Document, ctx: ApplyContext, report: FillReport): Promise<HistoryResult> {
  const owned: HTMLElement[] = [];

  const work = findRows(doc, "work");
  const jobs = (ctx.experience ?? []).slice(0, MAX_ROWS);
  if (work.length > 0 && jobs.length > 0 && work.every((r) => rowIsEmpty(r, doc))) {
    const rows = await ensureRows(doc, "work", jobs.length);
    for (const [i, job] of jobs.entries()) {
      if (rows[i]) await fillWorkRow(doc, rows[i], i + 1, job, report);
    }
  }
  owned.push(...findRows(doc, "work"));

  const edu = findRows(doc, "edu");
  const schools = (ctx.education ?? []).slice(0, MAX_ROWS);
  if (edu.length > 0 && schools.length > 0 && edu.every((r) => rowIsEmpty(r, doc))) {
    const rows = await ensureRows(doc, "edu", schools.length);
    for (const [i, school] of schools.entries()) {
      if (rows[i]) await fillEduRow(doc, rows[i], i + 1, school, report);
    }
  }
  owned.push(...findRows(doc, "edu"));

  // One empty "Websites" row asks for a required URL; the LinkedIn address is the natural fit.
  const web = findRows(doc, "web");
  const linkedin = ctx.candidate.linkedin_url?.trim();
  if (web.length === 1 && linkedin && rowIsEmpty(web[0], doc)) {
    await putText(report, find(rowFields(web[0], doc), /^url$/), "Websites 1: URL", linkedin);
  }
  owned.push(...web);

  return { rows: owned };
}
