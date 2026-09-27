# Extension

Chrome Manifest V3 extension: the browser *execution* layer only (spec §1). It opens and drives
ATS tabs and runs adapters against them, but holds no candidate-intelligence logic of its own —
every decision (what to fill, what to answer, whether to submit) comes from the backend.

## Setup

```bash
cd extension
npm install
npm run build
```

## Loading into Chrome (development)

1. `npm run build` (outputs to `extension/dist/`).
2. Open `chrome://extensions`.
3. Enable **Developer mode** (top-right toggle).
4. **Load unpacked** → select `extension/dist/`.
5. Make sure the backend is running (`backend/README.md`) before opening the popup — pairing and
   status both need it reachable at `127.0.0.1:8765`.

`npm run dev` rebuilds on file change; reload the extension in `chrome://extensions` after each
rebuild (Vite doesn't hot-reload MV3 extensions the way it does web pages).

## Pairing (first run)

1. Open the dashboard (`http://127.0.0.1:8765/app`) → **Pair Extension** → generate a code.
2. Open the extension's popup (toolbar icon) → paste the code → **Pair**.
3. The popup switches to showing automation status and a Start/Pause control.

The pairing secret is single-use and short-lived, issued by the backend and never stored; the
extension token it produces is the thing that persists (in `chrome.storage.local`), and is never
readable by a content script (`src/security/token-store.ts` is only ever imported by the service
worker).

## Structure

- `src/service-worker.ts` — MV3 background service worker. Event-driven only: uses
  `chrome.alarms`, never `setInterval`, per spec §33, since Chrome kills this worker after ~30s
  of inactivity and any in-memory state would evaporate with it.
- `src/popup/` — the toolbar popup (Start/Pause, status, Needs Attention count, Open Dashboard).
- `src/adapters/base.ts` — the `ATSAdapter` interface (spec §35). No implementations yet —
  Greenhouse/Lever (Milestone 7), the generic fallback (Milestone 6), and Workday (Milestone 9)
  all implement this same interface.
- `src/content/detector.ts` — placeholder for the multi-signal ATS detector (spec §37). Not
  wired into `manifest.json`: adapter scripts get injected programmatically via
  `chrome.scripting.executeScript` once the service worker opens a tab for a specific
  application, rather than declared as a static `content_scripts` entry — see the comment at
  the top of that file and spec §32.

## Permissions

Currently: `alarms`, `storage`, `tabs`, `scripting`, `notifications`, and host permission for
the local backend only (`http://127.0.0.1:8765/*`). ATS host permissions (Greenhouse, Lever,
Workday tenant domains, etc.) are added incrementally as each adapter is built, never as a
blanket `*://*/*` grant (spec §32).

## Notes on this milestone

Written in a sandboxed session with no npm registry access, so `npm install` / `npm run build`
have not been run here. Report back any errors and they'll get fixed.
