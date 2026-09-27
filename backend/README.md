# Backend

Python/FastAPI service: orchestration, candidate intelligence, job discovery, qualification
scoring, resume tailoring, credential management, and the durable SQLite state machine. Binds
to `127.0.0.1` only — never exposed to the network.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (`pipx install uv`, or
`brew install uv` on macOS).

```bash
cd backend
uv venv .venv
source .venv/bin/activate        # macOS/Linux
uv pip install -e ".[dev]"
```

## Database

SQLite in WAL mode, managed by Alembic. On first setup:

```bash
alembic upgrade head
```

To generate a new migration after changing a model in `app/models/`:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

The database file lives at `backend/data/job_agent.db` by default (see `app/config.py` /
`DATABASE_PATH`) — this directory is gitignored, since it's user data.

## Running the server

```bash
python -m app.run
```

This starts uvicorn bound to `127.0.0.1:8765` (configurable via `LOCAL_API_PORT` in a
`backend/.env` file), acquires a single-instance lock, and serves the API under `/api/v1/`.
Once the dashboard has been built (`dashboard/dist/` exists), it's also served at `/app`.

Verify it's alive:

```bash
curl http://127.0.0.1:8765/api/v1/health
curl http://127.0.0.1:8765/api/v1/version
```

## Configuration

All product-behavior knobs (rate limits, model routing, qualification thresholds, discovery
interval) are environment variables — see `app/config.py` for the full list and defaults, and
spec §7 for their intent. Override any of them in `backend/.env` (gitignored).

## Configuring an LLM provider

Resume parsing (structured extraction, `POST /api/v1/profile/resume/parse`) needs an
OpenAI-compatible LLM provider configured — without one, that endpoint returns a 503 rather
than guessing. Nothing else in Milestone 1/2 requires it.

1. Store your provider's API key in the OS credential store under some reference name, e.g.:
   ```bash
   python -c "from app.services.credentials.store import store_secret; store_secret('openrouter-main', 'sk-...')"
   ```
2. Set in `backend/.env`:
   ```
   LLM_API_BASE_URL=https://openrouter.ai/api/v1
   LLM_API_KEY_REF=openrouter-main
   PRIMARY_FAST_MODEL=deepseek/deepseek-chat
   FALLBACK_FAST_MODEL=openai/gpt-4o-mini
   ```
   Any OpenAI-compatible base URL works; model identifiers are provider-specific strings, not
   validated against a fixed list (spec §7 — "production code must verify provider capabilities
   rather than assume them").

## OCR fallback (optional)

Only needed if you'll upload scanned/image-only PDFs. Requires the `ocr` extra plus the
`poppler` system package (used by `pdf2image` to rasterize PDF pages):

```bash
uv pip install -e ".[dev,ocr]"
brew install poppler        # macOS
# or: apt-get install poppler-utils   (Linux)
```

## Tests

```bash
uv pip install -e ".[dev]"
pytest
ruff check .
mypy app
```

## Notes on this milestone

This backend was scaffolded and written in a sandboxed session with no PyPI/npm network access,
so **none of the above has been run yet**. If something in `uv pip install` or `alembic upgrade
head` fails, that's expected — report the exact error back and it'll get fixed. The code has
been reviewed for correctness (imports, SQLAlchemy 2.x syntax, FastAPI dependency wiring) but
not executed.
