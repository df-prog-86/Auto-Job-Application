/**
 * Message contract between the popup and the service worker. Content
 * scripts are not part of this contract yet — see spec §32/§43; adapter
 * scripts (Milestone 6+) get their own, narrower message types once they
 * exist, and are injected programmatically via chrome.scripting rather than
 * declared statically in manifest.json, so ATS host permissions are added
 * incrementally per adapter instead of granted up front.
 */

export type ExtensionMessage =
  | { type: "PAIR"; pairingSecret: string }
  | { type: "GET_PAIRING_STATE" }
  | { type: "GET_AUTOMATION_STATUS" }
  | { type: "TOGGLE_AUTOMATION" }
  | { type: "CAPTURE_JOB"; tabId: number }
  | { type: "FILL_PAGE"; tabId: number; jobId?: number }
  | { type: "COMPLETE_APPLICATION"; jobId: number; url: string };

export interface PairResult {
  ok: boolean;
  error?: string;
}

export interface PairingStateResult {
  paired: boolean;
}

export interface AutomationStatusResult {
  ok: boolean;
  mode?: "PAUSED" | "REVIEW" | "AUTO";
  error?: string;
}

export interface CaptureJobResult {
  ok: boolean;
  jobTitle?: string;
  company?: string;
  error?: string;
}

/** What the injected page-reader script hands back to the service worker. */
export interface CapturedPage {
  url: string;
  title: string;
  jsonLd: string[];
  bodyText: string;
}

export interface FillJobChoice {
  id: number;
  title: string;
  company: string;
}

export interface FillPageResult {
  ok: boolean;
  error?: string;
  /** Why nothing was filled (job not saved, no resume yet, ...). */
  problem?: string;
  /** Saved jobs to pick from when the page didn't match one. */
  choices?: FillJobChoice[];
  jobTitle?: string;
  company?: string;
  filledCount?: number;
  flagged?: string[];
  leftBlank?: number;
  alreadyFilled?: number;
  voluntarySkipped?: number;
  pagesAdvanced?: number;
  stoppedBecause?: string;
}
