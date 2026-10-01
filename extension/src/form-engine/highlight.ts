/** Green outlines on what was filled, amber on what needs the candidate, plus a small summary banner. */

const STYLE_ID = "job-agent-style";
const BANNER_ID = "job-agent-banner";

const CSS = `
[data-job-agent="filled"] { outline: 2px solid #12b76a !important; outline-offset: 2px !important; border-radius: 6px; }
[data-job-agent="flagged"] { outline: 2px dashed #f59e0b !important; outline-offset: 2px !important; border-radius: 6px; background-color: rgba(245, 158, 11, 0.07) !important; }
#${BANNER_ID} { position: fixed; top: 16px; right: 16px; z-index: 2147483647; width: 300px; padding: 14px 16px; border-radius: 16px; background: #fff; color: #1c1b3a; font: 13px/1.45 ui-rounded, system-ui, -apple-system, sans-serif; box-shadow: 0 8px 30px rgba(60, 50, 140, 0.25); border: 1px solid #e8e6ff; }
#${BANNER_ID} strong { display: block; font-size: 14px; margin-bottom: 4px; }
#${BANNER_ID} button { margin-top: 8px; border: 0; background: #f3f2ff; color: #3b36b8; border-radius: 999px; padding: 5px 12px; font-weight: 600; cursor: pointer; }
`;

export function mark(el: HTMLElement, state: "filled" | "flagged"): void {
  ensureStyle(el.ownerDocument);
  el.setAttribute("data-job-agent", state);
}

function ensureStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.appendChild(style);
}

export function clearMarks(doc: Document): void {
  doc.querySelectorAll("[data-job-agent]").forEach((el) => el.removeAttribute("data-job-agent"));
  doc.getElementById(BANNER_ID)?.remove();
}

export function showBanner(doc: Document, filled: number, needYou: number): void {
  ensureStyle(doc);
  doc.getElementById(BANNER_ID)?.remove();
  const banner = doc.createElement("div");
  banner.id = BANNER_ID;
  const title = doc.createElement("strong");
  title.textContent = `Filled ${filled} ${filled === 1 ? "field" : "fields"}`;
  const body = doc.createElement("div");
  body.textContent =
    needYou > 0
      ? `${needYou} ${needYou === 1 ? "needs" : "need"} you (dashed amber). Check everything before you submit. Job Agent never submits for you.`
      : "Check everything before you submit. Job Agent never submits for you.";
  const close = doc.createElement("button");
  close.type = "button";
  close.textContent = "Clear highlights";
  close.addEventListener("click", () => clearMarks(doc));
  banner.append(title, body, close);
  doc.body.appendChild(banner);
}
