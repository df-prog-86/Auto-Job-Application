"""
Other names for the same job, from the O*NET database (U.S. Department of Labor, Employment and Training Administration),
so a search for "billing specialist" also finds "medical biller" without paying for an AI call.

The list is optional. Make it once with `python -m scripts.load_onet`; until then the AI lookup is used alone, as before.

This product includes information from the O*NET Database by the U.S. Department of Labor, Employment and Training
Administration (USDOL/ETA). Used under the CC BY 4.0 license. O*NET(R) is a trademark of USDOL/ETA. The titles were
reorganised into a search index; USDOL/ETA has not approved, endorsed, or tested these modifications.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.jobcache.text import all_stems, fold, level_of, split_titles

ATTRIBUTION = (
    "This product includes information from the O*NET Database by the U.S. Department of Labor, Employment and Training "
    "Administration (USDOL/ETA). Used under the CC BY 4.0 license (https://creativecommons.org/licenses/by/4.0/). "
    "O*NET(R) is a trademark of USDOL/ETA. The titles were reorganised into a search index; USDOL/ETA has not approved, "
    "endorsed, or tested these modifications."
)


def data_file() -> Path:
    return Path(settings.JOB_CACHE_PATH).parent / "onet" / "titles.json"


@lru_cache(maxsize=4)
def _index(path_str: str, mtime: float) -> tuple[list[tuple[str, list[str]]], dict[tuple[str, ...], list[int]], str | None]:
    """(occupations as (title, other titles), word-set -> occupation numbers, release name)."""
    occupations: list[tuple[str, list[str]]] = []
    by_words: dict[tuple[str, ...], list[int]] = {}
    release = None
    path = Path(path_str)
    if mtime and path.exists():
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
            release = data.get("release")
            for n, (title, alts) in enumerate(data.get("occupations", [])):
                names = [str(title)] + [str(a) for a in alts]
                occupations.append((str(title), [str(a) for a in alts]))
                for name in names:
                    key = tuple(sorted(set(all_stems(name))))
                    if key and n not in by_words.setdefault(key, []):
                        by_words[key].append(n)
        except (ValueError, OSError, TypeError, AttributeError):
            occupations, by_words, release = [], {}, None  # a damaged file is ignored
    return occupations, by_words, release


def _loaded() -> tuple[list[tuple[str, list[str]]], dict[tuple[str, ...], list[int]], str | None]:
    p = data_file()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _index(str(p), mtime)


def available() -> bool:
    return bool(_loaded()[0])


def release() -> str | None:
    return _loaded()[2]


def alternates(titles: str, limit: int = 8) -> list[str]:
    """
    Other titles for the work named by `titles` ("a, b" is two titles), same seniority, closest wording first.
    Only a title that O*NET knows by name (any word order) gets alternatives; nothing is guessed.
    """
    occupations, by_words, _ = _loaded()
    if not occupations:
        return []
    given = {fold(t) for t in split_titles(titles)}
    scored: dict[str, tuple[int, int]] = {}
    for title in split_titles(titles):
        stems = set(all_stems(title))
        level = level_of(title)
        for n in by_words.get(tuple(sorted(stems)), []):
            occ_title, alts = occupations[n]
            for name in [occ_title, *alts]:
                f = fold(name)
                other = level_of(name)
                if f in given or not (3 <= len(name) <= 80) or len(name.split()) > 8 or (other is not None and level is not None and other != level):
                    continue  # (a title that names no seniority is fine; one that names a different seniority is not)
                shared = len(stems & set(all_stems(name)))
                best = scored.get(name)
                if best is None or (-shared, len(name)) < best:
                    scored[name] = (-shared, len(name))
    ordered = sorted(scored, key=lambda k: (scored[k], k))
    out: list[str] = []
    seen = set(given)
    for name in ordered:
        f = fold(name)
        if f not in seen:
            seen.add(f)
            out.append(name.strip())
        if len(out) >= limit:
            break
    return out
