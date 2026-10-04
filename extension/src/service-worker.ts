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
import { isSupportedApplicationUrl } from "@/security/ats-hosts";
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
    experience: ctx.experience,
    education: ctx.education,
    skills: ctx.skills,
    certifications: ctx.certifications,
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
    pagesAdvanced: report.pagesAdvanced,
    stoppedBecause: report.stoppedBecause,
  };
}

const DASHBOARD_ORIGIN = "http://127.0.0.1:8765";

function notify(title: string, message: string): void {
  chrome.notifications.create({ type: "basic", iconUrl: "icons/icon128.png", title, message });
}

function waitForTabComplete(tabId: number, timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(timer);
      resolve();
    };
    const listener = (id: number, info: chrome.tabs.TabChangeInfo) => {
      if (id === tabId && info.status === "complete") done();
    };
    const timer = setTimeout(done, timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

/**
 * "Complete application" from the dashboard: opens the posting in a new tab,
 * waits for the form to appear, then runs the same fill as the popup button.
 * Still never submits; the person reviews and clicks Submit themselves.
 */
/** Ashby shows the posting first; its form lives at ".../application". */
function applicationUrlFor(raw: string): string {
  const url = new URL(raw);
  if (url.hostname === "jobs.ashbyhq.com" && !/\/application\/?$/.test(url.pathname)) {
    url.pathname = `${url.pathname.replace(/\/$/, "")}/application`;
  }
  return url.toString();
}

// ---- Workday: posting -> Apply -> Apply Manually -> (person signs in) -> fill and move on ----

const WORKDAY_RUN_KEY = "jobAgent.workdayRun";
const WORKDAY_RUN_MAX_MS = 20 * 60_000;

interface WorkdayRun {
  tabId: number;
  jobId: number;
  startedAt: number;
}

const isWorkdayUrl = (raw: string): boolean => {
  try {
    return new URL(raw).hostname.toLowerCase().endsWith(".myworkdayjobs.com");
  } catch {
    return false;
  }
};

async function getWorkdayRun(): Promise<WorkdayRun | null> {
  const stored = await chrome.storage.session.get(WORKDAY_RUN_KEY);
  const run = stored[WORKDAY_RUN_KEY] as WorkdayRun | undefined;
  if (!run || Date.now() - run.startedAt > WORKDAY_RUN_MAX_MS) return null;
  return run;
}

async function clearWorkdayRun(): Promise<void> {
  await chrome.storage.session.remove(WORKDAY_RUN_KEY);
}

/** (Re)starts the in-page walker on the tab. Safe to call on every page load: the page ignores a second start. */
async function startWorkdayWalker(run: WorkdayRun): Promise<void> {
  const tab = await chrome.tabs.get(run.tabId);
  if (!tab.url || !isWorkdayUrl(tab.url) || !isSupportedApplicationUrl(tab.url)) return;
  const ctx = await backend.applyContext(tab.url, run.jobId);
  if (!ctx.job || !ctx.candidate || !ctx.resume) {
    await clearWorkdayRun();
    notify("Couldn't fill the application", ctx.problem ?? "Couldn't prepare this application.");
    return;
  }
  const resume = { base64: await downloadDocumentBase64(ctx.resume.document_id), filename: ctx.resume.filename };
  const applyCtx: ApplyContext = {
    candidate: ctx.candidate,
    answers: ctx.answers,
    learned_answers: ctx.learned_answers,
    experience: ctx.experience,
    education: ctx.education,
    skills: ctx.skills,
    certifications: ctx.certifications,
  };
  await chrome.scripting.executeScript({ target: { tabId: run.tabId }, files: ["content/fill-page.js"] });
  await chrome.scripting.executeScript({
    target: { tabId: run.tabId },
    func: (c: ApplyContext, r: { base64: string; filename: string }) =>
      (window as unknown as { __jobAgentWorkday: (c: ApplyContext, r: unknown) => string }).__jobAgentWorkday(c, r),
    args: [applyCtx, resume],
  });
}

chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status !== "complete") return;
  void (async () => {
    const run = await getWorkdayRun();
    if (!run || run.tabId !== tabId) return;
    await startWorkdayWalker(run);
  })().catch(() => undefined);
});

async function finishWorkdayRun(
  senderTabId: number | undefined,
  report: FillReport | null,
  stoppedBecause: string,
): Promise<void> {
  const run = await getWorkdayRun();
  if (!run || run.tabId !== senderTabId) return;
  await clearWorkdayRun();
  if (!report) {
    notify("Couldn't finish the application", stoppedBecause || "Open the application and try again.");
    return;
  }
  const tab = await chrome.tabs.get(run.tabId);
  const page = new URL(tab.url ?? "https://invalid.example/");
  await backend
    .applyReport({
      jobId: run.jobId,
      pageUrl: `${page.origin}${page.pathname}`,
      filledCount: report.filled.length,
      flagged: report.flagged,
    })
    .catch(() => undefined);
  const pages = report.pagesAdvanced ?? 0;
  notify(
    "Application filled, not submitted",
    `Moved ahead ${pages} page${pages === 1 ? "" : "s"}.${report.stoppedBecause ? ` Stopped: ${report.stoppedBecause}` : ""} Review it, then submit it yourself.`,
  );
}

async function completeWorkdayApplication(jobId: number, url: string): Promise<void> {
  const tab = await chrome.tabs.create({ url, active: true });
  if (tab.id === undefined) return;
  const run: WorkdayRun = { tabId: tab.id, jobId, startedAt: Date.now() };
  await chrome.storage.session.set({ [WORKDAY_RUN_KEY]: run });
  // The tab may already be loaded by now; if not, the tab listener starts it when it is.
  const now = await chrome.tabs.get(tab.id);
  if (now.status === "complete") await startWorkdayWalker(run);
}

async function completeApplication(jobId: number, url: string): Promise<void> {
  if (isWorkdayUrl(url)) return completeWorkdayApplication(jobId, url);
  const tab = await chrome.tabs.create({ url: applicationUrlFor(url), active: true });
  if (tab.id === undefined) return;
  const tabId = tab.id;
  await waitForTabComplete(tabId, 30000);

  // Application forms often render a moment after the page "loads".
  for (let i = 0; i < 20; i++) {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => document.querySelectorAll("input, textarea, select").length > 3,
    });
    if (res?.result) break;
    await new Promise((r) => setTimeout(r, 500));
  }

  const result = await fillApplicationPage(tabId, jobId);
  if (!result.ok) {
    notify("Couldn't fill the application", result.problem ?? result.error ?? "Open the extension on that tab to try again.");
  } else {
    const n = result.flagged?.length ?? 0;
    notify(
      "Application filled, not submitted",
      result.stoppedBecause
        ? `Moved ahead ${result.pagesAdvanced ?? 0} page${result.pagesAdvanced === 1 ? "" : "s"}. Stopped: ${result.stoppedBecause}`
        : n > 0 ? `${n} field${n === 1 ? "" : "s"} need you. Review the page, then submit it yourself.` : "Review the page, then submit it yourself.",
    );
  }
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

chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender, sendResponse) => {
  switch (message.type) {
    case "COMPLETE_APPLICATION": {
      // Only the dashboard (served from this computer) may ask for this.
      if (!sender.url || !sender.url.startsWith(`${DASHBOARD_ORIGIN}/app`)) {
        sendResponse({ ok: false, error: "Not allowed." });
        return false;
      }
      if (!Number.isInteger(message.jobId) || !isSupportedApplicationUrl(message.url)) {
        sendResponse({
          ok: false,
          unsupported: true,
          error: "This site isn't supported for one-click yet. Open the posting and use the extension's Fill button.",
        });
        return false;
      }
      void completeApplication(message.jobId, message.url).catch((err: Error) =>
        notify("Couldn't fill the application", err.message),
      );
      sendResponse({ ok: true });
      return false;
    }

    case "WORKDAY_WAITING":
      if (sender.id === chrome.runtime.id && sender.tab) {
        notify("Sign in to Workday", "Sign in (or create your account) on that tab. Job Agent carries on by itself afterwards.");
      }
      return false;

    case "WORKDAY_DONE":
      if (sender.id === chrome.runtime.id && sender.tab) {
        void finishWorkdayRun(sender.tab.id, message.report, message.stoppedBecause).catch(() => undefined);
      }
      return false;

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
