/**
 * Runs inside the SmartRecruiters page itself (declared in manifest.json with world MAIN), because the site's search
 * boxes only accept a picked suggestion when the click comes from the page's own JavaScript world. It does nothing until
 * the extension's fill script sends it the saved work history (see viaPageWorld in smartrecruiters-history.ts), then
 * fills City, Experience and Education and sends back what it did. It never submits anything.
 */

import { runSmartRecruitersHistory, setMouseRelay } from "@/form-engine/smartrecruiters-history";
import type { ApplyContext, FillReport } from "@/form-engine/types";

const seen = new Set<string>();

window.addEventListener("message", (event: MessageEvent) => {
  const d = event.data as { source?: string; type?: string; id?: string; ctx?: ApplyContext } | null;
  if (event.source !== window || !d || d.source !== "job-agent" || d.type !== "SR_HISTORY" || typeof d.id !== "string" || !d.ctx) return;
  if (seen.has(d.id)) return;
  seen.add(d.id);
  const id = d.id;
  const reply = (type: string, report?: unknown) => window.postMessage({ source: "job-agent-main", type, id, report }, window.location.origin);
  reply("SR_ACK");
  // A real mouse click is something only the extension can ask Chrome for: the request goes to its script and back.
  setMouseRelay(
    (x, y) =>
      new Promise((resolve) => {
        const req = Math.random().toString(36).slice(2);
        const done = (e: MessageEvent) => {
          const r = e.data as { source?: string; type?: string; req?: string; ok?: boolean } | null;
          if (e.source !== window || !r || r.source !== "job-agent" || r.type !== "SR_CLICKED" || r.req !== req) return;
          window.removeEventListener("message", done);
          clearTimeout(timer);
          resolve(r.ok === true);
        };
        const timer = setTimeout(() => {
          window.removeEventListener("message", done);
          resolve(false);
        }, 8000);
        window.addEventListener("message", done);
        window.postMessage({ source: "job-agent-main", type: "SR_CLICK", id, req, x, y }, window.location.origin);
      }),
  );
  const report: FillReport = { filled: [], flagged: [], leftBlank: 0, alreadyFilled: 0, voluntarySkipped: 0 };
  void runSmartRecruitersHistory(document, d.ctx, report)
    .catch(() => {
      /* whatever was filled so far is still reported */
    })
    .finally(() => reply("SR_DONE", { filled: report.filled, flagged: report.flagged }));
});
