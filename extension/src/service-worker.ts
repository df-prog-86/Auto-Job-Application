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

import { backend, downloadDocumentBase64 } from "@/backend-client";
import type { ApplyContext, FillReport } from "@/form-engine/types";
import type { CapturedPage, ExtensionMessage, FillPageResult } from "@/messaging/types";
import { getStoredToken, setStoredToken } from "@/security/token-store";

const CAPTURE_BODY_TEXT_LIMIT = 12000;

/**
 * Runs inside the page the user is looking at (spec §32's programmatic-
 * injection pattern, on a plain read here rather than an ATS adapter).
 * Reads only what's needed to extract a job posting -- structured JobPosting
 * markup if present, plus the page's own visible text as an LLM fallback --
 * never the full HTML, so nothing beyond that leaves the user's browser.
 */
function readJobPostingFromPage(bodyTextLimit: number): CapturedPage {
  const jsonLd = Array.from(
    document.querySelectorAll('script[type="application/ld+json"]'),
  ).map((el) => el.textContent || "");
  return {
    url: location.href,
    title: document.title,
    jsonLd,
    bodyText: (document.body?.innerText || "").slice(0, bodyTextLimit),
  };
}

/**
 * Fills the application page in the given tab. Runs only when the candidate
 * clicks "Fill this application". Never submits anything: the injected
 * script has no way to click a submit button (see form-engine/safety.ts).
 */
async function fillApplicationPage(tabId: number, jobId?: number): Promise<FillPageResult> {
  const tab = await chrome.tabs.get(tabId);
  if (!tab.url || !/^https?:/.test(tab.url)) {
    return { ok: false, problem: "Open the application page in this tab first." };
  }

  const ctx = await backend.applyContext(tab.url, jobId);
  if (!ctx.job || !ctx.candidate || !ctx.resume) {
    return {
      ok: false,
      problem: ctx.problem ?? "Couldn't prepare this application.",
      choices: ctx.candidates.map((c) => ({ id: c.id, title: c.title, company: c.company })),
    };
  }

  const resume = { base64: await downloadDocumentBase64(ctx.resume.document_id), filename: ctx.resume.filename };
  const applyCtx: ApplyContext = {
    candidate: ctx.candidate,
    answers: ctx.answers,
    learned_answers: ctx.learned_answers,
  };

  await chrome.scripting.executeScript({ target: { tabId }, files: ["content/fill-page.js"] });
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: (c: ApplyContext, r: { base64: string; filename: string }) =>
      (window as unknown as { __jobAgentFill: (c: ApplyContext, r: unknown) => Promise<FillReport> }).__jobAgentFill(c, r),
    args: [applyCtx, resume],
  });
  const report = results[0]?.result as FillReport | undefined;
  if (!report) return { ok: false, error: "Couldn't read this page. Reload it and try again." };

  // Only the questions left blank go back to the app (never the filled values),
  // and the address is sent without its query string.
  const page = new URL(tab.url);
  await backend.applyReport({
    jobId: ctx.job.id,
    pageUrl: `${page.origin}${page.pathname}`,
    filledCount: report.filled.length,
    flagged: report.flagged,
  });

  return {
    ok: true,
    jobTitle: ctx.job.title,
    company: ctx.job.company,
    filledCount: report.filled.length,
    flagged: report.flagged.map((f) => f.label),
    leftBlank: report.leftBlank,
    alreadyFilled: report.alreadyFilled,
    voluntarySkipped: report.voluntarySkipped,
  };
}

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

    case "CAPTURE_JOB":
      chrome.scripting
        .executeScript({
          target: { tabId: message.tabId },
          func: readJobPostingFromPage,
          args: [CAPTURE_BODY_TEXT_LIMIT],
        })
        .then(async (results) => {
          const captured = results[0]?.result;
          if (!captured) {
            sendResponse({ ok: false, error: "Couldn't read that page." });
            return;
          }
          try {
            const job = await backend.captureJob(captured);
            sendResponse({ ok: true, jobTitle: job.title, company: job.company });
          } catch (err) {
            sendResponse({ ok: false, error: (err as Error).message });
          }
        })
        .catch((err: Error) => sendResponse({ ok: false, error: err.message }));
      return true;

    case "FILL_PAGE":
      fillApplicationPage(message.tabId, message.jobId)
        .then(sendResponse)
        .catch((err: Error) => sendResponse({ ok: false, error: err.message }));
      return true;

    default:
      return false;
  }
});
