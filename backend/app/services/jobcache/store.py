"""
The job cache: a local copy of employers' public job lists, in its own SQLite file.

It is kept apart from job_agent.db on purpose. Backups of your real data (jobs, profile, resumes) stay small, and this
copy can always be rebuilt by reading the employers again. Nothing here holds personal information.

Speed at any size comes from three things: only OPEN postings sit in the full-text index (closed ones are removed from
it), every filter the search uses has an index, and a search reads a bounded number of candidates, never the whole table.
"""

from __future__ import annotations

import re
import datetime as dt
import sqlite3
import threading
import time
import zlib
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.jobcache.agency import is_agency
from app.services.jobcache.text import is_vague_place, names_no_town

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

-- Answers from paid "find this board job on the employer's own site" lookups, so the same lookup is not paid for twice in a day.
CREATE TABLE IF NOT EXISTS lookups (
    board_key TEXT PRIMARY KEY,
    found_url TEXT,
    checked_at INTEGER NOT NULL
);
"""

# Columns added after the first release: (name, definition)
MIGRATIONS = (("description_z", "BLOB"), ("desc_hash", "TEXT"), ("agency", "INTEGER"), ("seen_date", "TEXT"), ("date_tried", "INTEGER"), ("place_tried", "INTEGER"))
TRUST_GAP_HOURS = 48  # a posting's first-seen day counts as a date only when the board was also read within this many hours before
DESCRIPTION_CAP = 8000  # characters of a posting's text kept (pay is read from the whole text before this)

FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS postings_fts USING fts5("
    "title, company, location, tokenize = 'porter unicode61 remove_diacritics 2')"
)

CLOSED_KEEP_DAYS = 30
DESC_FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS postings_desc_fts USING fts5(body, tokenize = 'porter unicode61 remove_diacritics 2')"
)
DESC_INDEX_CHARS = 2000  # the opening lines of a posting's description that search can read
DESC_READY_KEY = "desc_index_ready"
_INIT_LOCK = threading.Lock()
_INITIALISED: dict[str, bool] = {}  # path -> whether full-text search is available
_DESC_OK: dict[str, bool] = {}  # path -> whether the description index could be created


def desc_lead(text_: str | None) -> str:
    """The opening lines of a description as one line of plain text: what search reads of it."""
    return " ".join((text_ or "").split())[:DESC_INDEX_CHARS]


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
    description: str | None = None  # plain text of the posting, when the employer's list carries it for free
    agency: bool | None = None  # True / False when known, None when not decided


@dataclass
class RefreshResult:
    new: int = 0
    closed: int = 0
    total: int = 0


def now_ts() -> int:
    return int(time.time())


def pack_description(text_: str | None) -> tuple[bytes | None, str | None]:
    """(compressed text, short fingerprint) for a posting's description, or (None, None) when there is none."""
    body = (text_ or "").strip()[:DESCRIPTION_CAP]
    if not body:
        return None, None
    return zlib.compress(body.encode("utf-8"), 6), hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def unpack_description(blob: bytes | None) -> str | None:
    try:
        return zlib.decompress(blob).decode("utf-8") if blob else None
    except (zlib.error, UnicodeDecodeError):
        return None


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
                have = {r["name"] for r in conn.execute("PRAGMA table_info(postings)")}
                for column, ddl in MIGRATIONS:  # older copies gain the new columns; nothing is lost or rewritten
                    if column not in have:
                        conn.execute(f"ALTER TABLE postings ADD COLUMN {column} {ddl}")
                try:
                    conn.execute(FTS_SCHEMA)
                    fts = True
                except sqlite3.OperationalError:
                    fts = False  # this Python's SQLite has no full-text search: searches fall back to a plain scan
                try:
                    conn.execute(DESC_FTS_SCHEMA)  # a second, separate index: the first one is never altered
                    _DESC_OK[self.path] = fts
                except sqlite3.OperationalError:
                    _DESC_OK[self.path] = False
                conn.commit()
                try:
                    # Fixes names saved before the proper one was known. Housekeeping only: when a long background job holds the
                    # database it is skipped (and tried again the next time the app starts) rather than making a search wait.
                    conn.execute("PRAGMA busy_timeout=2000")
                    for row in conn.execute("SELECT id, ats, identifier, name FROM employers").fetchall():
                        proper = known_name(row["ats"], row["identifier"])
                        if proper and row["name"] != proper:
                            conn.execute("UPDATE employers SET name = ? WHERE id = ?", (proper, row["id"]))
                    conn.commit()
                except sqlite3.OperationalError:
                    conn.rollback()
            finally:
                conn.close()
            _INITIALISED[self.path] = fts
            return fts

    def _raw(self, busy_seconds: float = 30.0) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=busy_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(busy_seconds * 1000)}")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-20000")
        return conn

    @contextmanager
    def session(self, busy_seconds: float = 30.0) -> Iterator[sqlite3.Connection]:
        conn = self._raw(busy_seconds)
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

    def rename_employer(self, employer_id: int, name: str) -> None:
        with self.session() as db:
            db.execute("UPDATE employers SET name = ? WHERE id = ?", (name, employer_id))

    def find_employer(self, ats: str, identifier: str) -> int | None:
        """The id of an employer already in the saved lists, or None."""
        with self.session() as db:
            row = db.execute("SELECT id FROM employers WHERE ats = ? AND identifier = ?", (ats, identifier)).fetchone()
        return int(row["id"]) if row else None

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

    @property
    def has_desc(self) -> bool:
        return _DESC_OK.get(self.path, False)

    def _desc_delete(self, db: sqlite3.Connection, ids: list[int]) -> None:
        if self.has_desc and ids:
            db.executemany("DELETE FROM postings_desc_fts WHERE rowid = ?", [(i,) for i in ids])

    def _desc_insert(self, db: sqlite3.Connection, rows: list[tuple[int, str]]) -> None:
        if self.has_desc and rows:
            db.executemany("INSERT INTO postings_desc_fts (rowid, body) VALUES (?, ?)", rows)

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
            emp = db.execute("SELECT name, last_ok FROM employers WHERE id = ?", (employer_id,)).fetchone()
            if emp is None:
                return result
            company = emp["name"]
            existing = {
                r["ext_id"]: r
                for r in db.execute("SELECT id, ext_id, title, location, closed_at, desc_hash, agency FROM postings WHERE employer_id = ?", (employer_id,))
            }
            # A new posting's first-seen day stands in for its posting date ONLY when it is trustworthy: this board was read before,
            # within the last 48 hours, completely, and the list did not suddenly look brand new (an employer changing its job
            # numbers would make every old job look new today). Otherwise the date stays empty, which the app shows as "not listed".
            fresh = sum(1 for p in postings if p.ext_id and p.ext_id not in existing)
            trusted = (
                close_missing
                and bool(existing)
                and emp["last_ok"] is not None
                and 0 <= now - emp["last_ok"] <= TRUST_GAP_HOURS * 3600
                and fresh <= max(20, len(existing) // 2)
            )
            seen_day = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc).date().isoformat() if trusted else None
            seen: set[str] = set()
            fts_add: list[tuple[int, str, str, str]] = []
            fts_del: list[int] = []
            desc_add: list[tuple[int, str]] = []
            desc_del: list[int] = []
            for p in postings:
                if not p.ext_id or not p.title or not p.url or p.ext_id in seen:
                    continue
                seen.add(p.ext_id)
                row = existing.get(p.ext_id)
                posted = p.posted_at.isoformat() if p.posted_at else None
                blob, fingerprint = pack_description(p.description)
                decided = p.agency if p.agency is not None else is_agency(company, p.description)
                agency = None if decided is None else int(decided)
                if row is None:
                    cur = db.execute(
                        "INSERT INTO postings (employer_id, ext_id, title, location, work_type, pay_text, pay_mid, posted_at, url, first_seen, last_seen, "
                        "description_z, desc_hash, agency, seen_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (employer_id, p.ext_id, p.title[:300], (p.location or None) and p.location[:300], p.work_type, p.pay_text, p.pay_mid, posted, p.url[:1000], now, now,
                         blob, fingerprint, agency, None if p.posted_at else seen_day),
                    )
                    fts_add.append((int(cur.lastrowid), p.title[:300], company, (p.location or "")[:300]))
                    if desc_lead(p.description):
                        desc_add.append((int(cur.lastrowid), desc_lead(p.description)))
                    result.new += 1
                    continue
                new_loc = p.location
                if row["location"] and is_vague_place(new_loc) and not is_vague_place(row["location"]):
                    new_loc = row["location"]  # the list only says "3 Locations": keep the real places found when the posting was opened
                db.execute(
                    "UPDATE postings SET title = ?, location = ?, work_type = ?, pay_text = COALESCE(?, pay_text), "
                    "pay_mid = COALESCE(?, pay_mid), posted_at = COALESCE(?, posted_at), url = ?, last_seen = ?, closed_at = NULL WHERE id = ?",
                    (p.title[:300], (new_loc or None) and new_loc[:300], p.work_type, p.pay_text, p.pay_mid, posted, p.url[:1000], now, row["id"]),
                )
                if fingerprint and fingerprint != row["desc_hash"]:  # the text is saved again only when it is new or has changed
                    db.execute("UPDATE postings SET description_z = ?, desc_hash = ? WHERE id = ?", (blob, fingerprint, row["id"]))
                    desc_del.append(row["id"])
                    if desc_lead(p.description):
                        desc_add.append((row["id"], desc_lead(p.description)))
                if agency is not None and agency != row["agency"]:
                    db.execute("UPDATE postings SET agency = ? WHERE id = ?", (agency, row["id"]))
                changed = row["title"] != p.title[:300] or (row["location"] or "") != (new_loc or "")[:300]
                if row["closed_at"] is not None or changed:
                    fts_del.append(row["id"])
                    fts_add.append((row["id"], p.title[:300], company, (new_loc or "")[:300]))
            gone = [r["id"] for k, r in existing.items() if close_missing and k not in seen and r["closed_at"] is None]
            if gone:
                db.executemany("UPDATE postings SET closed_at = ? WHERE id = ?", [(now, i) for i in gone])
                fts_del.extend(gone)
                desc_del.extend(gone)
                result.closed = len(gone)
            self._fts_delete(db, fts_del)
            self._fts_insert(db, fts_add)
            self._desc_delete(db, desc_del)
            self._desc_insert(db, desc_add)
            open_now = db.execute("SELECT COUNT(*) AS n FROM postings WHERE employer_id = ? AND closed_at IS NULL", (employer_id,)).fetchone()["n"]
            db.execute(
                "UPDATE employers SET status = 'ok', fail_count = 0, last_error = NULL, last_checked = ?, last_ok = ?, next_check = ?, open_count = ? WHERE id = ?",
                (now, now, now + int(interval_hours * 3600), open_now, employer_id),
            )
        return result

    def vague_place_postings(self, limit: int, per_employer: int, only_systems: list[str] | None = None) -> list[dict[str, Any]]:
        """Open postings whose list says only "3 Locations" (or nothing): the busiest employers first, a few from each."""
        import os
        import time as _time

        t0 = _time.time()

        def trace(msg: str) -> None:  # OTTER_TRACE=1 prints how long each step took (to find what makes a batch slow)
            if os.environ.get("OTTER_TRACE"):
                print(f"    [places pick {_time.time() - t0:6.1f}s] {msg}", flush=True)

        sys_sql = f" AND e.ats IN ({','.join('?' for _ in only_systems)})" if only_systems else ""
        sys_args = list(only_systems or [])
        with self.session() as db:
            rows = db.execute(
                "SELECT p.id, p.url, p.location, p.employer_id FROM postings p JOIN employers e ON e.id = p.employer_id "
                "WHERE p.closed_at IS NULL AND e.enabled = 1 AND COALESCE(p.place_tried, 0) = 0 AND (p.location IS NULL OR p.location = '' OR p.location LIKE '%ocations%' "
                "OR p.location LIKE '%ultiple%' OR p.location LIKE '%arious%' OR p.location LIKE '%everal%' OR p.location LIKE '%nywhere%') "
                + sys_sql + " ORDER BY e.hits DESC, p.first_seen DESC LIMIT ?",
                [*sys_args, limit * 30],
            ).fetchall()
        trace(f"first query done ({len(rows)} rows)")
        taken: dict[int, int] = {}
        out: list[dict[str, Any]] = []
        for r in rows:
            if not is_vague_place(r["location"]) or taken.get(r["employer_id"], 0) >= per_employer:
                continue
            taken[r["employer_id"]] = taken.get(r["employer_id"], 0) + 1
            out.append({"id": r["id"], "url": r["url"], "location": r["location"]})
            if len(out) >= limit:
                break
        trace(f"{len(out)} picked from the first query")
        if len(out) < limit:  # then the ones that name only a state ("PA", "US; PA; NJ"): a city search cannot use them until the town is known
            with self.session() as db:
                short = [r[0] for r in db.execute("SELECT DISTINCT location FROM postings WHERE closed_at IS NULL AND location IS NOT NULL AND length(location) <= 40")]
                trace(f"distinct short places read ({len(short)})")
                state_only = [loc for loc in short if names_no_town(loc)]
                trace(f"state-only places found ({len(state_only)})")
                rows = []
                for i in range(0, len(state_only), 400):
                    chunk = state_only[i : i + 400]
                    rows += db.execute(
                        "SELECT p.id, p.url, p.location, p.employer_id FROM postings p JOIN employers e ON e.id = p.employer_id "
                        f"WHERE p.closed_at IS NULL AND e.enabled = 1 AND COALESCE(p.place_tried, 0) = 0 AND p.location IN ({','.join('?' for _ in chunk)})"
                        + sys_sql + " ORDER BY e.hits DESC, p.first_seen DESC LIMIT ?",
                        [*chunk, *sys_args, limit * 10],
                    ).fetchall()
                    trace(f"chunk {i // 400 + 1} of {(len(state_only) + 399) // 400} looked up ({len(rows)} rows so far)")
            for r in rows:
                if taken.get(r["employer_id"], 0) >= per_employer:
                    continue
                taken[r["employer_id"]] = taken.get(r["employer_id"], 0) + 1
                out.append({"id": r["id"], "url": r["url"], "location": r["location"]})
                if len(out) >= limit:
                    break
        return out

    def mark_place_tried(self, urls: list[str]) -> None:
        """Marks postings whose page was read and names no place, so they are not opened again."""
        if urls:
            with self.session() as db:
                db.executemany("UPDATE postings SET place_tried = 1 WHERE url = ? AND closed_at IS NULL", [(u,) for u in urls])

    def set_location(self, url: str, location: str) -> bool:
        """Saves the real places of an open posting whose list only said "3 Locations" (and keeps the place index in step). False if not found."""
        location = (location or "").strip()[:300]
        if not location:
            return False
        try:
            with self.session(busy_seconds=3.0) as db:  # a search must not wait long on a background job: a skipped save is redone next search
                row = db.execute(
                    "SELECT p.id, p.title, e.name AS company FROM postings p JOIN employers e ON e.id = p.employer_id WHERE p.url = ? AND p.closed_at IS NULL LIMIT 1", (url,)
                ).fetchone()
                if not row:
                    return False
                db.execute("UPDATE postings SET location = ? WHERE id = ?", (location, row["id"]))
                self._fts_delete(db, [row["id"]])
                self._fts_insert(db, [(row["id"], row["title"], row["company"], location)])
        except sqlite3.OperationalError:
            return False
        return True

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
                self._desc_delete(db, ids)
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
                    "SELECT p.*, e.name AS company, e.ats AS ats, e.id AS eid, e.last_ok AS read_ok FROM postings_fts f "
                    "JOIN postings p ON p.id = f.rowid JOIN employers e ON e.id = p.employer_id "
                    "WHERE postings_fts MATCH ? AND p.closed_at IS NULL AND e.enabled = 1" + date_clause +
                    " ORDER BY bm25(postings_fts, 10.0, 0.0, 0.5) LIMIT ?"
                )
                rows = db.execute(sql, [match, *params, limit]).fetchall()
            else:
                terms = [t for t in like_terms if t][:6] or ["%"]
                like = " OR ".join("p.title LIKE ?" for _ in terms)
                sql = (
                    "SELECT p.*, e.name AS company, e.ats AS ats, e.id AS eid, e.last_ok AS read_ok FROM postings p JOIN employers e ON e.id = p.employer_id "
                    f"WHERE ({like}) AND p.closed_at IS NULL AND e.enabled = 1" + date_clause + " LIMIT ?"
                )
                rows = db.execute(sql, [*[f"%{t}%" for t in terms], *params, limit]).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["description"] = unpack_description(d.pop("description_z", None))
            out.append(d)
        return out

    def desc_ready(self) -> bool:
        """True once the description index has been built for the postings already saved (see reindex_descriptions)."""
        return self.has_desc and self.meta_get(DESC_READY_KEY) == "1"

    def postings_without_description(self, limit: int, per_employer: int, skip_systems: set[str] | None = None, employer_ids: list[int] | None = None, only_systems: list[str] | None = None) -> list[tuple[int, str]]:
        """
        (id, link) of open postings that have no saved description and were not tried before. At most `per_employer` from any one
        employer (newest first), and the batch is spread across as many employers as possible: one posting from each employer
        (the busiest employers, the ones searches reach, first), then a second from each, and so on. A few very busy employers
        can no longer fill the whole batch, which kept batches tiny once they were close to done.
        """
        marks = ",".join("?" for _ in (skip_systems or ()))
        with self.session() as db:
            rows = db.execute(
                "SELECT id, url FROM ("
                " SELECT p.id, p.url, e.hits AS hits, ROW_NUMBER() OVER (PARTITION BY p.employer_id ORDER BY p.first_seen DESC) AS rn"
                " FROM postings p JOIN employers e ON e.id = p.employer_id"
                " WHERE p.closed_at IS NULL AND e.enabled = 1 AND p.description_z IS NULL AND p.desc_hash IS NULL"
                + (f" AND e.ats NOT IN ({marks})" if marks else "")
                + (f" AND e.id IN ({','.join('?' for _ in employer_ids)})" if employer_ids else "")
                + (f" AND e.ats IN ({','.join('?' for _ in only_systems)})" if only_systems else "")
                + ") WHERE rn <= ? ORDER BY rn, hits DESC LIMIT ?",
                [*(skip_systems or ()), *(employer_ids or ()), *(only_systems or ()), max(per_employer, 1), limit],
            ).fetchall()
        return [(r["id"], r["url"]) for r in rows]

    def undated_postings(self, systems: list[str], limit: int, per_employer: int) -> list[tuple[int, str]]:
        """(id, link) of open postings of these hiring systems with no posted date that were not looked at before: busiest employers first."""
        marks = ",".join("?" for _ in systems)
        with self.session() as db:
            rows = db.execute(
                "SELECT p.id, p.url, p.employer_id FROM postings p JOIN employers e ON e.id = p.employer_id "
                f"WHERE p.closed_at IS NULL AND e.enabled = 1 AND (p.posted_at IS NULL OR p.posted_at = '') AND p.date_tried IS NULL AND e.ats IN ({marks}) "
                "ORDER BY e.hits DESC, p.first_seen DESC LIMIT ?",
                [*systems, limit * 20],
            ).fetchall()
        taken: dict[int, int] = {}
        out: list[tuple[int, str]] = []
        for r in rows:
            if taken.get(r["employer_id"], 0) >= per_employer:
                continue
            taken[r["employer_id"]] = taken.get(r["employer_id"], 0) + 1
            out.append((r["id"], r["url"]))
            if len(out) >= limit:
                break
        return out

    def set_posted_at(self, posting_id: int, day: dt.date) -> bool:
        """Saves a posted date a job page published. A date the employer's list already gave is never replaced."""
        with self.session() as db:
            cur = db.execute(
                "UPDATE postings SET posted_at = ?, date_tried = 1 WHERE id = ? AND (posted_at IS NULL OR posted_at = '')", (day.isoformat(), posting_id)
            )
        return cur.rowcount > 0

    def mark_date_tried(self, posting_ids: list[int]) -> None:
        """Remembers that a posting's page was read and showed no date, so it is not opened again."""
        if posting_ids:
            with self.session() as db:
                db.executemany("UPDATE postings SET date_tried = 1 WHERE id = ?", [(i,) for i in posting_ids])

    def description_outcomes(self, posting_ids: list[int]) -> dict[str, dict[str, int]]:
        """For postings a fill tried: per hiring system, how many now have a description and how many were marked unreadable."""
        out: dict[str, dict[str, int]] = {}
        if not posting_ids:
            return out
        with self.session() as db:
            for start in range(0, len(posting_ids), 500):
                chunk = posting_ids[start : start + 500]
                for r in db.execute(
                    "SELECT e.ats AS ats, SUM(CASE WHEN p.description_z IS NOT NULL THEN 1 ELSE 0 END) AS got, "
                    "SUM(CASE WHEN p.description_z IS NULL THEN 1 ELSE 0 END) AS missed FROM postings p JOIN employers e ON e.id = p.employer_id "
                    f"WHERE p.id IN ({','.join('?' for _ in chunk)}) GROUP BY e.ats", chunk,
                ):
                    row = out.setdefault(r["ats"], {"saved": 0, "unreadable": 0})
                    row["saved"] += r["got"] or 0
                    row["unreadable"] += r["missed"] or 0
        return out

    def count_postings_without_description(self, skip_systems: set[str] | None = None) -> int:
        marks = ",".join("?" for _ in (skip_systems or ()))
        with self.session() as db:
            return db.execute(
                "SELECT COUNT(*) FROM postings p JOIN employers e ON e.id = p.employer_id WHERE p.closed_at IS NULL AND e.enabled = 1 "
                "AND p.description_z IS NULL AND p.desc_hash IS NULL" + (f" AND e.ats NOT IN ({marks})" if marks else ""),
                list(skip_systems or ()),
            ).fetchone()[0]

    def retry_unavailable(self, systems: list[str] | None = None) -> int:
        """Lets postings marked unreadable be tried again (all, or only those of the named hiring systems). Returns how many."""
        marks = ",".join("?" for _ in (systems or ()))
        with self.session() as db:
            cur = db.execute(
                "UPDATE postings SET desc_hash = NULL WHERE desc_hash = 'unavailable' AND description_z IS NULL"
                + (f" AND employer_id IN (SELECT id FROM employers WHERE ats IN ({marks}))" if marks else ""),
                list(systems or ()),
            )
            return cur.rowcount

    def mark_description_unavailable(self, posting_ids: list[int]) -> None:
        """Remembers that a posting's text could not be read, so it is not tried again on every refresh."""
        if not posting_ids:
            return
        with self.session() as db:
            db.executemany("UPDATE postings SET desc_hash = 'unavailable' WHERE id = ? AND description_z IS NULL", [(i,) for i in posting_ids])

    def set_description(self, posting_id: int, text_: str, max_chars: int | None = None) -> bool:
        """Saves the text of one posting (and its place in the description index). False when there was nothing to save."""
        blob, fingerprint = pack_description((text_ or "")[:max_chars] if max_chars else text_)
        if not blob:
            return False
        with self.session() as db:
            db.execute("UPDATE postings SET description_z = ?, desc_hash = ? WHERE id = ?", (blob, fingerprint, posting_id))
            if self.has_desc and desc_lead(text_):
                db.execute("DELETE FROM postings_desc_fts WHERE rowid = ?", (posting_id,))
                self._desc_insert(db, [(posting_id, desc_lead(text_))])
        return True

    def set_pay(self, posting_id: int, pay_text: str, pay_mid: float) -> bool:
        """Saves pay found in a posting's text, only when the posting has no pay yet (pay from the job list is never replaced)."""
        with self.session() as db:
            cur = db.execute(
                "UPDATE postings SET pay_text = ?, pay_mid = ? WHERE id = ? AND pay_mid IS NULL AND COALESCE(pay_text, '') = ''",
                (pay_text[:200], pay_mid, posting_id),
            )
            return cur.rowcount > 0

    def descriptions_without_pay(self, after_id: int = 0, limit: int = 2000) -> list[tuple[int, str]]:
        """Open postings that have a saved description but no pay, in id order from after_id: [(id, description text)]."""
        with self.session() as db:
            rows = db.execute(
                "SELECT id, description_z FROM postings WHERE id > ? AND closed_at IS NULL AND pay_mid IS NULL AND COALESCE(pay_text, '') = '' "
                "AND description_z IS NOT NULL AND desc_hash <> 'unavailable' ORDER BY id LIMIT ?",
                (after_id, limit),
            ).fetchall()
        return [(r["id"], unpack_description(r["description_z"]) or "") for r in rows]

    def reindex_descriptions(self, batch: int = 2000, progress: Any = None, rebuild: bool = False) -> int:
        """
        Builds the description index for every open posting that has a saved description and is not in it yet. Safe to run
        again and to stop part way: it only adds what is missing. With rebuild, every open posting's entry is written again
        (after the amount of text that search reads changed). Returns how many postings it added.
        """
        if not self.has_desc:
            return 0
        if rebuild:
            return self._rebuild_desc_index(batch, progress)
        added = 0
        while True:
            with self.session() as db:
                rows = db.execute(
                    "SELECT p.id, p.description_z FROM postings p WHERE p.closed_at IS NULL AND p.description_z IS NOT NULL "
                    "AND p.id NOT IN (SELECT rowid FROM postings_desc_fts) LIMIT ?",
                    (batch,),
                ).fetchall()
                if not rows:
                    break
                items = [(r["id"], desc_lead(unpack_description(r["description_z"]))) for r in rows]
                # a posting whose text unpacks to nothing still gets a row, so the loop always moves forward
                self._desc_insert(db, items)
            added += len(rows)
            if progress:
                progress(added)
        self.meta_set(DESC_READY_KEY, "1")
        return added

    def _rebuild_desc_index(self, batch: int, progress: Any) -> int:
        done, after = 0, 0
        while True:
            with self.session() as db:
                rows = db.execute(
                    "SELECT id, description_z FROM postings WHERE id > ? AND closed_at IS NULL AND description_z IS NOT NULL ORDER BY id LIMIT ?",
                    (after, batch),
                ).fetchall()
                if not rows:
                    break
                db.executemany("DELETE FROM postings_desc_fts WHERE rowid = ?", [(r["id"],) for r in rows])
                self._desc_insert(db, [(r["id"], desc_lead(unpack_description(r["description_z"]))) for r in rows])
            after = rows[-1]["id"]
            done += len(rows)
            if progress:
                progress(done)
        self.meta_set(DESC_READY_KEY, "1")
        return done

    def candidates_by_description(
        self, match: str, limit: int, earliest_posted: dt.date | None = None, exclude_ids: set[int] | None = None
    ) -> list[dict[str, Any]]:
        """Open postings whose description opening matches a full-text query, best matches first. Empty until the index is built."""
        if not self.desc_ready() or not match:
            return []
        params: list[Any] = []
        date_clause = ""
        if earliest_posted is not None:
            date_clause = " AND (p.posted_at IS NULL OR p.posted_at >= ?)"
            params.append(earliest_posted.isoformat())
        with self.session() as db:
            rows = db.execute(
                "SELECT p.*, e.name AS company, e.ats AS ats, e.id AS eid, e.last_ok AS read_ok FROM postings_desc_fts f "
                "JOIN postings p ON p.id = f.rowid JOIN employers e ON e.id = p.employer_id "
                "WHERE postings_desc_fts MATCH ? AND p.closed_at IS NULL AND e.enabled = 1" + date_clause +
                " ORDER BY bm25(postings_desc_fts) LIMIT ?",
                [match, *params, limit + len(exclude_ids or ())],
            ).fetchall()
        out = []
        for r in rows:
            if exclude_ids and r["id"] in exclude_ids:
                continue
            d = dict(r)
            d["description"] = unpack_description(d.pop("description_z", None))
            out.append(d)
            if len(out) >= limit:
                break
        return out

    def lookup_get(self, board_key: str, max_age_seconds: int) -> tuple[bool, str | None]:
        """(remembered, found link). `remembered` is False when nothing was stored in the last `max_age_seconds`."""
        with self.session() as db:
            row = db.execute("SELECT found_url, checked_at FROM lookups WHERE board_key = ?", (board_key,)).fetchone()
        if not row or now_ts() - row["checked_at"] > max_age_seconds:
            return False, None
        return True, row["found_url"]

    def lookup_put(self, board_key: str, found_url: str | None) -> None:
        with self.session() as db:
            db.execute(
                "INSERT INTO lookups (board_key, found_url, checked_at) VALUES (?, ?, ?) "
                "ON CONFLICT (board_key) DO UPDATE SET found_url = excluded.found_url, checked_at = excluded.checked_at",
                (board_key, found_url, now_ts()),
            )
            db.execute("DELETE FROM lookups WHERE checked_at < ?", (now_ts() - 7 * 86400,))  # old answers are never read again

    def open_postings_titled(self, title: str, limit: int = 30) -> list[dict[str, Any]]:
        """Open saved postings with exactly this title (any capitalisation), with their employer's name."""
        with self.session() as db:
            rows = db.execute(
                "SELECT p.url, p.title, p.location, e.name AS company FROM postings p JOIN employers e ON e.id = p.employer_id "
                "WHERE p.closed_at IS NULL AND e.enabled = 1 AND lower(p.title) = lower(?) LIMIT ?",
                (title.strip(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def locations_sample(self, limit: int = 4000) -> list[str]:
        """The places postings name, most common first, for city suggestions."""
        with self.session() as db:
            rows = db.execute(
                "SELECT location FROM postings WHERE location IS NOT NULL AND location LIKE '%, __%' "
                "GROUP BY location ORDER BY COUNT(*) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [r["location"] for r in rows]

    def titles_sample(self, query: str, limit: int = 400) -> list[tuple[str, int]]:
        """Open job titles that contain what was typed, with how many postings use each, for title suggestions."""
        q = "".join(c for c in query.lower() if c.isalnum() or c in " .'&")[:40].strip()
        if len(q) < 2:
            return []
        with self.session() as db:
            rows = db.execute(
                "SELECT title, COUNT(*) AS n FROM postings WHERE closed_at IS NULL AND lower(title) LIKE ? "
                "GROUP BY lower(title) ORDER BY n DESC LIMIT ?",
                (f"%{q}%", limit),
            ).fetchall()
        return [(r["title"], r["n"]) for r in rows]

    def titles_common(self, limit: int = 60000) -> list[tuple[str, int]]:
        """The most common open job titles with how many postings use each. Read once in the background and kept in memory,
        so typing in the title box never has to search the whole saved copy."""
        with self.session() as db:
            rows = db.execute(
                "SELECT title, COUNT(*) AS n FROM postings WHERE closed_at IS NULL AND title IS NOT NULL "
                "GROUP BY lower(title) ORDER BY n DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(r["title"], r["n"]) for r in rows]

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


# Names for employers whose list address gives a run-together or shortened name ("premierinc"), shown the way people write
# them. Keyed by a Workday address's "tenant" or, where one tenant hosts several companies, "tenant|site" (lower case).
WORKDAY_NAMES = {
    "huron": "Huron Consulting Group",
    "guidehouse": "Guidehouse",
    "premierinc": "Premier Inc.",
    "nordic": "Nordic Global",
    "tegria": "Tegria",
    "bakertilly": "Baker Tilly",
    "plantemoran": "Plante Moran",
    "crowe": "Crowe",
    "pcg": "Public Consulting Group",
    "alirahealth": "Alira Health",
    "ensemblehp": "Ensemble Health Partners",
    "r1rcm": "R1 RCM",
    "iqvia": "IQVIA",
    "rsm": "RSM",
    "fticonsulting": "FTI Consulting",
    "alvarezandmarsal": "Alvarez & Marsal",
    "cornerstone|cornerstoneresearch_careers": "Cornerstone Research",
    "roberthalf|protivitiexperiencedcareers": "Protiviti",  # Protiviti's careers site runs on Robert Half's Workday account
}
OTHER_NAMES = {
    ("lever", "pmaconsultants"): "PMA Consultants",
    ("oracle", "ebez.fa.us2.oraclecloud.com|cx_1"): "CBIZ",
    ("oracle", "ehzq.fa.us2.oraclecloud.com|cx_1"): "Grant Thornton",
    ("oracle", "eedu.fa.em3.oraclecloud.com|cx_1003"): "WTW",
    ("pinpoint", "igsinsights"): "IGS",
    ("breezy", "tyton-partners"): "Tyton Partners",
    ("breezy", "charted-inc"): "Charted Inc",
    ("bamboohr", "reptrak"): "RepTrak",
    ("workable", "rapdev"): "RapDev",
    ("jazzhr", "kaufmanhall"): "Kaufman Hall",
    ("jobvite", "medullan"): "Medullan",
    ("icims", "careers-berrydunn.icims.com"): "BerryDunn",
    ("taleo", "phh.tbe.taleo.net|phh01|thebridg12|40"): "The Bridgespan Group",
    ("phenom", "careers.bcg.com"): "Boston Consulting Group",
    ("successfactors", "careers.ey.com|ey"): "EY",
    ("dayforce", "finthrive|candidateportal|en-us"): "FinThrive",
    ("kpmg", "www.kpmguscareers.com"): "KPMG",
    ("deloitte", "apply.deloitte.com"): "Deloitte",
    ("talentbrew", "careers.unitedhealthgroup.com"): "UnitedHealth Group",
    ("jibe", "careers.amd.com"): "AMD",
}


def known_name(ats: str, identifier: str) -> str | None:
    """The proper name for an employer the app knows by address, or None."""
    ident = identifier.lower()
    if ats == "workday" and ident.count("|") == 2:
        _, tenant, site = ident.split("|")
        return WORKDAY_NAMES.get(f"{tenant}|{site}") or WORKDAY_NAMES.get(tenant)
    return OTHER_NAMES.get((ats, ident))


def guess_name(ats: str, identifier: str) -> str:
    """A readable name from an employer's address, used until a real name is known."""
    known = known_name(ats, identifier)
    if known:
        return known
    slug = identifier.split("|")[1] if ats == "workday" and "|" in identifier else identifier
    if ats == "oracle":
        slug = identifier.split(".")[0]
    if ats == "icims":
        slug = re.sub(r"^(careers|jobs)-|-(careers|jobs)$", "", identifier.split(".")[0])
    slug = slug.removeprefix("eu:")
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w) or identifier
