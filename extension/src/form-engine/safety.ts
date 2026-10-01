/**
 * Hard stops. The engine fills fields; it never submits anything. Nothing
 * here is configurable: a button that looks like a final submit is refused.
 */

const FINAL_ACTION = /^\s*(submit|apply|send|finish|complete|confirm)\b|submit (my )?application|send application/i;

export function isFinalActionText(text: string): boolean {
  return FINAL_ACTION.test(text.trim());
}

/** True when clicking this element could submit a form or send an application. */
export function isSubmitLike(el: Element): boolean {
  const tag = el.tagName.toLowerCase();
  if (tag === "button") {
    const type = (el as HTMLButtonElement).type;
    if (type === "submit" || !el.getAttribute("type")) return true;
    return isFinalActionText(el.textContent ?? "");
  }
  if (tag === "input") {
    const type = (el as HTMLInputElement).type;
    return type === "submit" || type === "image";
  }
  if (tag === "a") return isFinalActionText(el.textContent ?? "");
  return false;
}

/**
 * The only elements the engine is allowed to click: dropdown options,
 * radio buttons and checkboxes that are not a consent box. Everything else,
 * and anything that looks like a submit, is refused.
 */
export function safeClick(el: HTMLElement): boolean {
  if (isSubmitLike(el)) return false;
  const role = el.getAttribute("role");
  const isOption = role === "option" || el.tagName.toLowerCase() === "li";
  const isRadio = el instanceof HTMLInputElement && el.type === "radio";
  if (!isOption && !isRadio) return false;
  const opts = { bubbles: true, cancelable: true, view: window };
  el.dispatchEvent(new MouseEvent("mousedown", opts));
  el.dispatchEvent(new MouseEvent("mouseup", opts));
  el.click();
  return true;
}
