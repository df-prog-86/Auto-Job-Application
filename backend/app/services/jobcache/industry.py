"""
Works out which industry each saved employer is in, using plain code (no AI, no network).

The employer's name and the titles of its open postings both vote. A hospital has nurses, therapists and patient access
roles; a bank has loan officers and underwriters; a software company has engineers and designers. The sector with the
strongest signal wins, and an employer with no clear signal is "Unclassified", never guessed. Sectors are the official
NAICS sector titles used by the US government.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

OTHER = "Unclassified"
STAFFING = "Administrative and Support and Waste Management and Remediation Services"  # NAICS 56, where staffing agencies sit

# The 2022 North American Industry Classification System (NAICS) sectors, which the US government (Census Bureau, Bureau of
# Labor Statistics) uses to describe employers. Names are the official sector titles. Sector 55 (holding companies) cannot be
# told from a name or job titles, so it is not assigned.
NAICS_CODES = {
    "Agriculture, Forestry, Fishing and Hunting": "11",
    "Mining, Quarrying, and Oil and Gas Extraction": "21",
    "Utilities": "22",
    "Construction": "23",
    "Manufacturing": "31-33",
    "Wholesale Trade": "42",
    "Retail Trade": "44-45",
    "Transportation and Warehousing": "48-49",
    "Information": "51",
    "Finance and Insurance": "52",
    "Real Estate and Rental and Leasing": "53",
    "Professional, Scientific, and Technical Services": "54",
    STAFFING: "56",
    "Educational Services": "61",
    "Health Care and Social Assistance": "62",
    "Arts, Entertainment, and Recreation": "71",
    "Accommodation and Food Services": "72",
    "Other Services (except Public Administration)": "81",
    "Public Administration": "92",
}

# (NAICS sector, name words, title words). All matched as whole words, lower case.
_RULES: list[tuple[str, list[str], list[str]]] = [
    (
        "Health Care and Social Assistance",
        ["hospital", "hospitals", "health system", "healthcare", "medical center", "clinic", "clinics", "health", "medical",
         "physicians", "pediatric", "oncology", "dental", "hospice", "behavioral", "senior living", "home care", "family services"],
        ["nurse", "rn", "lpn", "cna", "clinical", "patient", "physician", "therapist", "pharmacist", "pharmacy", "medical assistant",
         "surgeon", "radiology", "radiologic", "phlebotomist", "hospice", "dental", "behavioral health", "care coordinator",
         "revenue cycle", "denials", "medical coding", "prior authorization", "patient access", "clinician", "caregiver",
         "sonographer", "paramedic", "psychiatrist", "psychologist", "counselor", "social worker", "case manager",
         "behavior technician", "registered behavior technician", "rbt", "bcba", "aba", "veterinarian", "veterinary", "vet tech",
         "school psychologist", "speech language pathologist", "occupational therapist", "physical therapist", "dentist",
         "hygienist", "optometrist", "medical receptionist", "patient service representative", "billing specialist", "coder"],
    ),
    (
        "Information",  # software publishers, internet and data companies, telecommunications, publishing, film and broadcasting
        ["software", "technologies", "technology", "labs", "cloud", "digital", "cyber", "robotics", "telecom", "wireless", "internet",
         "media", "studios", "games", "publishing", "broadcasting", "pictures", "network", "networks"],
        ["software", "developer", "devops", "sre", "machine learning", "data scientist", "data engineer", "backend", "frontend",
         "front end", "back end", "full stack", "platform engineer", "solutions engineer", "security engineer", "product designer",
         "product manager", "qa engineer", "engineering manager", "site reliability", "ml engineer", "infrastructure engineer",
         "editor", "producer", "journalist", "reporter", "broadcast", "animator", "game designer", "copywriter", "content creator",
         "videographer"],
    ),
    (
        "Finance and Insurance",
        ["bank", "bancorp", "financial", "capital", "insurance", "assurance", "credit union", "mortgage", "wealth", "investments",
         "asset management", "advisors", "payments", "lending"],
        ["accountant", "accounting", "financial analyst", "auditor", "underwriter", "actuary", "actuarial", "loan", "mortgage",
         "banker", "wealth", "portfolio", "treasury", "tax", "controller", "fp&a", "investment", "claims adjuster", "branch manager",
         "teller", "credit analyst", "risk analyst", "compliance analyst"],
    ),
    (
        "Professional, Scientific, and Technical Services",  # consulting, legal, accounting firms, engineering, design, research
        ["consulting", "consultants", "advisory", "law", "llp", "laboratories", "research", "architects", "engineering"],
        ["consultant", "consulting", "advisory", "attorney", "paralegal", "counsel", "engagement manager", "management consultant",
         "strategy", "associate director", "senior associate", "research scientist", "scientist", "architect", "biostatistician"],
    ),
    (
        "Educational Services",
        ["university", "college", "school", "schools", "academy", "institute", "education", "learning"],
        ["professor", "teacher", "faculty", "lecturer", "academic", "curriculum", "instructor", "admissions", "campus", "tutor",
         "student", "registrar", "dean"],
    ),
    (
        "Public Administration",  # federal, state and local government
        ["city of", "county", "state of", "department of", "town of", "commonwealth of"],
        ["policy analyst", "public policy", "public works", "police", "firefighter", "municipal"],
    ),
    (
        "Other Services (except Public Administration)",  # nonprofits, grantmaking, civic and advocacy groups, religious organizations
        ["foundation", "nonprofit", "association", "ymca", "united way", "council", "ministries", "church"],
        ["program officer", "grants", "outreach", "advocacy", "fundraising", "development officer", "community"],
    ),
    (
        "Retail Trade",
        ["stores", "retail", "brands", "apparel", "grocery", "outfitters"],
        ["store manager", "cashier", "merchandiser", "merchandising", "retail", "sales associate", "stylist", "buyer", "ecommerce",
         "e-commerce"],
    ),
    (
        "Accommodation and Food Services",
        ["restaurants", "restaurant", "hotel", "hotels", "resort", "resorts", "hospitality", "cafe", "foods", "beverage"],
        ["line cook", "chef", "server", "bartender", "barista", "housekeeper", "front desk", "concierge", "crew member", "shift leader",
         "dishwasher", "host"],
    ),
    (
        "Manufacturing",
        ["manufacturing", "industries", "industrial", "materials", "chemical", "steel", "aerospace", "automotive", "devices",
         "pharmaceuticals", "biosciences"],
        ["machinist", "manufacturing", "assembler", "production operator", "quality technician", "welder", "maintenance technician",
         "plant", "process engineer", "mechanical engineer", "manufacturing engineer", "tooling", "cnc"],
    ),
    (
        "Transportation and Warehousing",
        ["logistics", "freight", "transport", "shipping", "airlines", "railroad", "trucking", "delivery", "warehouse"],
        ["driver", "logistics", "warehouse", "dispatcher", "supply chain", "freight", "fleet", "forklift", "carrier", "courier",
         "pilot", "flight attendant"],
    ),
    (
        "Utilities",  # electric power, natural gas, water, and renewable generation
        ["electric", "utility", "utilities", "solar", "renewables", "water", "power"],
        ["lineworker", "lineman", "utility", "solar", "power plant", "renewable", "grid", "substation", "energy"],
    ),
    (
        "Mining, Quarrying, and Oil and Gas Extraction",
        ["oil", "petroleum", "mining", "drilling", "gas exploration"],
        ["drilling", "geologist", "mining", "wellsite", "petroleum", "reservoir"],
    ),
    (
        "Arts, Entertainment, and Recreation",
        ["entertainment", "museum", "casino", "theatre", "theater", "fitness", "golf", "sports", "recreation"],
        ["fitness instructor", "personal trainer", "curator", "athletic", "lifeguard", "box office", "gallery"],
    ),
    (
        "Real Estate and Rental and Leasing",
        ["realty", "real estate", "properties", "rentals", "leasing"],
        ["property manager", "leasing", "real estate", "broker", "leasing consultant", "tenant"],
    ),
    (
        "Construction",
        ["construction", "builders", "homes", "contractors"],
        ["construction", "estimator", "superintendent", "carpenter", "electrician", "project engineer", "site manager", "foreman"],
    ),
    (
        "Wholesale Trade",
        ["wholesale", "distribution", "distributors", "supply"],
        ["inside sales representative", "purchasing agent"],
    ),
    (
        "Agriculture, Forestry, Fishing and Hunting",
        ["farms", "farm", "agricultural", "agriculture", "forestry", "growers"],
        ["farmhand", "agronomist", "grower", "farm manager", "forester"],
    ),
]

_STAFFING_NAME = re.compile(r"\b(staffing|recruit\w*|talent solutions|workforce|search group|placement)\b", re.I)


def _compile(words: Iterable[str]) -> re.Pattern[str]:
    # Whole words, but a word may carry an ending ("nurses", "accountants").
    parts = sorted({re.escape(w) for w in words}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")(?:s|es)?\b", re.I)


_NAME = {name: _compile(n) for name, n, _ in _RULES}
_TITLE = {name: _compile(t) for name, _, t in _RULES}

NAME_WEIGHT = 0.35  # a name that says "Hospital" counts as much as a third of the titles agreeing
MIN_SCORE = 0.15


def classify(name: str, titles: Iterable[str]) -> str:
    """The industry of one employer, from its name and its open posting titles."""
    if _STAFFING_NAME.search(name or ""):
        return STAFFING
    titles = [t for t in titles if t]
    scores: Counter[str] = Counter()
    for industry in _TITLE:
        if titles:
            hits = sum(1 for t in titles if _TITLE[industry].search(t))
            scores[industry] += hits / len(titles)
        if _NAME[industry].search(name or ""):
            scores[industry] += NAME_WEIGHT
    if not scores:
        return OTHER
    best, score = scores.most_common(1)[0]
    return best if score >= MIN_SCORE else OTHER


def tag_employers(db: Any, retag: bool = False) -> dict[str, tuple[int, int]]:
    """
    Fills in the industry of every employer that has none (or all of them with retag). Returns {industry: (employers, open jobs)}
    for the whole saved list afterwards. `db` is an open connection with row access by name.
    """
    where = "" if retag else "WHERE industry IS NULL OR industry = ''"
    todo = [(r["id"], r["name"]) for r in db.execute(f"SELECT id, name FROM employers {where}")]
    if todo:
        titles: dict[int, list[str]] = {}
        for r in db.execute("SELECT employer_id, title FROM postings WHERE closed_at IS NULL"):
            titles.setdefault(r["employer_id"], []).append(r["title"])
        db.executemany(
            "UPDATE employers SET industry = ? WHERE id = ?",
            [(classify(name, titles.get(eid, [])), eid) for eid, name in todo],
        )
    out: dict[str, tuple[int, int]] = {}
    for r in db.execute(
        "SELECT COALESCE(NULLIF(industry, ''), ?) AS ind, COUNT(*) AS n, COALESCE(SUM(open_count), 0) AS jobs FROM employers GROUP BY ind",
        (OTHER,),
    ):
        out[r["ind"]] = (r["n"], r["jobs"])
    return out
