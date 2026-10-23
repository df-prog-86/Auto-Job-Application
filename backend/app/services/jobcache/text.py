"""
Plain-text helpers shared by the readers and the matcher: word handling for job titles, pay figures, and places.
Everything here is pure (no network, no database) so it is easy to test and fast to run on thousands of postings.
"""

from __future__ import annotations

import datetime as dt
import html as html_lib
import json
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

_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kK](?![a-zA-Z]))?"
_PAIR = re.compile(r"\$?\s*" + _NUM + r"\s*(?:-|\u2013|\u2014|to)\s*\$?\s*" + _NUM, re.I)
_ONE = re.compile(r"\$?\s*" + _NUM)
_FOREIGN = re.compile(r"[\u20ac\u00a3\u00a5\u20b9\u20a9\u20bd]|\b(?:EUR|GBP|HUF|CAD|AUD|INR|JPY|CNY|CHF|SEK|NOK|DKK|PLN|MXN|BRL|SGD|NZD|ZAR|PHP|CZK|RON|AED)\b")
_PER_MONTH = re.compile(r"^\W{0,3}(?:/|per|a|each|every)?\s*(?:month|mo)\b|^\W{0,3}monthly", re.I)
_PER_BIWEEK = re.compile(r"^\W{0,3}(?:/|per|every)?\s*(?:bi-?weekly|two weeks|pay period)", re.I)
_PER_WEEK = re.compile(r"^\W{0,3}(?:/|per|a|each)?\s*(?:week|wk)\b|^\W{0,3}weekly", re.I)
_PER_HOUR = re.compile(r"^\W{0,3}(?:/|per|an|a|each)?\s*(?:hour|hr)\b|^\W{0,3}hourly", re.I)
HOURS_PER_YEAR = 2080


def pay_midpoint(text: str | None) -> float | None:
    """
    Midpoint of a pay range written as text, as a yearly figure: "$80,000 - $100,000", "$43,800.00 - $51,100.00", "85k".
    Hourly ("$17.71 - $24.28", 2,080 hours), monthly (x12), weekly (x52) and bi-weekly (x26) pay is turned into a yearly figure.
    Only the first range (or else the first figure) counts, so a bonus mentioned afterwards cannot change it. Money in another
    currency gives None, as does anything unclear.
    """
    if not text or _FOREIGN.search(text):
        return None
    m = _PAIR.search(text)
    if m:
        lo, k1, hi, k2 = float(m.group(1).replace(",", "")), m.group(2), float(m.group(3).replace(",", "")), m.group(4)
        if k1 and not k2 and hi < 1000:
            hi *= 1000
        elif k2 and not k1 and lo < 1000:
            lo *= 1000
        lo, hi = (lo * 1000 if k1 else lo), (hi * 1000 if k2 else hi)
        if lo > hi:
            return None
        end = m.end()
    else:
        m = _ONE.search(text)
        if not m:
            return None
        lo = hi = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        end = m.end()
    mid, after = (lo + hi) / 2, text[end : end + 30]
    if _PER_BIWEEK.match(after):
        return mid * 26 if 200 <= lo and hi <= 10000 else None
    if _PER_WEEK.match(after):
        return mid * 52 if 100 <= lo and hi <= 20000 else None
    if _PER_MONTH.match(after):
        return mid * 12 if 500 <= lo and hi <= 60000 else None
    if _PER_HOUR.match(after):
        return mid * HOURS_PER_YEAR if 2 <= lo and hi <= 250 else None
    if lo >= 1000:
        return mid
    if 8 <= lo and hi <= 250:  # small numbers read as an hourly rate
        return mid * HOURS_PER_YEAR
    return None


_LEGAL_WORDS = {"inc", "llc", "ltd", "corp", "co", "company", "corporation", "the", "plc", "lp", "llp", "incorporated", "limited"}


def _name_words(name: str | None) -> list[str]:
    cleaned = (name or "").lower().replace("&", " and ").replace("'", "").replace("\u2019", "")
    return [w for w in re.findall(r"[a-z0-9]+", cleaned) if w not in _LEGAL_WORDS]


def _has_run(big: list[str], small: list[str]) -> bool:
    n = len(small)
    return n > 0 and any(big[i : i + n] == small for i in range(len(big) - n + 1))


def name_excluded(company: str | None, excluded: list[str]) -> bool:
    """
    Whether a company is one the person asked to leave out. Whole words only, ignoring case, punctuation and "Inc"/"LLC":
    "Care" leaves out "Care.com" but not "Vertexcareers", "Acme" leaves out "Acme Corp", and "Amazon Web Services" leaves out "Amazon".
    """
    words = _name_words(company)
    if not words:
        return False
    for e in excluded:
        theirs = _name_words(e)
        if _has_run(words, theirs) or _has_run(theirs, words):
            return True
    return False


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

def remote_from_flag(flag: object, location: str | None) -> str | None:
    """
    "remote" for a hiring system's yes/no remote flag, but only when the job does not also name a place to go to. Several systems
    set the flag on any job that allows some remote work, so "Baton Rouge, LA" with the flag is not a remote job: unknown (None).
    """
    if flag is not True:
        return None
    loc = fold(location)
    if not loc.strip() or " remote " in f" {loc} " or "work from home" in loc or "anywhere" in loc or names_no_town(location):
        return "remote"
    return None


def work_type_from(declared: str | None, location: str | None, title: str | None = None) -> str | None:
    """remote / hybrid / onsite when the system or the text says so, else None (unknown, never guessed as onsite)."""
    d = fold(declared)
    if d in ("remote", "fully remote"):
        if " hybrid " in f" {fold(location)} {fold(title)} ":
            return "hybrid"  # a system's "remote allowed" flag on a job whose own words say hybrid
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
    "emea", "apac", "latam", "europe", "uk", "european union", "european", "eu", "dach", "nordics", "asia", "africa",
    "middle east", "latin america", "south america", "anz", "mena",
    "greece", "malta", "lithuania", "latvia", "estonia", "hungary", "czechia", "czech republic", "slovakia", "slovenia", "croatia",
    "serbia", "bulgaria", "austria", "russia", "luxembourg", "iceland", "cyprus", "morocco", "tunisia", "algeria", "kenya", "ghana",
    "ethiopia", "tanzania", "uganda", "senegal", "ivory coast", "saudi arabia", "united arab emirates", "uae", "qatar", "kuwait",
    "bahrain", "oman", "jordan", "lebanon", "iraq", "iran", "peru", "chile", "uruguay", "paraguay", "bolivia", "ecuador", "venezuela",
    "panama", "guatemala", "honduras", "el salvador", "nicaragua", "dominican republic", "jamaica", "trinidad", "bahamas", "bermuda",
    "thailand", "malaysia", "south korea", "korea", "taiwan", "hong kong", "new zealand", "sri lanka", "nepal", "kazakhstan",
    "uzbekistan", "turkiye", "republic of georgia", "armenia", "azerbaijan", "belarus", "moldova", "albania", "north macedonia",
    "bosnia", "montenegro", "kosovo", "lithuania",
    # big non-US cities a posting may name with no country ("Montreal", "Bangalore"). One that is also a US town needs no state here
    # to be foreign: a US posting names its state, and a place that names a US state is never treated as foreign.
    "montreal", "toronto", "vancouver", "ottawa", "calgary", "edmonton", "winnipeg", "quebec", "mississauga", "london", "dublin",
    "paris", "berlin", "munich", "amsterdam", "madrid", "barcelona", "lisbon", "milan", "zurich", "geneva", "stockholm", "copenhagen",
    "oslo", "helsinki", "brussels", "warsaw", "krakow", "prague", "budapest", "bucharest", "sofia", "kyiv", "tel aviv", "dubai",
    "abu dhabi", "riyadh", "istanbul", "bangalore", "bengaluru", "hyderabad", "mumbai", "pune", "chennai", "gurgaon", "gurugram",
    "noida", "delhi", "kolkata", "manila", "cebu", "jakarta", "bangkok", "hanoi", "ho chi minh", "kuala lumpur", "seoul", "tokyo",
    "osaka", "beijing", "shanghai", "shenzhen", "taipei", "sydney", "melbourne", "brisbane", "auckland", "sao paulo", "rio de janeiro",
    "buenos aires", "bogota", "mexico city", "guadalajara", "monterrey", "lima", "santiago", "johannesburg", "cape town", "nairobi",
    "lagos", "cairo", "casablanca",
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
    abbrs_typed = {abbr for abbr in re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", raw) if abbr in US_STATES}
    for chunk in chunks:
        chunk = re.sub(r"\bremote\b|\bhybrid\b|\bonsite\b|\bunited states\b|\busa\b|\bus\b", " ", chunk).strip()
        chunk = re.sub(r"^(new york)\s+city$|^nyc$", "new york", chunk)
        if chunk == "new york" and ("NY" in abbrs_typed or re.search(r"\bnew york\s+city\b|\bnyc\b", folded)):
            # "New York, NY" and "New York City" name the city: the state of the same name is not a state-wide search
            q.cities.append("new york")
            q.states.add("NY")
            continue
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


def effective_work_type(work_type: str | None, location: str | None) -> str | None:
    """
    The work type a job is shown and filtered by, as on LinkedIn and Indeed: remote or hybrid only when the employer says so, on site
    for every other job that has a place, and unknown only when the place itself is unknown ("3 Locations", a state alone, nothing).
    """
    if work_type:
        return work_type
    if is_vague_place(location) or names_no_town(location):
        return None
    return "onsite"


def title_names_foreign(title: str | None) -> bool:
    """True when a remote job's title puts it in another country ("REMOTE (INDIA): Project Coordinator") and says nothing of the US."""
    folded = f" {fold(title)} "
    if " remote " not in folded and " work from home " not in folded:
        return False
    if any(f" {us} " in folded for us in ("us", "usa", "united states", "u s")):
        return False
    return any(f" {c} " in folded for c in _NON_US)


def names_no_town(location: str | None) -> bool:
    """True when a place gives only a state or country ("PA", "US; PA; NJ"): it says which state, but not which town."""
    folded = fold(location or "")
    if not folded.strip():
        return False
    left = re.sub(r"\b(united states|usa|us)\b", " ", f" {folded} ")
    for name in STATE_BY_NAME:
        left = re.sub(rf"\b{name}\b", " ", left)
    left = re.sub(r"\b[a-z]{2}\b", " ", left)
    return not re.search(r"[a-z]{3,}", left)


REMOTE_ELSEWHERE = 0.75  # a remote job (based anywhere) in a search that names a city: kept, but behind jobs in that city


def location_fit(q: LocationQuery, location: str | None, work_type: str | None) -> float:
    """
    How well a posting's place fits the place asked for: 1.0 right there, 0.95 in the greater area, 0.75 remote when "or remote" was
    asked for, 0.4 the posting does not say where (kept, to be checked), 0.0 anywhere else (another town in the state included).
    A search for a state alone, or for the whole US, is unchanged.
    """
    if q.empty:
        return 1.0
    loc = (location or "").strip()
    remote_posting = work_type == "remote" or " remote " in f" {fold(loc)} "
    if not loc or _UNKNOWN_PLACE.search(loc):
        # "2 Locations" or no place at all: kept, since one of them may be the place asked for, but behind jobs that say so
        if remote_posting:
            return (REMOTE_ELSEWHERE if q.remote else 0.0) if q.cities else 0.9
        return 0.4 if q.cities else 0.5
    folded = f" {fold(loc)} "
    wanted_states = q.states
    posting_states = _states_in(loc)
    foreign = any(f" {c} " in folded for c in _NON_US) and not posting_states and " united states " not in folded and " usa " not in folded and " us " not in folded
    if foreign:  # the launch market is the US: a job placed in another country is never shown, remote or not
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
        # remote is welcome only when asked for ("or remote"), and a job in the city asked for comes first
        return REMOTE_ELSEWHERE if q.cities else 0.9
    if wanted_states & posting_states:
        if not q.cities:
            return 1.0
        leftover = re.sub(r"\b(united states|usa|us)\b", " ", folded)
        for name in STATE_BY_NAME:
            leftover = re.sub(rf"\b{name}\b", " ", leftover)
        leftover = re.sub(r"\b[a-z]{2}\b", " ", leftover)  # state abbreviations
        # a city search is a filter: another town in the same state is not the place asked for. A posting that gives only the state
        # (no town at all) is kept, behind jobs that name the city, to be checked.
        return 0.4 if not re.search(r"[a-z]{3,}", leftover) else 0.0
    return 0.0  # somewhere else, or remote when remote was not asked for


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
    "openai": "OpenAI",
    "1password": "1Password",
    "assorthealth": "AssortHealth",
    "doordash": "DoorDash",
    "paypal": "PayPal",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "gitlab": "GitLab",
    "hubspot": "HubSpot",
    "mongodb": "MongoDB",
    "datadog": "Datadog",
    "pagerduty": "PagerDuty",
    "airbnb": "Airbnb",
    "zoominfo": "ZoomInfo",
    "servicenow": "ServiceNow",
    "appfolio": "AppFolio",
    "sofi": "SoFi",
    "athenahealth": "athenahealth",
    "bmc": "BMC",
    "bestwestern": "Best Western",
    "livekit": "LiveKit",
    "gomining": "GoMining",
    "launchdarkly": "LaunchDarkly",
    "brightwheel": "Brightwheel",
    "dialysisclinic": "Dialysis Clinic",
    "careerschwab": "Charles Schwab",
    "mmc": "Marsh McLennan",
    "msk": "Memorial Sloan Kettering Cancer Center",
    "fticonsulting": "FTI Consulting",
}
# A run-together name ("Examplehealth") gets a space before a common last word ("Example Health").
_NAME_TAILS = ("health", "healthcare", "biosciences", "pharma", "therapeutics", "systems", "software", "labs",
               "technologies", "medical", "financial", "capital", "solutions", "analytics", "networks", "clinic", "hospital",
               "institute", "foundation", "university", "pharmacy")
_RUN_TOGETHER = re.compile(r"^[A-Za-z]{7,}$")
_ORG_CODE = re.compile(r"^(?:[A-Za-z]{1,4}\d{2,6}|\d{3,6})\s+(?=\S)")  # "1000 Abbott ...", "LE001 Berkeley ..."
_TRAIL_CODE = re.compile(r"\s*\((?:[A-Za-z]{2,6})\)\s*$")  # "Inc(ALI)"


def decode_text(text_: str | None) -> str:
    """Text with HTML entities turned into characters ("Johnson &amp; Johnson" -> "Johnson & Johnson", even when escaped twice) and spaces tidied."""
    out = text_ or ""
    for _ in range(3):
        decoded = html_lib.unescape(out)
        if decoded == out:
            break
        out = decoded
    return re.sub(r"\s+", " ", out).strip()


def _squash(text_: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text_ or "").lower())


def clean_company(name: str | None) -> str:
    """An employer's name without the system's internal codes ("1000 Abbott Laboratories Inc(ALI)" -> "Abbott Laboratories Inc")."""
    out = decode_text(name)
    cleaned = _TRAIL_CODE.sub("", _ORG_CODE.sub("", out)).strip(" ,-")
    out = cleaned or out
    known = COMPANY_NAMES.get(_squash(out))
    if known:
        return known
    if _RUN_TOGETHER.match(out) and (out.islower() or out == out.capitalize()):
        low = out.lower()
        for tail in _NAME_TAILS:
            if low.endswith(tail) and len(low) - len(tail) >= 3:
                return f"{out[: len(out) - len(tail)].capitalize()} {tail.capitalize()}"
        return out.capitalize()
    return out


_LD_JSON = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
_SITE_NAME = (
    re.compile(r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']+)", re.I),
    re.compile(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']og:site_name[\"']", re.I),
)


def _hiring_org(node: object) -> str | None:
    if isinstance(node, list):
        for n in node:
            found = _hiring_org(n)
            if found:
                return found
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        org = node.get("hiringOrganization")
        if "JobPosting" in kinds and org:
            name = org.get("name") if isinstance(org, dict) else org
            if isinstance(name, str) and name.strip():
                return name
        for key in ("@graph", "mainEntity"):
            found = _hiring_org(node.get(key))
            if found:
                return found
    return None


def company_from_page(page: str | None) -> str | None:
    """The employer's own name as a job page states it: the hiring organisation in the posting's data, else the site name."""
    if not page:
        return None
    for m in _LD_JSON.finditer(page):
        try:
            name = _hiring_org(json.loads(html_lib.unescape(m.group(1)).strip()))
        except ValueError:
            continue
        if name:
            return re.sub(r"\s+", " ", html_lib.unescape(name)).strip()[:80] or None
    for pattern in _SITE_NAME:
        m = pattern.search(page)
        if m:
            return re.sub(r"\s+", " ", html_lib.unescape(m.group(1))).strip()[:80] or None
    return None


def same_company(guess: str | None, found: str | None) -> bool:
    """True when a name read from a page is the same employer as the one guessed from its address ("Morganlewis" and "Morgan, Lewis & Bockius LLP")."""
    a, b = _squash(guess), _squash(found)
    return len(a) >= 4 and len(b) >= 4 and (a in b or b in a)


_DATE_POSTED = (
    re.compile(r'datePosted\\?"\s*:\s*\\?"([^"\\]+)', re.I),  # structured details, plain or inside an escaped string (iCIMS)
    re.compile(r"itemprop=[\"']datePosted[\"'][^>]*content=[\"']([^\"']+)", re.I),
    re.compile(r"content=[\"']([^\"']+)[\"'][^>]*itemprop=[\"']datePosted[\"']", re.I),
)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def parse_posted_value(value: str | None) -> dt.date | None:
    """
    A posted date as employers write it: 2026-10-15, 2026-10-15 00:00:00.0, 2026-01-02T15:49:12+00:00, "Oct 1, 2026",
    "Sun Oct 18 02:00:00 UTC 2026", 10/15/2026. None when it is not a date, in the future, or before 2015.
    """
    v = html_lib.unescape(value or "").strip()
    day: dt.date | None = None
    try:
        if re.match(r"\d{4}-\d{2}-\d{2}", v):
            day = dt.date.fromisoformat(v[:10])
        elif m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v):
            day = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        elif m := re.search(r"(?i)\b([a-z]{3})[a-z]*\.? (\d{1,2}),? (?:[\d:]+ [A-Z]{2,4} )?(\d{4})", v):
            day = dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        elif m := re.search(r"(?i)\b([a-z]{3}) (\d{1,2}) [\d:]+ [A-Z]{2,4} (\d{4})", v):
            day = dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    except (ValueError, KeyError):
        return None
    if day is None or day < dt.date(2015, 1, 1) or day > dt.date.today() + dt.timedelta(days=1):
        return None
    return day


def posted_from_page(page: str | None) -> dt.date | None:
    """The posted date a job page publishes for search engines (datePosted), or None."""
    for pattern in _DATE_POSTED:
        for m in pattern.finditer(page or ""):
            day = parse_posted_value(m.group(1))
            if day:
                return day
    return None


_COUNTRY = re.compile(
    r'"addressCountry"\s*:\s*(?:"([^"]{2,60})"|\{[^{}]*?"name"\s*:\s*"([^"]{2,60})")|itemprop=["\']addressCountry["\'][^>]*content=["\']([^"\']{2,60})', re.I
)
_US_COUNTRY = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america", "america"}


def country_from_page(page: str | None) -> str | None:
    """The country a job page publishes for search engines (jobLocation addressCountry), or None."""
    m = _COUNTRY.search((page or "")[:800000].replace('\\"', '"'))
    if not m:
        return None
    return html_lib.unescape(next(g for g in m.groups() if g)).strip() or None


_LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _ld_items(data: object) -> list[dict]:
    """Every object inside a page's structured data, including lists and @graph."""
    if isinstance(data, list):
        return [x for d in data for x in _ld_items(d)]
    if isinstance(data, dict):
        return [data] + _ld_items(data.get("@graph") or [])
    return []


def place_from_page(page: str | None) -> str | None:
    """
    Where a job page says the job is (its published jobLocation): "Joliet, IL" for a US place, "Leeds, United Kingdom" elsewhere, up to three
    places joined with "; ". None when the page names no town or state.
    """
    out: list[str] = []
    for block in _LD_JSON.findall(page or ""):
        try:
            data = json.loads(html_lib.unescape(block).strip())
        except (ValueError, TypeError):
            continue
        for item in _ld_items(data):
            kind = item.get("@type")
            if "JobPosting" not in (kind if isinstance(kind, list) else [kind]):
                continue
            locs = item.get("jobLocation")
            for loc in locs if isinstance(locs, list) else [locs]:
                addr = loc.get("address") if isinstance(loc, dict) else None
                if not isinstance(addr, dict):
                    continue
                city = str(addr.get("addressLocality") or "").strip()
                region = str(addr.get("addressRegion") or "").strip()
                country = addr.get("addressCountry")
                country = str((country.get("name") if isinstance(country, dict) else country) or "").strip()
                if not (city or region):
                    continue
                if region.lower() in STATE_BY_NAME:
                    region = STATE_BY_NAME[region.lower()]
                if is_us_country(country) or (not country and region.upper() in US_STATES):
                    place = ", ".join(x for x in (city, region.upper() if len(region) == 2 else region) if x)
                else:
                    place = ", ".join(x for x in (city, region if not city else "", country) if x)
                if place and place not in out:
                    out.append(place)
    return "; ".join(out[:3]) or None


def is_us_country(country: str | None) -> bool:
    return (country or "").strip().lower() in _US_COUNTRY


def lead_with_place(location: str | None, wanted: list[str]) -> str | None:
    """A list of places with the ones the search asked for first, so shortening it to three ("A; B; C +4 more") never hides the place searched."""
    if not location or ";" not in location or not wanted:
        return location
    parts = [p.strip() for p in location.split(";") if p.strip()]
    hit = lambda part: any(f" {w} " in f" {fold(part)} " for w in wanted)
    return "; ".join(sorted(parts, key=lambda p: 0 if hit(p) else 1))


_CITY_DASH_STATE = re.compile(r"^([A-Za-z][A-Za-z .'\u2019]+)-([A-Z]{2})$")


_COUNTRY_TAIL = re.compile(r",?\s*\b(?:USA|U\.S\.A\.|United States(?: of America)?)\s*$", re.I)
_ZIP_TAIL = re.compile(r"\s+\d{5}(?:-\d{4})?\s*$")
_PREFIXED_STATE = re.compile(r"^(?:USA?|United States)\s*-\s*([A-Za-z][A-Za-z ]+?)\s*-\s*(.+)$", re.I)
_PREFIXED_CITY = re.compile(r"^(?:USA?|United States)\s*-\s*(.+)$", re.I)
_CITY_STATE_TAIL = re.compile(r"([A-Z][A-Za-z.' ]+),\s*([A-Z]{2})$")
_CITY_STATE_NAME = re.compile(r"^([A-Z][A-Za-z.' ]+),\s*([A-Za-z ]+)$")


def _clean_place_part(part: str) -> str:
    """One place written plainly: "USA-PA-Philadelphia" -> "Philadelphia, PA", "Denver, Colorado, USA" -> "Denver, CO", codes and zips dropped."""
    if re.match(r"^\s*remote\b", part, re.I):
        return part  # "Remote, USA" and "Remote (US or Canada)" say something the cleaning would remove
    out = re.sub(r"\s*\([^)]*\)", "", part).strip()  # "(1250 Broadway)", "(PAH01)"
    out = _COUNTRY_TAIL.sub("", out).strip()
    out = _ZIP_TAIL.sub("", out).strip()
    m = _PREFIXED_STATE.match(out)
    if m:  # "US - North Carolina - Charlotte", "USA-PA-Philadelphia"
        st = m.group(1).strip()
        abbr = st.upper() if len(st) == 2 and st.upper() in US_STATES else STATE_BY_NAME.get(st.lower())
        if abbr:
            return f"{m.group(2).strip()}, {abbr}"
    m = _PREFIXED_CITY.match(out)
    if m and _CITY_STATE_TAIL.search(m.group(1)):  # "US-New York, NY"
        out = m.group(1).strip()
    if out.count("-") >= 2:  # "Store 1168-South Park Mall-ANN-Charlotte, NC": the place is the end of it
        m = _CITY_STATE_TAIL.search(out.rsplit("-", 1)[-1].strip())
        if m:
            return f"{m.group(1).strip()}, {m.group(2)}"
    m = _CITY_STATE_NAME.match(out)
    if m and STATE_BY_NAME.get(m.group(2).strip().lower()):  # "Denver, Colorado" -> "Denver, CO"
        return f"{m.group(1).strip()}, {STATE_BY_NAME[m.group(2).strip().lower()]}"
    return out or part


def tidy_place(location: str | None) -> str | None:
    """A place written the usual way: "Newton-MA" -> "Newton, MA", "Austin,TX" -> "Austin, TX", a list of ten cities -> three and "+7 more"."""
    if not location:
        return location
    location = decode_text(location)
    piped = re.match(r"^(?:US|USA|United States)\s*\|\s*([A-Za-z .]+?)\s*\|\s*([A-Za-z .'-]+)$", location.strip())
    if piped and STATE_BY_NAME.get(piped.group(1).lower()):  # "US | Illinois | Chicago" -> "Chicago, IL"
        return f"{piped.group(2).strip()}, {STATE_BY_NAME[piped.group(1).lower()]}"
    remote_list = re.match(r"^remote\s*[(\-:]\s*([^()]+?)\s*\)?$", location.strip(), re.I)
    if remote_list and "|" in remote_list.group(1):  # "Remote (United States | Canada)" -> "Remote (US or Canada)"
        names = [re.sub(r"^(united states|usa|us)$", "US", p.strip(), flags=re.I) for p in remote_list.group(1).split("|") if p.strip()]
        if names:
            return "Remote (" + " or ".join(names) + ")"
    parts = []
    for part in re.split(r"\s*;\s*", location.strip()):
        part = _clean_place_part(part)
        m = _CITY_DASH_STATE.match(part)
        part = f"{m.group(1).strip()}, {m.group(2)}" if m else part
        parts.append(re.sub(r",(?=\S)", ", ", part))
    if len(parts) > 3:
        return "; ".join(parts[:3]) + f" +{len(parts) - 3} more"
    return "; ".join(parts)


_REQ_CODE = re.compile(r"\s*(?:[(\[]\s*[A-Za-z]{0,6}[- ]?\d{2,8}\s*[)\]]|[-\u2013|]\s*(?:req|job|id)?\s*#?[A-Za-z]{0,5}-?\d{3,}|#\s*\d{3,})\s*$", re.I)


def title_without_code(title: str | None) -> str:
    """A title without a trailing requisition code ("Product Marketing Manager (SMM194)" -> "Product Marketing Manager")."""
    out = decode_text(title)
    return _REQ_CODE.sub("", out).strip() or out


def clean_title(title: str | None, company: str | None = None) -> str:
    """A job title without a trailing "at <Employer>" ("Program Manager at Massgeneralbrigham" -> "Program Manager")."""
    out = decode_text(title)
    if not company:
        return out
    squashed = {_squash(company), _squash(clean_company(company))} - {""}
    m = re.search(r"\s+(?:at|@|-|\|)\s+([^@|]+)$", out)
    if m and _squash(m.group(1)) in squashed:
        shorter = out[: m.start()].strip()
        return shorter or out
    return out


_VIRTUAL = re.compile(r"\b(virtual(?:ly)?|remote|work(?:ing)? from home|telecommute|home[- ]based)\b", re.I)
_NO_PLACE = re.compile(r"^\s*(location not (?:listed|stated|specified)|not (?:listed|stated|specified)|n/?a|none|unknown)\s*$", re.I)


def reconcile_place(location: str | None, work_type: str | None) -> tuple[str | None, str | None]:
    """
    A place and work type that do not contradict each other. A place that says it is virtual or remote means remote, whatever else is
    claimed ("USA-NC-Virtual" + "hybrid" -> "Remote (NC)", remote). No usable place plus remote reads just "Remote".
    """
    loc = (location or "").strip()
    if _NO_PLACE.match(loc):
        loc = ""
    if loc and _VIRTUAL.search(loc) and "hybrid" not in loc.lower() and not re.match(r"^\s*remote\b", loc, re.I):
        tidy = tidy_place(_VIRTUAL.sub("", loc).strip(" -,;|/") or "") or ""
        m = re.search(r"\b([A-Z]{2})\b\s*$", tidy) or re.search(r"\b([A-Z]{2})\b", tidy)
        state = m.group(1) if m and m.group(1) in US_STATES else None
        return (f"Remote ({state})" if state else "Remote"), "remote"
    if not loc:
        return (("Remote" if work_type == "remote" else None), work_type)
    return loc, work_type


_REMOTE_US = re.compile(r"^\s*remote\s*[:\-]\s*(?:united states(?: of america)?|usa|us)\s*$", re.I)
_CODE_DASH = re.compile(r"^[A-Z]{2,5}\s*-\s*(?=[A-Z][a-z])")  # an office code before the city: "BRG-Chicago IL"
_STATE_DASH_CITY = re.compile(r"^([A-Z]{2})\s*-\s*([A-Z][A-Za-z. ]+)$")  # "NJ-Jersey City"
_CITY_SPACE_STATE = re.compile(r"^([A-Z][A-Za-z.' ]+?)\s+([A-Z]{2})$")  # "Boston MA"
_USA_STATE_CITY = re.compile(r"\bUSA?\s*-\s*([A-Z]{2})\s*-\s*([A-Z][A-Za-z. ]+?)(?:\s*-|\s*$)")  # "Client Site - USA - NY - New York - 11 Madison Avenue"


def _plain_place(part: str) -> str:
    part = part.strip()
    m = _USA_STATE_CITY.search(part)
    if m and m.group(1) in US_STATES:
        return f"{m.group(2).strip()}, {m.group(1)}"
    m = _STATE_DASH_CITY.match(part)
    if m and m.group(1) in US_STATES:
        return f"{m.group(2).strip()}, {m.group(1)}"
    part = _CODE_DASH.sub("", part)
    m = _CITY_SPACE_STATE.match(part)
    if m and m.group(2) in US_STATES:
        return f"{m.group(1).strip()}, {m.group(2)}"
    return part


def display_place(location: str | None, work_type: str | None) -> tuple[str | None, str | None]:
    """
    A place and work type as a person should read them: no codes or street addresses, "Remote: United States" and "Working Virtually"
    as plain remote, "Location not listed" as nothing, and a list of places as the first one and "+N more". Used when a result is shown;
    the ranking works from the original text.
    """
    if not location:
        return location, work_type
    if _REMOTE_US.match(location):
        return "Remote (US)", "remote"
    place, work_type = reconcile_place(location, work_type)
    if not place:
        return place, work_type
    parts = [p for p in re.split(r"\s*;\s*", place.strip()) if p]
    shown: list[str] = []
    for part in parts:
        plain = _plain_place(part)
        plain = tidy_place(part) if plain == part.strip() else plain
        shown.append(re.sub(r"\s+-\s+\d.*$", "", plain or part))  # "Chicago - 550 Van Buren" reads "Chicago"
    first = shown[0] if shown else place
    return (f"{first} +{len(shown) - 1} more" if len(shown) > 1 else first), work_type
