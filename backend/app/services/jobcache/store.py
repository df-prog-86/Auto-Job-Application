"""
The job cache: a local copy of employers' public job lists, in its own SQLite file.

It is kept apart from job_agent.db on purpose. Backups of your real data (jobs, profile, resumes) stay small, and this
copy can always be rebuilt by reading the employers again. Nothing here holds personal information.

Speed at any size comes from three things: only OPEN postings sit in the full-text index (closed ones are removed from
it), every filter the search uses has an index, and a search reads a bounded number of candidates, never the whole table.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS employers (
    id INTEGER PRIMARY KEY,
    ats TEXT NOT NULL,
    identifier TEXT NOT NULL,
    name TEXT NOT NULL,
    industry TEXT,
    source TEXT NOT NULL DEFAULT 'search',
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'new',
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_checked INTEGER,
    last_ok INTEGER,
    next_check INTEGER NOT NULL DEFAULT 0,
    open_count INTEGER NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0,
    added_at INTEGER NOT NULL,
    UNIQUE (ats, identifier)
);
CREATE INDEX IF NOT EXISTS idx_employers_due ON employers (enabled, next_check);

CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY,
    employer_id INTEGER NOT NULL REFERENCES employers (id) ON DELETE CASCADE,
    ext_id TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    work_type TEXT,
    pay_text TEXT,
    pay_mid REAL,
    posted_at TEXT,
    url TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    closed_at INTEGER,
    UNIQUE (employer_id, ext_id)
);
CREATE INDEX IF NOT EXISTS idx_postings_open ON postings (closed_at, employer_id);
CREATE INDEX IF NOT EXISTS idx_postings_posted ON postings (posted_at);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS postings_fts USING fts5("
    "title, company, location, tokenize = 'porter unicode61 remove_diacritics 2')"
)

CLOSED_KEEP_DAYS = 30
_INIT_LOCK = threading.Lock()
_INITIALISED: dict[str, bool] = {}  # path -> whether full-text search is available


@dataclass
class PostingIn:
    """One posting as a reader hands it over."""

    ext_id: str
    title: str
    url: str
    location: str | None = None
    work_type: str | None = None  # remote / hybrid / onsite / None when the system does not say
    pay_text: str | None = None
    pay_mid: float | None = None
    posted_at: dt.date | None = None


@dataclass
class RefreshResult:
    new: int = 0
    closed: int = 0
    total: int = 0


def now_ts() -> int:
    return int(time.time())


class JobCache:
    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or settings.JOB_CACHE_PATH)
        self.has_fts = self._init()

    # ---- connection -------------------------------------------------------------------------------------

    def _init(self) -> bool:
        with _INIT_LOCK:
            if self.path in _INITIALISED:
                return _INITIALISED[self.path]
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = self._raw()
            try:
                conn.executescript(SCHEMA)
                try:
                    conn.execute(FTS_SCHEMA)
                    fts = True
                except sqlite3.OperationalError:
                    fts = False  # this Python's SQLite has no full-text search: searches fall back to a plain scan
                conn.commit()
            finally:
                conn.close()
            _INITIALISED[self.path] = fts
            return fts

    def _raw(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-20000")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self._raw()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- meta -------------------------------------------------------------------------------------------

    def meta_get(self, key: str) -> str | None:
        with self.session() as db:
            row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self.session() as db:
            db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))

    # ---- employers --------------------------------------------------------------------------------------

    def upsert_employer(self, ats: str, identifier: str, name: str, source: str, industry: str | None = None) -> tuple[int, bool]:
        """Adds an employer, or returns the existing one. A real name replaces a name that was only a guess from the address."""
        guess = guess_name(ats, identifier)
        name = (name or "").strip() or guess
        with self.session() as db:
            row = db.execute("SELECT id, name FROM employers WHERE ats = ? AND identifier = ?", (ats, identifier)).fetchone()
            if row:
                if name != guess and row["name"] == guess:
                    db.execute("UPDATE employers SET name = ? WHERE id = ?", (name, row["id"]))
                return row["id"], False
            cur = db.execute(
                "INSERT INTO employers (ats, identifier, name, industry, source, added_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ats, identifier, name, industry, source, now_ts()),
            )
            return int(cur.lastrowid), True

    def get_employer(self, employer_id: int) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM employers WHERE id = ?", (employer_id,)).fetchone()
        return dict(row) if row else None

    def list_employers(self, query: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Employers, the ones with the most open jobs first. `query` filters by name; `limit` keeps a long list short."""
        sql = "SELECT * FROM employers"
        params: list[Any] = []
        if query and query.strip():
            sql += " WHERE name LIKE ?"
            params.append(f"%{query.strip()}%")
        sql += " ORDER BY open_count DESC, name COLLATE NOCASE"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.session() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_enabled(self, employer_id: int, enabled: bool) -> bool:
        with self.session() as db:
            cur = db.execute("UPDATE employers SET enabled = ? WHERE id = ?", (1 if enabled else 0, employer_id))
            return cur.rowcount > 0

    def delete_employer(self, employer_id: int) -> None:
        with self.session() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM postings WHERE employer_id = ?", (employer_id,))]
            self._fts_delete(db, ids)
            db.execute("DELETE FROM employers WHERE id = ?", (employer_id,))

    def due_employers(self, now: int, limit: int, only_ids: list[int] | None = None, disabled_systems: set[str] | None = None) -> list[dict[str, Any]]:
        """Employers whose copy is out of date. The ones you saved jobs from, or that have produced results, go first."""
        with self.session() as db:
            if only_ids is not None:
                marks = ",".join("?" * len(only_ids)) or "NULL"
                rows = db.execute(f"SELECT * FROM employers WHERE id IN ({marks})", only_ids).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM employers WHERE enabled = 1 AND next_check <= ? "
                    "ORDER BY (source IN ('saved_job', 'user_link') OR hits > 0) DESC, next_check ASC LIMIT ?",
                    (now, limit),
                ).fetchall()
        out = [dict(r) for r in rows]
        if disabled_systems:
            out = [e for e in out if e["ats"] not in disabled_systems]
        return out

    def record_failure(self, employer_id: int, error: str, now: int, retry_after: int | None = None) -> None:
        """A failed read. The wait before the next try doubles each time, up to a week, so a dead employer costs almost nothing."""
        with self.session() as db:
            row = db.execute("SELECT fail_count FROM employers WHERE id = ?", (employer_id,)).fetchone()
            fails = (row["fail_count"] if row else 0) + 1
            wait = retry_after if retry_after else min(6 * 3600 * (2 ** (fails - 1)), 7 * 86400)
            status = "unreachable" if fails >= 5 else "error"
            db.execute(
                "UPDATE employers SET fail_count = ?, status = ?, last_error = ?, last_checked = ?, next_check = ? WHERE id = ?",
                (fails, status, error[:300], now, now + wait, employer_id),
            )

    def employer_hits(self, employer_ids: list[int]) -> None:
        if not employer_ids:
            return
        with self.session() as db:
            db.executemany("UPDATE employers SET hits = hits + 1 WHERE id = ?", [(i,) for i in set(employer_ids)])

    # ---- postings ---------------------------------------------------------------------------------------

    def _fts_delete(self, db: sqlite3.Connection, ids: list[int]) -> None:
        if self.has_fts and ids:
            db.executemany("DELETE FROM postings_fts WHERE rowid = ?", [(i,) for i in ids])

    def _fts_insert(self, db: sqlite3.Connection, rows: list[tuple[int, str, str, str]]) -> None:
        if self.has_fts and rows:
            db.executemany("INSERT INTO postings_fts (rowid, title, company, location) VALUES (?, ?, ?, ?)", rows)

    def apply_refresh(
        self, employer_id: int, postings: list[PostingIn], now: int, interval_hours: float = 6.0, close_missing: bool = True
    ) -> RefreshResult:
        """
        Makes the saved copy of one employer match what the employer lists now. New postings are added, postings no longer
        listed are marked closed (and leave the search index), and one that comes back is reopened. When only part of a very
        large list was read, close_missing is False so nothing is closed just because it was not reached.
        """
        result = RefreshResult(total=len(postings))
        with self.session() as db:
            emp = db.execute("SELECT name FROM employers WHERE id = ?", (employer_id,)).fetchone()
            if emp is None:
                return result
            company = emp["name"]
            existing = {
                r["ext_id"]: r
                for r in db.execute("SELECT id, ext_id, title, location, closed_at FROM postings WHERE employer_id = ?", (employer_id,))
            }
            seen: set[str] = set()
            fts_add: list[tuple[int, str, str, str]] = []
            fts_del: list[int] = []
            for p in postings:
                if not p.ext_id or not p.title or not p.url or p.ext_id in seen:
                    continue
                seen.add(p.ext_id)
                row = existing.get(p.ext_id)
                posted = p.posted_at.isoformat() if p.posted_at else None
                if row is None:
                    cur = db.execute(
                        "INSERT INTO postings (employer_id, ext_id, title, location, work_type, pay_text, pay_mid, posted_at, url, first_seen, last_seen) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (employer_id, p.ext_id, p.title[:300], (p.location or None) and p.location[:300], p.work_type, p.pay_text, p.pay_mid, posted, p.url[:1000], now, now),
                    )
                    fts_add.append((int(cur.lastrowid), p.title[:300], company, (p.location or "")[:300]))
                    result.new += 1
                    continue
                db.execute(
                    "UPDATE postings SET title = ?, location = ?, work_type = COALESCE(?, work_type), pay_text = COALESCE(?, pay_text), "
                    "pay_mid = COALESCE(?, pay_mid), posted_at = COALESCE(?, posted_at), url = ?, last_seen = ?, closed_at = NULL WHERE id = ?",
                    (p.title[:300], (p.location or None) and p.location[:300], p.work_type, p.pay_text, p.pay_mid, posted, p.url[:1000], now, row["id"]),
                )
                changed = row["title"] != p.title[:300] or (row["location"] or "") != (p.location or "")[:300]
                if row["closed_at"] is not None or changed:
                    fts_del.append(row["id"])
                    fts_add.append((row["id"], p.title[:300], company, (p.location or "")[:300]))
            gone = [r["id"] for k, r in existing.items() if close_missing and k not in seen and r["closed_at"] is None]
            if gone:
                db.executemany("UPDATE postings SET closed_at = ? WHERE id = ?", [(now, i) for i in gone])
                fts_del.extend(gone)
                result.closed = len(gone)
            self._fts_delete(db, fts_del)
            self._fts_insert(db, fts_add)
            open_now = db.execute("SELECT COUNT(*) AS n FROM postings WHERE employer_id = ? AND closed_at IS NULL", (employer_id,)).fetchone()["n"]
            db.execute(
                "UPDATE employers SET status = 'ok', fail_count = 0, last_error = NULL, last_checked = ?, last_ok = ?, next_check = ?, open_count = ? WHERE id = ?",
                (now, now, now + int(interval_hours * 3600), open_now, employer_id),
            )
        return result

    def cleanup(self, now: int | None = None) -> int:
        """Deletes postings that have been closed for a month, then the oldest closed ones if the copy is over its size limit."""
        now = now or now_ts()
        removed = 0
        with self.session() as db:
            old = [r["id"] for r in db.execute("SELECT id FROM postings WHERE closed_at IS NOT NULL AND closed_at < ?", (now - CLOSED_KEEP_DAYS * 86400,))]
            if old:
                db.executemany("DELETE FROM postings WHERE id = ?", [(i,) for i in old])
                removed += len(old)
            total = db.execute("SELECT COUNT(*) AS n FROM postings").fetchone()["n"]
            over = total - settings.JOB_CACHE_MAX_POSTINGS
            if over > 0:
                ids = [r["id"] for r in db.execute("SELECT id FROM postings ORDER BY (closed_at IS NULL), COALESCE(closed_at, last_seen) ASC LIMIT ?", (over,))]
                self._fts_delete(db, ids)
                db.executemany("DELETE FROM postings WHERE id = ?", [(i,) for i in ids])
                removed += len(ids)
        return removed

    # ---- search -----------------------------------------------------------------------------------------

    def candidates(self, match: str | None, like_terms: list[str], limit: int, earliest_posted: dt.date | None = None) -> list[dict[str, Any]]:
        """
        Open postings whose TITLE shares words with the search, best text matches first, at most `limit` of them.
        `match` is a full-text query; `like_terms` is the fallback when this SQLite has no full-text search.
        """
        params: list[Any] = []
        date_clause = ""
        if earliest_posted is not None:
            date_clause = " AND (p.posted_at IS NULL OR p.posted_at >= ?)"
            params.append(earliest_posted.isoformat())
        with self.session() as db:
            if self.has_fts and match:
                sql = (
                    "SELECT p.*, e.name AS company, e.ats AS ats, e.id AS eid FROM postings_fts f "
                    "JOIN postings p ON p.id = f.rowid JOIN employers e ON e.id = p.employer_id "
                    "WHERE postings_fts MATCH ? AND p.closed_at IS NULL AND e.enabled = 1" + date_clause +
                    " ORDER BY bm25(postings_fts, 10.0, 0.0, 0.5) LIMIT ?"
                )
                rows = db.execute(sql, [match, *params, limit]).fetchall()
            else:
                terms = [t for t in like_terms if t][:6] or ["%"]
                like = " OR ".join("p.title LIKE ?" for _ in terms)
                sql = (
                    "SELECT p.*, e.name AS company, e.ats AS ats, e.id AS eid FROM postings p JOIN employers e ON e.id = p.employer_id "
                    f"WHERE ({like}) AND p.closed_at IS NULL AND e.enabled = 1" + date_clause + " LIMIT ?"
                )
                rows = db.execute(sql, [*[f"%{t}%" for t in terms], *params, limit]).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, Any]:
        """How much is saved: employers and open postings, overall and for each hiring system. Reads one small table, so it stays instant."""
        with self.session() as db:
            rows = db.execute(
                "SELECT ats, COUNT(*) AS employers, SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ready, "
                "SUM(CASE WHEN status IN ('error', 'unreachable') THEN 1 ELSE 0 END) AS failing, SUM(open_count) AS postings "
                "FROM employers WHERE enabled = 1 GROUP BY ats"
            ).fetchall()
        by_system = {
            r["ats"]: {"employers": r["employers"], "ready": r["ready"] or 0, "failing": r["failing"] or 0, "postings": r["postings"] or 0}
            for r in rows
        }
        return {
            "employers": sum(v["employers"] for v in by_system.values()),
            "ready": sum(v["ready"] for v in by_system.values()),
            "postings": sum(v["postings"] for v in by_system.values()),
            "by_system": by_system,
        }


def guess_name(ats: str, identifier: str) -> str:
    """A readable name from an employer's address, used until a real name is known."""
    slug = identifier.split("|")[1] if ats == "workday" and "|" in identifier else identifier
    slug = slug.removeprefix("eu:")
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w) or identifier
