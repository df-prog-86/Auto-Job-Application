/**
 * SmartRecruiters draws its application form with web components, and the real input boxes sit inside open shadow
 * roots, where document.querySelectorAll cannot see them. These helpers look inside those roots. They are used only
 * on jobs.smartrecruiters.com; every other site is read exactly as before.
 */

/** Every match of `selector` in the page, including inside open shadow roots, in roughly page order. */
export function deepQueryAll<T extends Element>(root: ParentNode, selector: string): T[] {
  const out: T[] = [];
  const visit = (node: ParentNode): void => {
    for (const el of Array.from(node.querySelectorAll("*"))) {
      if (el.matches(selector)) out.push(el as T);
      if (el.shadowRoot) visit(el.shadowRoot);
    }
  };
  visit(root);
  return out;
}

/** The custom element whose shadow root holds this element, or null for an ordinary page element. */
export function shadowHost(el: Element): Element | null {
  const root = el.getRootNode();
  return root instanceof ShadowRoot ? root.host : null;
}

/** True when the element sits inside a shadow root belonging to (or nested under) a custom element with this tag. */
export function insideHost(el: Element, tag: string): boolean {
  let host = shadowHost(el);
  while (host) {
    if (host.tagName.toLowerCase() === tag) return true;
    host = shadowHost(host);
  }
  return false;
}

// SmartRecruiters marks its two upload boxes only by a data-test value. "resume-upload" is the resume itself. The other box
// ("apply-with-resume-container") parses an uploaded resume into the form on its own, so it is deliberately not a field here.
const DROPZONES: Record<string, string> = { "resume-upload": "Resume" };
const CONSENT_TEXT = /privacy|consent|terms|agree|acknowledg/i;

/**
 * The question a shadow-DOM control belongs to, read from the custom element that wraps it (its own label, never a
 * label from an outer wrapper, so a country search box inside the phone field is not mistaken for a second phone box).
 * Empty when the control is not in a shadow root or has no label of its own.
 */
export function deepLabel(el: Element): string {
  const host = shadowHost(el);
  if (!host) return "";
  const own = host.getAttribute("label") ?? host.getAttribute("aria-label");
  if (own && own.trim()) return own;
  const tag = host.tagName.toLowerCase();
  if (tag === "spl-dropzone") return DROPZONES[host.getAttribute("data-test") ?? ""] ?? "";
  if (tag === "spl-checkbox") {
    const text = (host.textContent ?? "").replace(/\s+/g, " ").trim();
    return CONSENT_TEXT.test(text) ? "Privacy notice acknowledgement" : text.slice(0, 200);
  }
  return "";
}
