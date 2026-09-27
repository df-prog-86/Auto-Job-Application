# Milestone 1 (Foundation) — validation checklist

Everything below was written and syntax/type-checked in a sandboxed session with no PyPI or npm
registry access, so **none of it has actually been run yet**. This is the checklist to run
locally to confirm the spec's Milestone 1 acceptance criterion: *"Dashboard ↔ FastAPI ↔
Extension communication works."*

Report back the exact output of any step that fails — that's the fastest way to get it fixed.

## 1. Backend

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
alembic revision --autogenerate -m "initial schema"   # generates the first migration
alembic upgrade head
python -m app.run
```

Expect: server starts, logs binding to `127.0.0.1:8765`, no traceback.

In another terminal:

```bash
curl http://127.0.0.1:8765/api/v1/health
curl http://127.0.0.1:8765/api/v1/version
```

Expect: JSON responses, not connection errors.

```bash
pytest
```

Expect: all tests in `backend/tests/` pass (health, version, automation start/pause, full
pairing flow, wrong-secret rejection).

## 2. Dashboard

```bash
cd dashboard
npm install
npm run build       # or: npm run dev, for a live-reload dev server on :5173
```

If using `npm run build`, restart the backend afterward so it picks up `dashboard/dist/`, then
open `http://127.0.0.1:8765/app` in a browser. If using `npm run dev`, open
`http://localhost:5173` instead (it proxies `/api` to the backend).

Expect: the Home page loads, shows automation status as **PAUSED**, and clicking **Start**
flips it to **REVIEW** without a page reload (confirms dashboard ↔ backend).

## 3. Extension

```bash
cd extension
npm install
npm run build
```

Then in Chrome: `chrome://extensions` → enable Developer mode → **Load unpacked** →
`extension/dist/`.

- Open the dashboard, go to **Pair Extension**, click **Generate pairing code**.
- Open the extension's toolbar popup, paste the code, click **Pair**.
- Popup should switch to showing status + Start/Pause + Open Dashboard.
- Click **Start** in the popup; reload the dashboard's Home page — it should now show
  **REVIEW** too (confirms extension ↔ backend ↔ dashboard are all seeing the same state).

## If something breaks

Most likely failure points, roughly in order of probability:
- A version pin in `backend/pyproject.toml` or `dashboard/package.json` /
  `extension/package.json` that's since moved — bump it.
- `alembic revision --autogenerate` producing an empty migration (means a model isn't being
  imported — check `app/models/__init__.py`).
- A CORS/origin mismatch between the extension's actual ID and `EXTENSION_ORIGIN_ALLOWLIST` —
  it's empty by default (any origin accepted), so this shouldn't bite in dev, but worth checking
  first if pairing fails with a 403.
