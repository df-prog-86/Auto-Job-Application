# Job Agent

A local-first, automated job application platform: resume in, tailored applications out,
with a human in control of limits, review, and exceptions at every step.

## Architecture

Three independently-versioned components, talking over a local-only HTTP API:

- **`backend/`** — Python/FastAPI. Orchestration, candidate intelligence, AI calls, job
  discovery, qualification scoring, resume tailoring, credential management, and the durable
  SQLite state machine. Binds to `127.0.0.1` only.
- **`extension/`** — Chrome MV3 extension. The browser *execution* layer only: opens ATS tabs,
  runs ATS-specific adapters, fills and submits forms. Contains no candidate-intelligence logic
  of its own — it calls back into the backend for every decision.
- **`dashboard/`** — React/TypeScript. The primary user-facing interface, served locally by the
  backend at `http://127.0.0.1:8765/app`.

See `docs/` for the full production specification and architecture decisions as they're made.

## Status

Milestone 1 (Foundation) in progress — repo scaffold, backend skeleton, local pairing/auth,
dashboard shell, extension shell. See the task list in-session for current progress.

## Local development

Each component has its own README with setup instructions:

- [`backend/README.md`](backend/README.md)
- [`dashboard/README.md`](dashboard/README.md)
- [`extension/README.md`](extension/README.md)

## Core principles

- **Local-first.** Candidate data, credentials, and application history stay on the user's
  machine. External providers get only what a specific AI operation requires.
- **Deterministic before generative.** LLMs are used only where interpretation or controlled
  generation materially improves the result — never for facts a database lookup or a
  calculation can answer.
- **Candidate truth is authoritative.** No model may invent an employer, skill, date, metric,
  or credential. Every generated factual claim traces to a `VerifiedClaim` or an explicit
  candidate answer.
- **Respect external controls.** No CAPTCHA/MFA/rate-limit bypass, no automation of platforms
  that prohibit it (LinkedIn, Indeed Apply), no evasion of anti-automation controls.
- **User is in control.** Daily/weekly/employer application limits, automation
  pause/review/auto modes, and per-adapter certification levels are all configurable.
