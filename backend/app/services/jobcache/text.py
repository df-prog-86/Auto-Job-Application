"""
Plain-text helpers shared by the readers and the matcher: word handling for job titles, pay figures, and places.
Everything here is pure (no network, no database) so it is easy to test and fast to run on thousands of postings.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

# ---- words ------------------------------------------------------------------------------------------------------

STOPWORDS = frozenset(
    "a an and at for in of on or the to with within de la".split()
)
# Shorthand people write in titles, expanded so "Sr. Mgr" and "Senior Manager" read the same.
ABBREVIATIONS = {
    "sr": "senior", "snr": "senior", "jr": "junior", "mgr": "manager", "mgmt": "management", "asst": "assistant",
    "assoc": "associate", "dir": "director", "coord": "coordinator", "rep": "representative", "eng": "engineer",
    "svp": "vp", "evp": "vp", "admin": "administrator", "ops": "operations", "hr": "hr",
}
# Words that say how senior a role is. They shape the ranking but are not required to appear (a search for
# "revenue cycle manager" still finds "Senior Revenue Cycle Manager").
SENIORITY_ONLY = frozenset({"senior", "junior", "lead", "principal", "i", "ii", "iii", "iv", "v", "1", "2", "3", "4"})
LEVELS = {
    "intern": 0, "internship": 0, "trainee": 0,
    "assistant": 1, "associate": 1, "junior": 1, "entry": 1, "coordinator": 1, "clerk": 1,
    "analyst": 2, "specialist": 2, "representative": 2, "engineer": 2, "technician": 2, "consultant": 2, "administrator": 2,
    "senior": 3, "lead": 3, "manager": 3, "supervisor": 3, "principal": 4,
    "director": 5, "head": 5, "vp": 6, "president": 6, "chief": 7,
}


def fold(text: str | None) -> str:
    """Lowercase, accents removed, punctuation turned into spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def words(text: str | None) -> list[str]:
    """The words of a title with shorthand expanded, in order, nothing dropped."""
    return [ABBREVIATIONS.get(w, w) for w in fold(text).split()]


def stem(word: str) -> str:
    """A light stem so "managers" and "manager" match. Deliberately simple: the search index does the heavy stemming."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    return word


def content_stems(text: str | None) -> list[str]:
    """The stems of the words that carry the meaning of a title: no filler words and no bare seniority words."""
    return [stem(w) for w in words(text) if w not in STOPWORDS and w not in SENIORITY_ONLY]


def all_stems(text: str | None) -> list[str]:
    return [stem(w) for w in words(text) if w not in STOPWORDS]


def level_of(text: str | None) -> int | None:
    """How senior a title reads, 0 (intern) to 7 (chief), or None when no word says."""
    found = [LEVELS[w] for w in words(text) if w in LEVELS]
    return max(found) if found else None


def split_titles(text: str) -> list[str]:
    """"Revenue cycle manager, patient financial services manager" -> two titles."""
    parts = re.split(r"[,;/\n|]|\s+or\s+", text, flags=re.I)
    return [p.strip() for p in parts if p and len(p.strip()) >= 2][:8]


# ---- pay --------------------------------------------------------------------------------------------------------

_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?")


def pay_midpoint(text: str | None) -> float | None:
    """Midpoint of a yearly pay range written as text ("$80,000 - $100,000", "85k"). None when unclear or hourly."""
    if not text:
        return None
    values: list[float] = []
    for number, k in _MONEY.findall(text)[:2]:
        value = float(number.replace(",", ""))
        values.append(value * 1000 if k else value)
    if not values or min(values) < 1000:
        return None
    return sum(values) / len(values)


# ---- work type --------------------------------------------------------------------------------------------------

def work_type_from(declared: str | None, location: str | None, title: str | None = None) -> str | None:
    """remote / hybrid / onsite when the system or the text says so, else None (unknown, never guessed as onsite)."""
    d = fold(declared)
    if d in ("remote", "fully remote"):
        return "remote"
    if d == "hybrid":
        return "hybrid"
    if d in ("onsite", "on site", "in office"):
        return "onsite"
    hay = f" {fold(location)} {fold(title)} "
    if " hybrid " in hay:
        return "hybrid"
    if " remote " in hay or " work from home " in hay or " telecommute " in hay:
        return "remote"
    return None


# ---- places -----------------------------------------------------------------------------------------------------

US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
    "CT": "connecticut", "DE": "delaware", "DC": "district of columbia", "FL": "florida", "GA": "georgia", "HI": "hawaii",
    "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey",
    "NM": "new mexico", "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina", "SD": "south dakota",
    "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
}
STATE_BY_NAME = {name: abbr for abbr, name in US_STATES.items()}
_NON_US = (
    "canada", "united kingdom", "england", "scotland", "ireland", "india", "germany", "france", "spain", "italy",
    "netherlands", "australia", "mexico", "brazil", "philippines", "poland", "singapore", "japan", "china", "israel",
    "argentina", "colombia", "portugal", "sweden", "romania", "ukraine", "costa rica", "south africa", "nigeria", "egypt",
    "pakistan", "bangladesh", "vietnam", "indonesia", "turkey", "switzerland", "denmark", "norway", "finland", "belgium",
    "emea", "apac", "latam", "europe", "uk",
)
_UNKNOWN_PLACE = re.compile(r"\b(\d+\s+locations?|multiple locations?|various|several locations?|locations? vary|anywhere)\b", re.I)


@dataclass
class LocationQuery:
    cities: list[str] = field(default_factory=list)
    states: set[str] = field(default_factory=set)
    remote: bool = False
    empty: bool = True


def parse_location_query(text: str | None) -> LocationQuery:
    """"Boston, MA or remote" -> city boston, state MA, remote ok."""
    if not text or not text.strip():
        return LocationQuery()
    q = LocationQuery(empty=False)
    raw = text.strip()
    for abbr in re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", raw):  # capitals only: "or" and "in" are not states
        if abbr in US_STATES:
            q.states.add(abbr)
    folded = fold(raw)
    for name, abbr in STATE_BY_NAME.items():
        if re.search(rf"\b{name}\b", folded):
            q.states.add(abbr)
    if re.search(r"\bremote\b|\bwork from home\b|\banywhere\b", folded):
        q.remote = True
    cleaned = re.sub(r"\bremote\b|\bhybrid\b|\bonsite\b|\bwork from home\b|\bunited states\b|\busa\b|\bus\b", " ", folded)
    for name in STATE_BY_NAME:
        cleaned = re.sub(rf"\b{name}\b", " ", cleaned)
    chunks = [fold(c) for c in re.split(r"[,;/|]|\s+or\s+|\s+and\s+", raw)]
    for chunk in chunks:
        chunk = re.sub(r"\bremote\b|\bhybrid\b|\bonsite\b|\bunited states\b|\busa\b|\bus\b", " ", chunk).strip()
        for name in STATE_BY_NAME:
            chunk = re.sub(rf"\b{name}\b", " ", chunk).strip()
        if chunk and chunk.upper() not in US_STATES and len(chunk) > 2:
            q.cities.append(re.sub(r"\s+", " ", chunk))
    if not q.cities and not q.states and not q.remote:
        q.cities = [re.sub(r"\s+", " ", cleaned)] if cleaned.strip() else []
    return q


def _states_in(location: str) -> set[str]:
    found = {a for a in re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", location) if a in US_STATES}
    folded = fold(location)
    for name, abbr in STATE_BY_NAME.items():
        if re.search(rf"\b{name}\b", folded):
            found.add(abbr)
    for m in re.finditer(r"\bUS-([A-Z]{2})\b", location):  # Workday style: US-MA-Boston
        if m.group(1) in US_STATES:
            found.add(m.group(1))
    return found


def is_vague_place(location: str | None) -> bool:
    """True when a posting does not name where the job is ("2 Locations", "Multiple locations", nothing at all)."""
    return not (location or "").strip() or bool(_UNKNOWN_PLACE.search(location or ""))


def location_fit(q: LocationQuery, location: str | None, work_type: str | None) -> float:
    """
    How well a posting's place fits the place asked for: 1.0 right there, 0.9 remote when remote is acceptable,
    0.7 same state, 0.5 the posting does not say where (kept, to be checked), 0.0 somewhere else.
    """
    if q.empty:
        return 1.0
    loc = (location or "").strip()
    remote_posting = work_type == "remote" or " remote " in f" {fold(loc)} "
    if not loc or _UNKNOWN_PLACE.search(loc):
        return 0.9 if remote_posting else 0.5
    folded = f" {fold(loc)} "
    wanted_states = q.states
    posting_states = _states_in(loc)
    foreign = any(f" {c} " in folded for c in _NON_US) and not posting_states and " united states " not in folded and " usa " not in folded and " us " not in folded
    if foreign and (wanted_states or not q.cities):
        return 0.0
    for city in q.cities:
        if f" {city} " in folded:
            if not wanted_states or not posting_states or wanted_states & posting_states:
                return 1.0
    if remote_posting and (q.remote or not q.cities):
        return 0.9
    if remote_posting and q.remote:
        return 0.9
    if wanted_states & posting_states:
        return 0.7 if q.cities else 1.0
    if remote_posting:
        return 0.6  # remote, but the person asked for a place and did not say remote is fine
    return 0.0


# ---- dates ------------------------------------------------------------------------------------------------------

def workday_posted(text: str | None, today: dt.date | None = None) -> dt.date | None:
    """Workday lists "Posted Today", "Posted 3 Days Ago", "Posted 30+ Days Ago". A rough date, refined when a job is opened."""
    if not text:
        return None
    today = today or dt.date.today()
    t = text.lower()
    if "today" in t:
        return today
    if "yesterday" in t:
        return today - dt.timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        return today - dt.timedelta(days=int(m.group(1)))
    return None
