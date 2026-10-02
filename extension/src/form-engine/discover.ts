/**
 * Finds the fields on a page and works out each one's label, whether it is
 * required, and its choices. Everything is read from the page as it is; no
 * values are written here.
 */

export type FieldKind = "text" | "textarea" | "select" | "combobox" | "radio" | "checkbox" | "file" | "yesno" | "dropdown";

export interface FormField {
  kind: FieldKind;
  /** The element to type into or set. For a radio group, the first radio. */
  el: HTMLElement;
  /** Every radio in the group (radio kind only). */
  group: HTMLInputElement[];
  /** The Yes and No buttons (yesno kind only). */
  buttons?: HTMLElement[];
  /** The element to outline on the page. */
  outlineEl: HTMLElement;
  label: string;
  name: string;
  id: string;
  autocomplete: string;
  inputType: string;
  required: boolean;
  options: string[];
}

const SKIP_TYPES = new Set(["hidden", "submit", "button", "image", "reset"]);

function clean(text: string | null | undefined): string {
  return (text ?? "")
    .replace(/[*✱∗]/g, " ")
    .replace(/\(\s*required\s*\)/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Text of a label element without the text of controls nested inside it. */
function labelText(label: Element): string {
  const copy = label.cloneNode(true) as Element;
  copy.querySelectorAll("input, select, textarea, option, button, script, style").forEach((n) => n.remove());
  return copy.textContent ?? "";
}

function byId(doc: Document, ids: string): string {
  return ids
    .split(/\s+/)
    .map((id) => doc.getElementById(id))
    .filter((n): n is HTMLElement => !!n)
    .map((n) => labelText(n))
    .join(" ");
}

function rawLabel(el: HTMLElement, doc: Document): string {
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const t = byId(doc, labelledBy);
    if (clean(t)) return t;
  }
  if (el.id) {
    const forLabel = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (forLabel && clean(labelText(forLabel))) return labelText(forLabel);
  }
  const aria = el.getAttribute("aria-label");
  if (clean(aria)) return aria as string;
  const wrapping = el.closest("label");
  if (wrapping && clean(labelText(wrapping))) return labelText(wrapping);
  // Some forms (Ashby) wrap each question in a field entry whose label is not linked to the box.
  const entryLabel = el.closest("[class*='field-entry'], [class*='fieldEntry']")?.querySelector("label");
  if (entryLabel && clean(labelText(entryLabel))) return labelText(entryLabel);
  return "";
}

/** True when the question's own label is styled as required (the star is often CSS, not text). */
function entryRequired(el: HTMLElement): boolean {
  const label = el.closest("[class*='field-entry'], [class*='fieldEntry']")?.querySelector("label");
  return !!label && /required/i.test(label.className);
}

function groupLabel(first: HTMLElement, doc: Document): string {
  const group = first.closest("fieldset, [role='radiogroup'], [role='group']");
  if (group) {
    const legend = group.querySelector("legend");
    if (legend && clean(legend.textContent)) return legend.textContent as string;
    const labelledBy = group.getAttribute("aria-labelledby");
    if (labelledBy && clean(byId(doc, labelledBy))) return byId(doc, labelledBy);
    const aria = group.getAttribute("aria-label");
    if (clean(aria)) return aria as string;
    const heading = group.querySelector("label:not([for]), .label, [class*='label']");
    if (heading && clean(heading.textContent) && !heading.contains(first) && !heading.querySelector("input")) {
      return heading.textContent as string;
    }
  }
  return "";
}

function isVisible(el: HTMLElement): boolean {
  if (el.closest("[hidden], [aria-hidden='true']")) return false;
  const style = el.ownerDocument.defaultView?.getComputedStyle(el);
  if (!style) return true;
  if (style.display === "none" || style.visibility === "hidden") return false;
  return true;
}

function looksRequired(el: HTMLElement, raw: string, groupEl?: Element | null): boolean {
  if ((el as HTMLInputElement).required || el.getAttribute("aria-required") === "true") return true;
  if (entryRequired(el)) return true;
  if (/\*|✱|\(\s*required\s*\)/i.test(raw)) return true;
  if (groupEl && /\*|\(\s*required\s*\)/i.test(groupEl.textContent ?? "") && groupEl.querySelector("legend, label")) {
    const heading = groupEl.querySelector("legend, label");
    return /\*|\(\s*required\s*\)/i.test(heading?.textContent ?? "");
  }
  return false;
}

export function discoverFields(doc: Document): FormField[] {
  const fields: FormField[] = [];
  const seenRadioGroups = new Set<string>();

  const controls = Array.from(doc.querySelectorAll<HTMLElement>("input, textarea, select"));
  for (const el of controls) {
    const tag = el.tagName.toLowerCase();
    const inputType = tag === "input" ? ((el as HTMLInputElement).type || "text").toLowerCase() : tag;
    if (tag === "input" && SKIP_TYPES.has(inputType)) continue;
    if ((el as HTMLInputElement).disabled || (el as HTMLInputElement).readOnly) continue;
    const name = el.getAttribute("name") || el.getAttribute("data-automation-id") || "";
    if (/recaptcha|captcha|honeypot/i.test(`${name} ${el.id}`)) continue;
    if (inputType !== "file" && !isVisible(el)) continue;
    // react-select keeps a hidden "requiredInput" twin next to every combobox.
    if (el.getAttribute("tabindex") === "-1" && el.getAttribute("role") !== "combobox" && inputType !== "file") continue;

    const autocomplete = (el.getAttribute("autocomplete") ?? "").toLowerCase();

    if (inputType === "radio") {
      const radio = el as HTMLInputElement;
      const groupKey = radio.name || radio.id;
      if (!groupKey || seenRadioGroups.has(groupKey)) continue;
      seenRadioGroups.add(groupKey);
      const group = Array.from(doc.querySelectorAll<HTMLInputElement>(`input[type="radio"]`)).filter(
        (r) => r.name === radio.name,
      );
      const raw = groupLabel(radio, doc);
      const groupEl = radio.closest("fieldset, [role='radiogroup'], [role='group']");
      fields.push({
        kind: "radio",
        el: radio,
        group,
        outlineEl: (groupEl as HTMLElement) ?? radio,
        label: clean(raw),
        name,
        id: radio.id,
        autocomplete,
        inputType,
        required: group.some((r) => r.required) || looksRequired(radio, raw, groupEl),
        options: group.map((r) => clean(rawLabel(r, doc)) || r.value),
      });
      continue;
    }

    if (inputType === "checkbox") {
      const raw = rawLabel(el, doc);
      fields.push({
        kind: "checkbox",
        el,
        group: [],
        outlineEl: el,
        label: clean(raw),
        name,
        id: el.id,
        autocomplete,
        inputType,
        required: looksRequired(el, raw),
        options: [],
      });
      continue;
    }

    const raw = rawLabel(el, doc) || el.getAttribute("placeholder") || "";
    let label = clean(raw);
    // A hidden upload input is often unlabeled; its id/name ("resume") still says what it is.
    if (!label && inputType === "file" && el.closest("[data-automation-id*='resume' i]")) label = "Resume";
    // Workday's upload box has no label of its own; the section heading above it ("Resume/CV") names it.
    if (!label && inputType === "file" && el.getAttribute("data-automation-id") === "file-upload-input-ref") {
      const heads = Array.from(doc.querySelectorAll("h2, h3, h4")).filter(
        (h) => h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
      label = clean(heads[heads.length - 1]?.textContent);
    }
    if (!label && inputType === "file") label = clean(`${name} ${el.id}`.replace(/[_-]+/g, " ")) || "File upload";
    if (!label) continue; // unlabeled controls (search boxes, country pickers) are not questions

    const isCombobox = tag === "input" && (el.getAttribute("role") === "combobox" || el.getAttribute("data-uxi-widget-type") === "selectinput");
    let kind: FieldKind = "text";
    let options: string[] = [];
    if (inputType === "file") kind = "file";
    else if (tag === "textarea") kind = "textarea";
    else if (tag === "select") {
      kind = "select";
      options = Array.from((el as HTMLSelectElement).options)
        .filter((o) => o.value !== "" && clean(o.textContent))
        .map((o) => clean(o.textContent));
    } else if (isCombobox) kind = "combobox";

    const wrapper =
      kind === "file" || kind === "combobox"
        ? ((el.closest("[class*='select'], [class*='upload'], [class*='file'], .field, .input-wrapper") as HTMLElement | null) ??
          el.parentElement ??
          el)
        : el;

    fields.push({
      kind,
      el,
      group: [],
      outlineEl: wrapper,
      label,
      name,
      id: el.id,
      autocomplete,
      inputType,
      required: looksRequired(el, raw),
      options,
    });
  }

  // Yes/No questions drawn as a pair of toggle buttons (the real checkbox behind them is hidden).
  const seenGroups = new Set<HTMLElement>();
  for (const btn of Array.from(doc.querySelectorAll<HTMLElement>("button[aria-pressed]"))) {
    const text = clean(btn.textContent).toLowerCase();
    if (text !== "yes" && text !== "no") continue;
    const container = btn.parentElement;
    if (!container || seenGroups.has(container)) continue;
    const buttons = Array.from(container.querySelectorAll<HTMLElement>("button[aria-pressed]")).filter((b) =>
      ["yes", "no"].includes(clean(b.textContent).toLowerCase()),
    );
    if (buttons.length !== 2 || !isVisible(buttons[0])) continue;
    seenGroups.add(container);
    const entry = container.closest("[class*='field-entry'], [class*='fieldEntry']");
    const raw = entry?.querySelector("label")?.textContent ?? "";
    if (!clean(raw)) continue;
    fields.push({
      kind: "yesno",
      el: buttons[0],
      group: [],
      buttons,
      outlineEl: container,
      label: clean(raw),
      name: "",
      id: "",
      autocomplete: "",
      inputType: "yesno",
      required: /required/i.test(entry?.querySelector("label")?.className ?? ""),
      options: buttons.map((b) => clean(b.textContent)),
    });
  }
  // Workday drawn dropdowns: a button that opens a list of options. The list is read and picked later.
  for (const btn of Array.from(doc.querySelectorAll<HTMLElement>("button[aria-haspopup='listbox']"))) {
    if (!isVisible(btn) || (btn as HTMLButtonElement).disabled) continue;
    const raw = rawLabel(btn, doc);
    // Workday's aria-label reads "State Select One Required" or "Country United States of America Required".
    const shown = clean(btn.textContent);
    let label = clean(raw).replace(/\s*required\s*$/i, "").trim();
    if (shown) label = label.replace(new RegExp(`\\s*${shown.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i"), "");
    label = label.replace(/\s*select one\s*$/i, "").trim();
    // Questionnaire dropdowns carry only "Select One Required"; the question itself is the fieldset's legend.
    if (!label) label = clean(btn.closest("fieldset")?.querySelector("legend")?.textContent);
    if (!label) continue;
    fields.push({
      kind: "dropdown",
      el: btn,
      group: [],
      outlineEl: btn,
      label,
      name: btn.getAttribute("data-automation-id") ?? "",
      id: btn.id,
      autocomplete: "",
      inputType: "dropdown",
      required: btn.getAttribute("aria-required") === "true" || /\*|required/i.test(raw),
      options: [],
    });
  }
  return fields;
}
