/**
 * Deliberately minimal popup UI (spec §14): Start/Pause, status, Needs
 * Attention count, and Open Dashboard — plus first-run pairing, which has
 * nowhere else to live in the extension. Plain DOM, no framework; this
 * surface is small enough not to need one.
 */

import type {
  AutomationStatusResult,
  CaptureJobResult,
  ExtensionMessage,
  FillPageResult,
  PairingStateResult,
  PairResult,
} from "@/messaging/types";

const DASHBOARD_URL = "http://127.0.0.1:8765/app";

function sendMessage<T>(message: ExtensionMessage): Promise<T> {
  return chrome.runtime.sendMessage(message);
}

function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Missing #${id} in popup.html`);
  return el;
}

function showError(message: string): void {
  $("error").textContent = message;
  $("captureStatus").textContent = "";
}

function showCaptureStatus(message: string): void {
  $("captureStatus").textContent = message;
  $("error").textContent = "";
}

function setStatusUI(mode: "PAUSED" | "REVIEW" | "AUTO"): void {
  const statusText = $("statusText");
  statusText.textContent = mode;
  statusText.className = `status ${mode === "PAUSED" ? "paused" : "active"}`;
  ($("toggleButton") as HTMLButtonElement).textContent = mode === "PAUSED" ? "Start" : "Pause";
}

async function refreshStatus(): Promise<void> {
  const result = await sendMessage<AutomationStatusResult>({ type: "GET_AUTOMATION_STATUS" });
  if (result.ok && result.mode) {
    setStatusUI(result.mode);
  } else {
    showError(result.error ?? "Couldn't reach the backend.");
  }
}

async function init(): Promise<void> {
  const pairingState = await sendMessage<PairingStateResult>({ type: "GET_PAIRING_STATE" });

  if (!pairingState.paired) {
    $("pairingSection").style.display = "block";
    $("pairButton").addEventListener("click", async () => {
      const input = $("pairingSecretInput") as HTMLInputElement;
      const secret = input.value.trim();
      if (!secret) return;

      const result = await sendMessage<PairResult>({ type: "PAIR", pairingSecret: secret });
      if (result.ok) {
        $("pairingSection").style.display = "none";
        $("mainSection").style.display = "block";
        await refreshStatus();
      } else {
        showError(result.error ?? "Pairing failed.");
      }
    });
    return;
  }

  $("mainSection").style.display = "block";
  await refreshStatus();

  $("toggleButton").addEventListener("click", async () => {
    const result = await sendMessage<AutomationStatusResult>({ type: "TOGGLE_AUTOMATION" });
    if (result.ok && result.mode) {
      setStatusUI(result.mode);
    } else {
      showError(result.error ?? "Couldn't update automation status.");
    }
  });

  $("saveJobButton").addEventListener("click", async () => {
    const button = $("saveJobButton") as HTMLButtonElement;
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!activeTab?.id) {
      showError("Couldn't find the current tab.");
      return;
    }

    button.disabled = true;
    button.textContent = "Saving…";
    try {
      const result = await sendMessage<CaptureJobResult>({
        type: "CAPTURE_JOB",
        tabId: activeTab.id,
      });
      if (result.ok) {
        showCaptureStatus(`Saved: ${result.jobTitle} · ${result.company}`);
      } else {
        showError(result.error ?? "Couldn't save this job.");
      }
    } finally {
      button.disabled = false;
      button.textContent = "Save this job";
    }
  });

  async function runFill(jobId?: number): Promise<void> {
    const button = $("fillButton") as HTMLButtonElement;
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!activeTab?.id) {
      showError("Couldn't find the current tab.");
      return;
    }
    button.disabled = true;
    button.textContent = "Filling…";
    $("fillResult").textContent = "";
    $("fillChoices").style.display = "none";
    try {
      const result = await sendMessage<FillPageResult>({ type: "FILL_PAGE", tabId: activeTab.id, jobId });
      renderFillResult(result);
    } catch (err) {
      showError((err as Error).message);
    } finally {
      button.disabled = false;
      button.textContent = "Fill this application";
    }
  }

  function renderFillResult(result: FillPageResult): void {
    const out = $("fillResult");
    $("error").textContent = "";
    if (!result.ok) {
      if (result.choices && result.choices.length > 0) {
        const select = $("fillChoiceSelect") as HTMLSelectElement;
        select.replaceChildren(
          ...result.choices.map((c) => {
            const option = document.createElement("option");
            option.value = String(c.id);
            option.textContent = `${c.title} at ${c.company}`;
            return option;
          }),
        );
        $("fillChoices").style.display = "block";
      }
      out.style.color = "#b45309";
      out.textContent = result.problem ?? result.error ?? "Couldn't fill this page.";
      return;
    }
    out.style.color = "#059669";
    const lines = [`Filled ${result.filledCount} for ${result.jobTitle} at ${result.company}.`];
    if (result.flagged && result.flagged.length > 0) {
      lines.push(`${result.flagged.length} need you: ${result.flagged.join("; ")}. They're on Needs Attention too.`);
    }
    if (result.voluntarySkipped) lines.push(`Left ${result.voluntarySkipped} self-identification questions for you.`);
    lines.push("Check everything, then submit it yourself.");
    out.textContent = lines.join(" ");
  }

  $("fillButton").addEventListener("click", () => void runFill());
  $("fillChoiceButton").addEventListener("click", () => {
    const id = Number(($("fillChoiceSelect") as HTMLSelectElement).value);
    if (id) void runFill(id);
  });

  $("openDashboardButton").addEventListener("click", () => {
    chrome.tabs.create({ url: DASHBOARD_URL });
  });
}

void init();
