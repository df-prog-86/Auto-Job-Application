/**
 * Runs inside the SmartRecruiters page itself (declared in manifest.json with world MAIN), because the site's search
 * boxes only accept a picked suggestion when the click comes from the page's own JavaScript world. It does nothing until
 * the extension's fill script sends it the saved work history (see viaPageWorld in smartrecruiters-history.ts), then
 * fills City, Experience and Education and sends back what it did. It never submits anything.
 */

import { runSmartRecruitersHistory } from "@/form-engine/smartrecruiters-history";
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
  const report: FillReport = { filled: [], flagged: [], leftBlank: 0, alreadyFilled: 0, voluntarySkipped: 0 };
  void runSmartRecruitersHistory(document, d.ctx, report)
    .catch(() => {
      /* whatever was filled so far is still reported */
    })
    .finally(() => reply("SR_DONE", { filled: report.filled, flagged: report.flagged }));
});
