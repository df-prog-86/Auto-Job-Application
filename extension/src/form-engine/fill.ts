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

async function fillCombobox(el: HTMLInputElement, value: string, typeText?: string): Promise<boolean> {
  const doc = el.ownerDocument;
  el.focus();
  // typeText narrows a long list ("United States") while the exact entry ("United States +1") is what gets picked.
  setNativeValue(el, typeText ?? value);
  const wanted = normalizeQuestion(value);
  for (let i = 0; i < 12; i++) {
    await sleep(120);
    const options = Array.from(doc.querySelectorAll<HTMLElement>("[role='option']"));
    // An exact match wins. A partial match is used only when exactly one
    // option fits, so "Boston" is never silently resolved to the wrong Boston.
    const norm = (o: HTMLElement) => normalizeQuestion(o.textContent ?? "");
    const starts = options.filter((o) => norm(o).startsWith(wanted));
    const contains = wanted.length > 2 ? options.filter((o) => norm(o).includes(wanted)) : [];
    const pick =
      options.find((o) => norm(o) === wanted) ??
      (starts.length === 1 ? starts[0] : undefined) ??
      (starts.length === 0 && contains.length === 1 ? contains[0] : undefined);
    if (pick && safeClick(pick)) {
      await sleep(60);
      return true;
    }
  }
  setNativeValue(el, ""); // nothing matched: leave the field as we found it
  return false;
}

/** Reads the choices a combobox offers, without choosing anything. */
export async function readComboboxOptions(el: HTMLInputElement): Promise<string[]> {
  const doc = el.ownerDocument;
  el.focus();
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  await sleep(200);
  const options = Array.from(doc.querySelectorAll<HTMLElement>("[role='option']")).map((o) => (o.textContent ?? "").trim());
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  el.blur();
  return options.filter(Boolean);
}

export async function fillField(field: FormField, value: string, typeText?: string): Promise<boolean> {
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
    case "combobox":
      return fillCombobox(field.el as HTMLInputElement, value, typeText);
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
