/**
 * Injected into the application tab only when the candidate clicks "Fill
 * this application" (see service-worker.ts). It defines one function and
 * does nothing until it is called.
 */

import { fillPage } from "@/form-engine/engine";
import type { ResumePayload } from "@/form-engine/engine";
import type { ApplyContext, FillReport } from "@/form-engine/types";

declare global {
  interface Window {
    __jobAgentFill?: (ctx: ApplyContext, resume: ResumePayload | null) => Promise<FillReport>;
  }
}

window.__jobAgentFill = (ctx, resume) => fillPage(document, ctx, resume);
