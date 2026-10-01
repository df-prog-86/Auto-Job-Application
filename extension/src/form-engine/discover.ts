/**
 * Finds the fields on a page and works out each one's label, whether it is
 * required, and its choices. Everything is read from the page as it is; no
 * values are written here.
 */

export type FieldKind = "text" | "textarea" | "select" | "combobox" | "radio" | "checkbox" | "file";

export interface FormField {
  kind: FieldKind;
  /** The element to type into or set. For a radio group, the first radio. */
  el: HTMLElement;
  /** Every radio in the group (radio kind only). */
  group: HTMLInputElement[];
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
  return "";
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
    const name = el.getAttribute("name") ?? "";
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
    const label = clean(raw);
    if (!label) continue; // unlabeled controls (search boxes, country pickers) are not questions

    const isCombobox = el.getAttribute("role") === "combobox" && tag === "input";
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
  return fields;
}
