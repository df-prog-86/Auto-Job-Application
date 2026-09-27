/**
 * MV3 service worker. Event-driven only (spec §33): no setInterval, no
 * reliance on module-level variables surviving between invocations — Chrome
 * terminates this worker after ~30s of inactivity, so every handler below
 * re-derives whatever state it needs from chrome.storage or the backend
 * rather than from an in-memory variable.
 *
 * Milestone 1 scope: pairing, a health-check alarm, and automation
 * start/pause relayed from the popup. Application claiming, tab management,
 * and adapter dispatch are Milestone 6.
 */

import { backend } from "@/backend-client";
import type { ExtensionMessage } from "@/messaging/types";
import { getStoredToken, setStoredToken } from "@/security/token-store";

const HEALTH_CHECK_ALARM = "job-agent-health-check";

async function ensureAlarms(): Promise<void> {
  const existing = await chrome.alarms.get(HEALTH_CHECK_ALARM);
  if (!existing) {
    chrome.alarms.create(HEALTH_CHECK_ALARM, { periodInMinutes: 1 });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void ensureAlarms();
});

chrome.runtime.onStartup.addListener(() => {
  void ensureAlarms();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== HEALTH_CHECK_ALARM) return;
  void backend
    .health()
    .then(() => chrome.storage.local.set({ "jobAgent.backendReachable": true }))
    .catch(() => chrome.storage.local.set({ "jobAgent.backendReachable": false }));
});

function extensionOrigin(): string {
  return `chrome-extension://${chrome.runtime.id}`;
}

chrome.runtime.onMessage.addListener((message: ExtensionMessage, _sender, sendResponse) => {
  switch (message.type) {
    case "PAIR":
      backend
        .pair(message.pairingSecret, extensionOrigin())
        .then(async ({ extension_token }) => {
          await setStoredToken(extension_token);
          sendResponse({ ok: true });
        })
        .catch((err: Error) => sendResponse({ ok: false, error: err.message }));
      return true; // keep the message channel open for the async response

    case "GET_PAIRING_STATE":
      getStoredToken()
        .then((token) => sendResponse({ paired: token !== null }))
        .catch(() => sendResponse({ paired: false }));
      return true;

    case "GET_AUTOMATION_STATUS":
      backend
        .automationStatus()
        .then((res) => sendResponse({ ok: true, mode: res.mode }))
        .catch((err: Error) => sendResponse({ ok: false, error: err.message }));
      return true;

    case "TOGGLE_AUTOMATION":
      backend
        .automationStatus()
        .then((current) =>
          current.mode === "PAUSED" ? backend.startAutomation() : backend.pauseAutomation(),
        )
        .then((res) => sendResponse({ ok: true, mode: res.mode }))
        .catch((err: Error) => sendResponse({ ok: false, error: err.message }));
      return true;

    default:
      return false;
  }
});
