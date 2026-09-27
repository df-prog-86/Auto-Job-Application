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
  | { type: "TOGGLE_AUTOMATION" };

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
