# Dashboard

React/TypeScript UI, served locally by the backend at `http://127.0.0.1:8765/app`. This is the
primary user-facing surface for the whole product (spec §14) — the extension's own popup is
deliberately minimal (Start/Pause, status, Needs Attention count, Open Dashboard).

## Setup

Requires Node 20+.

```bash
cd dashboard
npm install
```

## Development

```bash
npm run dev
```

Runs Vite's dev server on `http://localhost:5173` and proxies `/api/*` calls to the backend at
`127.0.0.1:8765` (see `vite.config.ts`) — start the backend first (`backend/README.md`).

## Production build

```bash
npm run build
```

Outputs to `dashboard/dist/`, which the backend serves at `/app` once present
(`app/main.py` mounts it automatically if the directory exists).

## Type checking / linting

```bash
npm run typecheck
npm run lint
```

## Structure

- `src/pages/` — the six primary user areas (Home, Profile, Job Preferences, Applications,
  Needs Attention, Accounts) plus the extension-pairing page.
- `src/api/client.ts` — thin fetch wrapper against the backend's `/api/v1` surface.
- `src/types/api.ts` — hand-written response types for now; per spec §5 these should eventually
  be generated from the backend's OpenAPI schema rather than kept in sync by hand — that
  generation step is added once the backend is reachable to introspect.

## Notes on this milestone

Written in a sandboxed session with no npm registry access, so `npm install` has not been run
here. Report back any install/build errors and they'll get fixed.
