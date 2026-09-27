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
