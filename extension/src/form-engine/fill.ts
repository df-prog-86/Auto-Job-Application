/**
 * Writes values into fields the way a person would, so pages built with
 * React and similar libraries notice the change. Only recognized values are
 * ever written; nothing here clicks a button.
 */

import { normalizeQuestion } from "@/form-engine/canonical";
import type { FormField } from "@/form-engine/discover";
import { safeClick } from "@/form-engine/safety";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function fire(el: HTMLElement, types: string[]): void {
  for (const type of types) el.dispatchEvent(new Event(type, { bubbles: true }));
}

function setNativeValue(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  fire(el, ["input", "change"]);
}

export function currentValue(field: FormField): string {
  switch (field.kind) {
    case "text":
    case "textarea":
    case "combobox":
      return (field.el as HTMLInputElement).value.trim();
    case "select":
      return (field.el as HTMLSelectElement).value.trim();
    case "radio":
      return field.group.some((r) => r.checked) ? "checked" : "";
    case "yesno":
      return field.buttons?.some((b) => b.getAttribute("aria-pressed") === "true") ? "pressed" : "";
    case "dropdown": {
      const text = (field.el.textContent ?? "").replace(/\s+/g, " ").trim();
      return /^select one$/i.test(text) ? "" : text;
    }
    case "file":
      return ((field.el as HTMLInputElement).files?.length ?? 0) > 0 ? "file" : "";
    default:
      return "";
  }
}

function matchOption(options: string[], wanted: string): string | null {
  const w = normalizeQuestion(wanted);
  return (
    options.find((o) => normalizeQuestion(o) === w) ??
    options.find((o) => normalizeQuestion(o).includes(w) && w.length > 2) ??
    null
  );
}

/**
 * Presses a Yes or No toggle. These buttons have no type attribute, which
 * browsers treat as "submit" inside a form, so the form's submit is blocked for
 * the instant of the press: answering a question must never send the application.
 */
async function pressYesNo(button: HTMLElement): Promise<boolean> {
  const text = (button.textContent ?? "").trim().toLowerCase();
  if ((text !== "yes" && text !== "no") || !button.hasAttribute("aria-pressed")) return false;
  const form = button.closest("form");
  const block = (e: Event) => {
    e.preventDefault();
    e.stopImmediatePropagation();
  };
  form?.addEventListener("submit", block, true);
  try {
    button.click();
    await sleep(80);
  } finally {
    form?.removeEventListener("submit", block, true);
  }
  return button.getAttribute("aria-pressed") === "true";
}


const optionNodes = (doc: Document) => Array.from(doc.querySelectorAll<HTMLElement>("[role='option'], [data-automation-id='promptOption']"));

/** Opens a Workday style dropdown button like a mouse would, without ever letting it submit the form. */
async function openDropdown(btn: HTMLElement): Promise<void> {
  if (btn.getAttribute("aria-expanded") === "true") return;
  const form = btn.closest("form");
  const block = (e: Event) => {
    e.preventDefault();
    e.stopImmediatePropagation();
  };
  form?.addEventListener("submit", block, true);
  try {
    const view = btn.ownerDocument.defaultView ?? window;
    const init = { bubbles: true, cancelable: true, button: 0, view };
    btn.dispatchEvent(new PointerEvent("pointerdown", init));
    btn.dispatchEvent(new MouseEvent("mousedown", init));
    btn.dispatchEvent(new PointerEvent("pointerup", init));
    btn.dispatchEvent(new MouseEvent("mouseup", init));
    btn.click();
    await sleep(150);
  } finally {
    form?.removeEventListener("submit", block, true);
  }
}

async function closeDropdown(btn: HTMLElement): Promise<void> {
  btn.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await sleep(80);
}

/** Reads a dropdown button's choices without choosing anything. */
export async function readDropdownOptions(btn: HTMLElement): Promise<string[]> {
  await openDropdown(btn);
  let options: string[] = [];
  for (let i = 0; i < 20 && options.length === 0; i++) {
    await sleep(100);
    options = optionNodes(btn.ownerDocument).map((o) => (o.textContent ?? "").trim()).filter(Boolean);
  }
  await closeDropdown(btn);
  return options;
}

async function fillDropdown(btn: HTMLElement, value: string): Promise<boolean> {
  await openDropdown(btn);
  const wanted = normalizeQuestion(value);
  for (let i = 0; i < 24; i++) {
    await sleep(125);
    const exact = optionNodes(btn.ownerDocument).filter((o) => normalizeQuestion(o.textContent ?? "") === wanted);
    if (exact.length === 1 && safeClick(exact[0])) {
      await sleep(80);
      return true;
    }
  }
  await closeDropdown(btn);
  return false;
}

export interface ComboboxHints {
  /** What to type to narrow the list (the exact entry is still what gets picked). */
  typeText?: string;
  /** Other spellings of the entry to pick, tried as exact matches. */
  alternates?: string[];
}

/**
 * Opens a react-select style box the way a mouse does. Greenhouse's lists
 * ignore typed text until the box has been pressed, so typing alone (even
 * with focus) never brings the menu up.
 */
function pressControl(el: HTMLInputElement): void {
  const control = el.closest<HTMLElement>("[class*='control']") ?? el.parentElement;
  if (!control || control.tagName === "BUTTON") return;
  const view = el.ownerDocument.defaultView ?? window;
  const init = { bubbles: true, cancelable: true, button: 0, view };
  control.dispatchEvent(new PointerEvent("pointerdown", init));
  control.dispatchEvent(new MouseEvent("mousedown", init));
  control.dispatchEvent(new PointerEvent("pointerup", init));
  control.dispatchEvent(new MouseEvent("mouseup", init));
  control.dispatchEvent(new MouseEvent("click", init));
}

const isExpanded = (el: HTMLInputElement) => el.getAttribute("aria-expanded") === "true";

/** Pressing an already open box closes it, so only press a closed one. */
function openCombobox(el: HTMLInputElement): void {
  if (!isExpanded(el)) pressControl(el);
}

function closeCombobox(el: HTMLInputElement): void {
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  if (isExpanded(el)) pressControl(el);
  el.blur();
}

async function fillCombobox(el: HTMLInputElement, value: string, hints: ComboboxHints = {}): Promise<boolean> {
  const doc = el.ownerDocument;
  el.focus();
  openCombobox(el);
  await sleep(150);
  // typeText narrows a long list ("United States") while the exact entry ("United States +1") is what gets picked.
  setNativeValue(el, hints.typeText ?? value);
  const wanted = normalizeQuestion(value);
  const exactSet = new Set([wanted, ...(hints.alternates ?? []).map(normalizeQuestion)]);
  // Place lists load over the network, so give them a few seconds.
  for (let i = 0; i < 40; i++) {
    await sleep(125);
    const options = Array.from(doc.querySelectorAll<HTMLElement>("[role='option']"));
    // An exact match wins. A partial match is used only when exactly one
    // option fits, so "Boston" is never silently resolved to the wrong Boston.
    const norm = (o: HTMLElement) => normalizeQuestion(o.textContent ?? "");
    const starts = options.filter((o) => norm(o).startsWith(wanted));
    const contains = wanted.length > 2 ? options.filter((o) => norm(o).includes(wanted)) : [];
    const pick =
      options.find((o) => exactSet.has(norm(o))) ??
      (starts.length === 1 ? starts[0] : undefined) ??
      (starts.length === 0 && contains.length === 1 ? contains[0] : undefined);
    if (pick && safeClick(pick)) {
      await sleep(60);
      return true;
    }
  }
  setNativeValue(el, ""); // nothing matched: leave the field as we found it
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  el.blur();
  return false;
}

/** Reads the choices a combobox offers, without choosing anything. */
export async function readComboboxOptions(el: HTMLInputElement): Promise<string[]> {
  const doc = el.ownerDocument;
  el.focus();
  openCombobox(el);
  let options: string[] = [];
  // The list can take a moment to appear; wait for it rather than reading it empty.
  for (let i = 0; i < 20 && options.length === 0; i++) {
    await sleep(100);
    options = Array.from(doc.querySelectorAll<HTMLElement>("[role='option']"))
      .map((o) => (o.textContent ?? "").trim())
      .filter(Boolean);
  }
  closeCombobox(el);
  await sleep(100);
  return options;
}

export async function fillField(field: FormField, value: string, hints?: ComboboxHints): Promise<boolean> {
  switch (field.kind) {
    case "text":
    case "textarea": {
      setNativeValue(field.el as HTMLInputElement | HTMLTextAreaElement, value);
      return true;
    }
    case "select": {
      const select = field.el as HTMLSelectElement;
      const hit = matchOption(field.options, value);
      if (!hit) return false;
      const option = Array.from(select.options).find((o) => o.textContent && normalizeQuestion(o.textContent) === normalizeQuestion(hit));
      if (!option) return false;
      select.value = option.value;
      fire(select, ["input", "change"]);
      return true;
    }
    case "radio": {
      const index = field.options.findIndex((o) => normalizeQuestion(o) === normalizeQuestion(value));
      const radio = index >= 0 ? field.group[index] : undefined;
      return radio ? safeClick(radio) : false;
    }
    case "yesno": {
      const wanted = normalizeQuestion(value);
      const button = field.buttons?.find((b) => normalizeQuestion(b.textContent ?? "") === wanted);
      return button ? pressYesNo(button) : false;
    }
    case "dropdown":
      return fillDropdown(field.el, value);
    case "combobox":
      return fillCombobox(field.el as HTMLInputElement, value, hints);
    default:
      return false;
  }
}

export function base64ToFile(base64: string, filename: string): File {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const type = filename.toLowerCase().endsWith(".docx")
    ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    : "application/octet-stream";
  return new File([bytes], filename, { type });
}

export function fillFile(field: FormField, file: File): boolean {
  const input = field.el as HTMLInputElement;
  try {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    fire(input, ["input", "change"]);
    return (input.files?.length ?? 0) > 0;
  } catch {
    return false;
  }
}
