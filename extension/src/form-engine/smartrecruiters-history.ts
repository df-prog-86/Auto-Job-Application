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

/** The name of a row that comes from the page's own database (its text is repeated), else null. */
function databaseName(text: string): string | null {
  const w = clean(text).split(" ");
  for (let len = Math.floor(w.length / 2); len >= 1; len--) {
    let same = true;
    for (let j = 0; j < len; j++) if (w[len + j] !== w[j]) same = false;
    if (same) return w.slice(0, len).join(" ");
  }
  return null;
}

interface Row {
  el: HTMLElement;
  text: string;
}
type Chooser = (rows: Row[]) => HTMLElement | null;

/**
 * A search box: types the text, waits for the suggestions, and clicks the one `choose` approves. True only when a row was
 * clicked and the box now holds something. When nothing qualifies the box is emptied again, never left half typed.
 */
let why = "";

/** A real-looking mouse press on a suggestion: pointer down, mouse down, pointer up, mouse up, click (all crossing shadow roots). */
function press(el: HTMLElement): void {
  const r = el.getBoundingClientRect();
  const at = { bubbles: true, composed: true, cancelable: true, button: 0, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, view: el.ownerDocument.defaultView };
  el.dispatchEvent(new PointerEvent("pointerdown", { ...at, pointerType: "mouse", isPrimary: true }));
  el.dispatchEvent(new MouseEvent("mousedown", at));
  el.dispatchEvent(new PointerEvent("pointerup", { ...at, pointerType: "mouse", isPrimary: true }));
  el.dispatchEvent(new MouseEvent("mouseup", at));
  el.dispatchEvent(new MouseEvent("click", at));
}

/** The message the page shows under a box that has no accepted value ("Please provide institution"), or "". */
function boxError(input: HTMLInputElement): string {
  let host = shadowHost(input);
  while (host) {
    if (host.getAttribute("label")) {
      const m = /please (?:provide|enter|select|choose)[^.!?]*/i.exec(clean(deepText(host)));
      return m ? m[0].trim() : host.getAttribute("invalid") === "true" || host.getAttribute("aria-invalid") === "true" ? "marked invalid" : "";
    }
    host = shadowHost(host);
  }
  return "";
}

function key(input: HTMLInputElement, name: string, code: number): void {
  const init = { key: name, code: name, keyCode: code, which: code, bubbles: true, composed: true, cancelable: true };
  input.dispatchEvent(new KeyboardEvent("keydown", init));
  input.dispatchEvent(new KeyboardEvent("keyup", init));
}

type How = "click" | "keys";

/** Waits until the suggestion rows have stopped being redrawn (the same row elements for 1.2 seconds, at most 7 seconds). */
async function settled(read: () => Row[]): Promise<void> {
  let last = read().map((r) => r.el);
  let since = Date.now();
  const end = Date.now() + 7000;
  while (Date.now() < end && Date.now() - since < 1200) {
    await sleep(200);
    const now = read().map((r) => r.el);
    if (now.length !== last.length || now.some((el, i) => el !== last[i])) {
      last = now;
      since = Date.now();
    }
  }
}

async function pickOnce(input: HTMLInputElement, typeText: string, choose: Chooser, how: How): Promise<boolean> {
  why = "";
  typed(input, typeText.trim());
  const id = input.getAttribute("aria-controls");
  const read = (): Row[] => {
    if (!id) return [];
    const list = deepQueryAll<HTMLElement>(input.ownerDocument, `#${CSS.escape(id)}`)[0];
    return list ? inside(list, "spl-select-option").map((el) => ({ el, text: clean(deepText(el)) })) : [];
  };
  await waitFor(() => (read().length > 0 ? true : null), 32, 125);
  await settled(read);
  let rows = read();
  let pick = choose(rows);
  if (!pick) {
    await sleep(900);
    await settled(read);
    rows = read();
    pick = choose(rows);
  }
  const closed = () => input.getAttribute("aria-expanded") === "false";
  if (pick) {
    if (how === "click") {
      // The list is redrawn when later suggestions arrive, which makes a row picked earlier a dead one: pick from the
      // current rows each time, and count it done only when the page closes the list.
      for (let attempt = 0; attempt < 3; attempt++) {
        if (attempt > 0) {
          await settled(read);
          rows = read();
          pick = choose(rows);
          if (!pick) break;
        }
        press(pick);
        await sleep(350);
        if (closed()) break;
        pick.click(); // the plain click, in case the full press was not enough
        await sleep(350);
        if (closed()) break;
      }
    } else {
      // The way a person would with the keyboard: arrow down to the row, then Enter.
      input.focus();
      const at = Math.max(0, rows.findIndex((r) => r.el === pick));
      for (let i = 0; i < at; i++) {
        key(input, "ArrowDown", 40);
        await sleep(80);
      }
      key(input, "Enter", 13);
    }
    await sleep(400);
    if (clean(input.value) !== "") {
      // Leaving the box makes the page check it: a pick it did not accept brings back its error or empties the box.
      input.blur();
      input.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
      input.dispatchEvent(new FocusEvent("focusout", { bubbles: true, composed: true }));
      await sleep(500);
      const error = boxError(input);
      if (clean(input.value) !== "" && !error && !(input.getAttribute("aria-expanded") === "true")) return true;
      why = error ? `the ${how} pick was not accepted: ${error}` : input.getAttribute("aria-expanded") === "true" ? `the ${how} pick left the list open` : `the ${how} pick did not stay`;
    }
  }
  if (!why) {
    const seen = read();
    why = seen.length === 0 ? "no suggestions appeared" : `saw ${seen.length}: ${seen.slice(0, 3).map((r) => clean(r.text).slice(0, 40)).join(" | ")}`;
  }
  typed(input, "");
  input.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
  return false;
}

/** A search box: tries picking the row with a click, then with the keyboard. True only when the page accepted the pick. */
async function pickRow(input: HTMLInputElement, typeText: string, choose: Chooser): Promise<boolean> {
  if (await pickOnce(input, typeText, choose, "click")) return true;
  const first = why;
  if (await pickOnce(input, typeText, choose, "keys")) return true;
  why = `${first}; ${why}`;
  return false;
}

/** A suggestion row, as opposed to the "Cannot find your city? Click here to fill in manually" line at the end of a place list. */
const isSuggestion = (r: Row) => !/cannot find|click here|fill in manually/i.test(r.text);

/** The top suggestion, whatever it is: the person's rule is to type the word and take the first option the page offers. */
const topRow: Chooser = (rows) => rows.find(isSuggestion)?.el ?? null;

/**
 * Institution: the top suggestion from the page's own school list. A line that merely repeats what was typed (the page
 * adds those for text it does not know) is skipped when a real school is listed, because only schools can be saved.
 */
const topSchool: Chooser = (rows) => {
  const real = rows.filter(isSuggestion);
  return (real.find((r) => databaseName(r.text) !== null) ?? real[0])?.el ?? null;
};

/** "Boston, MA" -> what to type and which rows ("Boston, MA, US") are that city and state. */
function place(loc: string): { typeText: string; choose: Chooser } {
  const m = /^\s*([^,]+?)\s*,\s*([A-Za-z]{2})\b/.exec(loc);
  const city = (m ? m[1] : loc.split(",")[0]).trim();
  return {
    typeText: m ? `${city}, ${m[2]}` : city,
    choose: topRow,
  };
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
  // The picker's own parsed date lives on the page's side; Chrome's extension sandbox cannot read it (undefined), so
  // only an explicit empty answer counts as "not understood".
  const parsed = host ? (host as unknown as { value?: unknown }).value : true;
  return input.value === text && parsed !== null && parsed !== false && parsed !== "";
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

async function fillTypeahead(
  p: Progress,
  el: Box | null,
  label: string,
  value: string | null | undefined,
  required: boolean,
  how: "exact" | "school" | "place" = "exact",
): Promise<void> {
  if (!el || !value?.trim()) {
    if (required) p.needs.push(label);
    return;
  }
  const input = el as HTMLInputElement;
  let done: boolean;
  if (how === "place") {
    const w = place(value);
    done = await pickRow(input, w.typeText, w.choose);
  } else {
    done = await pickRow(input, value, how === "school" ? topSchool : topRow);
  }
  if (done) ok(p, label);
  // Optional boxes that cannot be matched are left empty so the entry can still be saved.
  else if (required) p.needs.push(`${label} (pick it from the list; ${why})`);
}

async function fillDate(p: Progress, el: HTMLInputElement | null, label: string, value: string | null | undefined, required: boolean): Promise<void> {
  if (!el) return;
  if (value && (await writeMonth(el, value))) ok(p, label);
  else if (required) p.needs.push(`${label} (month and year)`);
}

async function fillJob(form: Element, job: ApplyExperience, p: Progress): Promise<void> {
  await fillTypeahead(p, box(form, "Title"), "Title", job.title, true);
  await fillTypeahead(p, box(form, "Company"), "Company", job.employer, false);
  await fillTypeahead(p, box(form, "Office location"), "Office location", job.location, false, "place");
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
  await fillTypeahead(p, box(form, "Institution"), "Institution", school.institution, true, "school");
  await fillTypeahead(p, box(form, "School location"), "School location", (school as ApplyEducation & { location?: string | null }).location, false, "place");
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
    const errors = Array.from(new Set(clean(deepText(form)).match(/please (?:provide|enter|select|choose)[^.!?]*/gi) ?? [])).slice(0, 3);
    flag(report, `${tag}: finish and save this entry${errors.length ? ` (${errors.join("; ")})` : ""}`);
    return false;
  }
  report.filled.push(`${tag}: saved`);
  await sleep(500); // the page settles before the next Add
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

/** The City box at the top: typed from the saved location, then the one suggestion that is that city and state. */
async function fillCity(doc: Document, ctx: ApplyContext, report: FillReport): Promise<void> {
  const loc = ctx.candidate.location?.trim();
  if (!loc) return;
  const input = deepQueryAll<HTMLInputElement>(doc, "input").find(
    (e) => e.type === "text" && e.getAttribute("role") === "combobox" && labelOf(e).toLowerCase() === "city",
  );
  if (!input || input.value.trim() !== "") return;
  const host = deepQueryAll<HTMLElement>(doc, "spl-autocomplete").find((h) => (h.getAttribute("label") ?? "").toLowerCase() === "city");
  const w = place(loc);
  if (await pickRow(input, w.typeText, w.choose)) {
    report.filled.push("City");
    if (host) mark(host, "filled");
  } else {
    flag(report, "City (pick it from the list)");
    if (host) mark(host, "flagged");
  }
}

/** The actual work: City, then Experience, then Education. Runs in whichever JavaScript world it is given. */
export async function runSmartRecruitersHistory(doc: Document, ctx: ApplyContext, report: FillReport): Promise<void> {
  await fillCity(doc, ctx, report);
  await fillSection(doc, "experience", (ctx.experience ?? []).slice(0, MAX_JOBS), report);
  await fillSection(doc, "education", (ctx.education ?? []).slice(0, MAX_SCHOOLS), report);
}

/**
 * Chrome runs an extension's scripts in a separate JavaScript world from the page's own. SmartRecruiters' search boxes
 * only take a picked suggestion when the click comes from the page's own world, so on that site the work is handed to a
 * small helper that runs there (content/sr-main.js, declared in the manifest) and the result is handed back. Only the
 * saved places and schools travel with the message. If the helper is not there, the work is done here instead.
 */
async function viaPageWorld(ctx: ApplyContext): Promise<{ filled: string[]; flagged: FillReport["flagged"] } | null> {
  const win = window;
  const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return new Promise((resolve) => {
    let acked = false;
    const finish = (value: { filled: string[]; flagged: FillReport["flagged"] } | null) => {
      win.removeEventListener("message", onMessage);
      clearTimeout(ackTimer);
      clearTimeout(doneTimer);
      resolve(value);
    };
    const onMessage = (event: MessageEvent) => {
      const d = event.data as { source?: string; type?: string; id?: string; report?: { filled: string[]; flagged: FillReport["flagged"] } } | null;
      if (event.source !== win || !d || d.source !== "job-agent-main" || d.id !== id) return;
      if (d.type === "SR_ACK") {
        acked = true;
        clearTimeout(ackTimer);
      } else if (d.type === "SR_DONE") {
        finish(d.report ?? null);
      }
    };
    win.addEventListener("message", onMessage);
    const ackTimer = setTimeout(() => {
      if (!acked) finish(null);
    }, 1200);
    const doneTimer = setTimeout(() => finish(null), 300_000);
    win.postMessage(
      {
        source: "job-agent",
        type: "SR_HISTORY",
        id,
        ctx: { candidate: { location: ctx.candidate.location }, experience: ctx.experience ?? [], education: ctx.education ?? [] },
      },
      win.location.origin,
    );
  });
}

export async function fillSmartRecruitersHistory(doc: Document, ctx: ApplyContext, report: FillReport): Promise<void> {
  if (doc.location?.hostname !== "jobs.smartrecruiters.com") return;
  const away = doc.defaultView === window ? await viaPageWorld(ctx) : null;
  if (away) {
    report.filled.push(...away.filled);
    report.flagged.push(...away.flagged);
    return;
  }
  await runSmartRecruitersHistory(doc, ctx, report);
}
