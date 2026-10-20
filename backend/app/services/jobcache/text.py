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

_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kK])?")
HOURS_PER_YEAR = 2080


def pay_midpoint(text: str | None) -> float | None:
    """
    Midpoint of a pay range written as text, as a yearly figure: "$80,000 - $100,000", "$43,800.00 - $51,100.00", "85k".
    An hourly range ("$17.71 - $24.28") is turned into a yearly one (2,080 hours). None when unclear.
    """
    if not text:
        return None
    values: list[float] = []
    for number, k in _MONEY.findall(text)[:2]:
        value = float(number.replace(",", ""))
        values.append(value * 1000 if k else value)
    if not values:
        return None
    if min(values) >= 1000:
        return sum(values) / len(values)
    if 8 <= min(values) and max(values) <= 250:  # small numbers read as an hourly rate
        return sum(values) / len(values) * HOURS_PER_YEAR
    return None


# Pay written inside a posting's text ("The salary range is $85,000 - $110,000 per year", "$42 to $55 an hour").
_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d{1,7})(?:\.\d{1,2})?\s*([kK])?(?![\d,]*\s*(?:m\b|mm\b|million|billion|bn\b|b\b))"
_AMT2 = r"\$?\s?(\d{1,3}(?:,\d{3})+|\d{1,7})(?:\.\d{1,2})?\s*([kK])?"
_RANGE = re.compile(_AMT + r"\s*(?:-|\u2013|\u2014|to|and|through)\s*" + _AMT2, re.I)
_SINGLE = re.compile(_AMT)
_PAY_WORDS = re.compile(r"\b(salary|pay|compensation|base|wage|wages|hourly|range|rate|earn|earning|annual)\b", re.I)
_NOT_PAY = re.compile(r"\b(revenue|funding|raised|valuation|series [a-f]|budget|assets|sales|billion|million|bonus of|sign[- ]?on|referral|tuition|stipend|reimbursement)\b", re.I)
_HOURLY = re.compile(r"^\s*(?:/|per|an|a|each)?\s*(?:hour|hr|hourly)\b", re.I)
_YEARLY = re.compile(r"^\s*(?:/|per|a|an|each)?\s*(?:year|yr|annum|annual|annually|yearly)\b", re.I)


def html_to_text(markup: str | None) -> str:
    """A posting's markup as plain text: entities decoded (twice, some sites escape their own markup), tags turned into spaces."""
    import html as _html

    out = _html.unescape(_html.unescape(markup or ""))
    out = re.sub(r"<\s*(br|/p|/li|/div|/h\d|/tr)\b[^>]*>", "\n", out, flags=re.I)
    out = re.sub(r"<[^>]+>", " ", out)
    return re.sub(r"[ \t\r\f\v\u00a0]+", " ", out).replace(" \n", "\n").strip()


def _amount(number: str, k: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * 1000 if k else value


def pay_from_text(text_: str | None) -> tuple[str | None, float | None]:
    """
    A pay range found in free text, as (readable text, yearly midpoint), or (None, None). Careful on purpose: it needs a dollar sign,
    a believable range, and not a company's revenue, funding or a bonus. A single figure counts only next to a pay word
    ("starting salary of $82,000"). An hourly rate is turned into a yearly figure (2,080 hours). The first believable range wins.
    """
    if not text_:
        return None, None
    body = text_[:60000]
    ranges = [(m.start(), m.end()) for m in _RANGE.finditer(body)]  # a range that was turned down must not be read again as one figure
    for m in _RANGE.finditer(body):
        before = body[max(0, m.start() - 120) : m.start()]
        if _NOT_PAY.search(before[-50:]):
            continue
        lo, hi = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
        if m.group(2) and not m.group(4) and hi < 1000:  # "$85K - 110" : the K applies to both
            hi *= 1000
        after = body[m.end() : m.end() + 24]
        hourly = bool(_HOURLY.match(after))
        yearly = bool(_YEARLY.match(after))
        if lo > hi:
            continue
        if hourly or (not yearly and hi <= 250):
            if not (8 <= lo and hi <= 250 and hi <= lo * 3):
                continue
            if not hourly and not _PAY_WORDS.search(before):
                continue  # small numbers with no "per hour" and no pay word are not pay
            return f"${lo:,.2f} - ${hi:,.2f} / hour".replace(".00", ""), (lo + hi) / 2 * HOURS_PER_YEAR
        if not (20000 <= lo and hi <= 1500000 and hi <= lo * 3):
            continue
        return f"${lo:,.0f} - ${hi:,.0f} / year", (lo + hi) / 2
    for m in _SINGLE.finditer(body):
        if any(a <= m.start() < b for a, b in ranges):
            continue
        before = body[max(0, m.start() - 60) : m.start()]
        if not _PAY_WORDS.search(before) or _NOT_PAY.search(before):
            continue
        value = _amount(m.group(1), m.group(2))
        after = body[m.end() : m.end() + 24]
        if _HOURLY.match(after) and 8 <= value <= 250:
            return f"${value:,.2f} / hour".replace(".00", ""), value * HOURS_PER_YEAR
        if 20000 <= value <= 1500000:
            return f"${value:,.0f} / year", value
    return None, None


_LOC_LABEL = re.compile(
    r"(?:^|\n)\s*(?i:(?:job |work |office |primary )?location(?:s)?)\s*[:\-]\s*([A-Z][A-Za-z.'\- ]{2,40}),\s*([A-Z]{2})\b"
)


def location_from_text(text_: str | None) -> str | None:
    """
    "City, ST" when a posting's text states it on a labelled line ("Location: Waltham, MA"), else None. Only an explicit label counts:
    a city mentioned in passing ("our Boston headquarters") is never taken as the job's place.
    """
    m = _LOC_LABEL.search(text_ or "")
    if m and m.group(2) in US_STATES:
        return f"{m.group(1).strip()}, {m.group(2)}"
    return None


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
    "greece", "malta", "lithuania", "latvia", "estonia", "hungary", "czechia", "czech republic", "slovakia", "slovenia", "croatia",
    "serbia", "bulgaria", "austria", "russia", "luxembourg", "iceland", "cyprus", "morocco", "tunisia", "algeria", "kenya", "ghana",
    "ethiopia", "tanzania", "uganda", "senegal", "ivory coast", "saudi arabia", "united arab emirates", "uae", "qatar", "kuwait",
    "bahrain", "oman", "jordan", "lebanon", "iraq", "iran", "peru", "chile", "uruguay", "paraguay", "bolivia", "ecuador", "venezuela",
    "panama", "guatemala", "honduras", "el salvador", "nicaragua", "dominican republic", "jamaica", "trinidad", "bahamas", "bermuda",
    "thailand", "malaysia", "south korea", "korea", "taiwan", "hong kong", "new zealand", "sri lanka", "nepal", "kazakhstan",
    "uzbekistan", "turkiye", "republic of georgia", "armenia", "azerbaijan", "belarus", "moldova", "albania", "north macedonia",
    "bosnia", "montenegro", "kosovo", "lithuania",
)
_UNKNOWN_PLACE = re.compile(r"\b(\d+\s+locations?|multiple locations?|various|several locations?|locations? vary|anywhere)\b", re.I)


@dataclass
class LocationQuery:
    nationwide: bool = False  # "United States" with no city or state: anywhere in the US
    cities: list[str] = field(default_factory=list)
    states: set[str] = field(default_factory=set)
    remote: bool = False
    empty: bool = True
    near: list[tuple[str, str | None]] = field(default_factory=list)  # nearby places (city, state) that count as "around there"


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
    if not q.cities and not q.states and re.search(r"\bunited states\b|\busa\b|\bus\b", folded):
        q.nationwide = True
    if not q.cities and not q.states and not q.remote and not q.nationwide:
        q.cities = [re.sub(r"\s+", " ", cleaned)] if cleaned.strip() else []
    return q


def place_ref(text_: str | None) -> tuple[str, str | None] | None:
    """"Cambridge, MA" -> ("cambridge", "MA"); "Cambridge" -> ("cambridge", None). None when there is no usable city."""
    if not text_ or not text_.strip():
        return None
    head, _, tail = text_.strip().rpartition(",")
    city, state = (head, tail) if head else (text_, "")
    state = state.strip()
    abbr = state.upper() if state.upper() in US_STATES else STATE_BY_NAME.get(fold(state))
    city = fold(city if abbr or not state else text_)
    return (city, abbr) if len(city) > 2 else None


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
    if q.nationwide:  # anywhere in the US: a US place counts fully, a place that says nothing is kept to be checked
        us_place = bool(posting_states) or " united states " in folded or " usa " in folded
        return 1.0 if us_place else (0.9 if remote_posting else 0.5)
    for city in q.cities:
        if f" {city} " in folded:
            if not wanted_states or not posting_states or wanted_states & posting_states:
                return 1.0
    for near_city, near_state in q.near:  # the greater area: Cambridge and Somerville count for a search in Boston
        if f" {near_city} " in folded and (near_state is None or not posting_states or near_state in posting_states):
            return 0.95
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


# ---- employer and title tidying ---------------------------------------------------------------------------------

# Employers whose list address gives a run-together or shortened name ("danafarber"), shown the way people write them.
COMPANY_NAMES = {
    "danafarber": "Dana-Farber Cancer Institute",
    "massgeneralbrigham": "Mass General Brigham",
    "hcsc": "HCSC",
    "bilh": "Beth Israel Lahey Health",
    "intersystems": "InterSystems",
    "genetixbiotherapeutics": "Genetix Biotherapeutics",
}
_ORG_CODE = re.compile(r"^(?:[A-Za-z]{1,4}\d{2,6}|\d{3,6})\s+(?=\S)")  # "1000 Abbott ...", "LE001 Berkeley ..."
_TRAIL_CODE = re.compile(r"\s*\((?:[A-Za-z]{2,6})\)\s*$")  # "Inc(ALI)"


def _squash(text_: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text_ or "").lower())


def clean_company(name: str | None) -> str:
    """An employer's name without the system's internal codes ("1000 Abbott Laboratories Inc(ALI)" -> "Abbott Laboratories Inc")."""
    out = re.sub(r"\s+", " ", name or "").strip()
    cleaned = _TRAIL_CODE.sub("", _ORG_CODE.sub("", out)).strip(" ,-")
    out = cleaned or out
    return COMPANY_NAMES.get(_squash(out), out)


def clean_title(title: str | None, company: str | None = None) -> str:
    """A job title without a trailing "at <Employer>" ("Program Manager at Massgeneralbrigham" -> "Program Manager")."""
    out = re.sub(r"\s+", " ", title or "").strip()
    if not company:
        return out
    squashed = {_squash(company), _squash(clean_company(company))} - {""}
    m = re.search(r"\s+(?:at|@|-|\|)\s+([^@|]+)$", out)
    if m and _squash(m.group(1)) in squashed:
        shorter = out[: m.start()].strip()
        return shorter or out
    return out
