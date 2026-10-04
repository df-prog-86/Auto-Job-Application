/**
 * "Remember my answer". Questions the engine could not answer are tracked. When the person answers one
 * by hand, a small note offers to keep the answer for next time. Nothing is saved unless they press
 * "Save for next time", and agreements, secrets and history questions are never offered.
 */

import { normalizeQuestion } from "@/form-engine/canonical";
import type { FormField } from "@/form-engine/discover";

/** Same idea as the backend list: these are answered fresh each time. */
const NEVER =
  /password|passcode|\bssn\b|social security|card number|account number|routing|passport|certify|attest|acknowledg|\bagree\b|consent|signature|sign here|i understand|terms|\b(ever|convicted|arrested|felony|failed)\b/i;

const KINDS = new Set(["text", "select", "dropdown", "radio", "yesno"]);

export interface LearnedAnswer {
  label: string;
  value: string;
}

const tracked = new Map<string, FormField>();
const settled = new Set<string>(); // offered once (saved or dismissed): never asked again on this page

export function rememberable(label: string): boolean {
  const l = label.trim();
  return l.length >= 4 && l.length <= 300 && !NEVER.test(l) && normalizeQuestion(l) !== "";
}

export function trackFlagged(field: FormField): void {
  if (!KINDS.has(field.kind) || !rememberable(field.label)) return;
  const key = normalizeQuestion(field.label);
  if (!settled.has(key)) tracked.set(key, field);
}

/** What the person has chosen or typed, as the words a later visit can match. */
export function chosenText(field: FormField): string {
  switch (field.kind) {
    case "text":
      return (field.el as HTMLInputElement).value.trim().slice(0, 120);
    case "select": {
      const s = field.el as HTMLSelectElement;
      return (s.selectedOptions[0]?.textContent ?? "").trim();
    }
    case "dropdown": {
      const text = (field.el.textContent ?? "").replace(/\s+/g, " ").trim();
      return /^select one$/i.test(text) ? "" : text;
    }
    case "radio": {
      const i = field.group.findIndex((r) => r.checked);
      return i >= 0 ? (field.options[i] ?? "").trim() : "";
    }
    case "yesno":
      return (field.buttons?.find((b) => b.getAttribute("aria-pressed") === "true")?.textContent ?? "").trim();
    default:
      return "";
  }
}

/** Tracked questions that now have an answer typed in by the person. */
export function answeredByPerson(): (LearnedAnswer & { key: string })[] {
  const out: (LearnedAnswer & { key: string })[] = [];
  for (const [key, field] of tracked) {
    if (!field.el.isConnected) continue;
    const value = chosenText(field);
    if (value) out.push({ key, label: field.label.replace(/\s+/g, " ").trim(), value });
  }
  return out;
}

const BOX_ID = "job-agent-learn-note";

function removeNote(doc: Document): void {
  doc.getElementById(BOX_ID)?.remove();
}

function showNote(doc: Document, items: (LearnedAnswer & { key: string })[], onSave: (a: LearnedAnswer[]) => void): void {
  removeNote(doc);
  const box = doc.createElement("div");
  box.id = BOX_ID;
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "Remember your answers");
  Object.assign(box.style, {
    position: "fixed", right: "16px", bottom: "88px", zIndex: "2147483647", maxWidth: "340px",
    background: "#ffffff", color: "#1a1a1a", border: "1px solid #c9d3e0", borderRadius: "12px",
    boxShadow: "0 6px 24px rgba(0,0,0,.18)", padding: "12px 14px", font: "13px/1.4 system-ui, sans-serif",
  } as Partial<CSSStyleDeclaration>);

  const title = doc.createElement("div");
  title.style.fontWeight = "600";
  title.textContent = items.length === 1 ? "Remember this answer?" : `Remember these ${items.length} answers?`;
  box.appendChild(title);

  const list = doc.createElement("ul");
  list.style.cssText = "margin:6px 0 10px;padding-left:16px";
  for (const it of items.slice(0, 4)) {
    const li = doc.createElement("li");
    li.textContent = `${it.label.length > 70 ? `${it.label.slice(0, 67)}...` : it.label}: ${it.value}`;
    list.appendChild(li);
  }
  if (items.length > 4) {
    const more = doc.createElement("li");
    more.textContent = `and ${items.length - 4} more`;
    list.appendChild(more);
  }
  box.appendChild(list);

  const button = (text: string, primary: boolean, click: () => void) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.style.cssText = `margin-right:8px;padding:6px 12px;border-radius:8px;cursor:pointer;font:inherit;border:1px solid ${
      primary ? "#1d4ed8" : "#c9d3e0"
    };background:${primary ? "#1d4ed8" : "#fff"};color:${primary ? "#fff" : "#1a1a1a"}`;
    b.addEventListener("click", click);
    return b;
  };
  box.appendChild(
    button("Save for next time", true, () => {
      for (const it of items) settled.add(it.key);
      onSave(items.map(({ label, value }) => ({ label, value })));
      removeNote(doc);
    }),
  );
  box.appendChild(
    button("Not now", false, () => {
      for (const it of items) settled.add(it.key);
      removeNote(doc);
    }),
  );
  doc.body.appendChild(box);
}

let timer: number | undefined;

/**
 * Checks every 1.5 s. When the same answers have been sitting there for two checks (the person has stopped
 * typing), the note appears. Starting again replaces the earlier timer.
 */
export function startLearning(doc: Document, onSave: (a: LearnedAnswer[]) => void): void {
  if (timer !== undefined) window.clearInterval(timer);
  let lastSeen = "";
  timer = window.setInterval(() => {
    if (doc.getElementById(BOX_ID)) return;
    const items = answeredByPerson().filter((i) => !settled.has(i.key));
    const sig = items.map((i) => `${i.key}=${i.value}`).join("|");
    if (items.length === 0 || sig !== lastSeen) {
      lastSeen = sig;
      return;
    }
    showNote(doc, items, onSave);
  }, 1500);
}

/** For tests. */
export function resetLearning(): void {
  tracked.clear();
  settled.clear();
  if (timer !== undefined) window.clearInterval(timer);
  timer = undefined;
}
