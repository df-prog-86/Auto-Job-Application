"""
Works out which industry each saved employer is in, using plain code (no AI, no network).

The employer's name and the titles of its open postings both vote. A hospital has nurses, therapists and patient access
roles; a bank has loan officers and underwriters; a software company has engineers and designers. The industry with the
strongest signal wins, and an employer with no clear signal is "Other or mixed", never guessed.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

OTHER = "Other or mixed"
STAFFING = "Staffing and recruiting"

# (industry, name words, title words). All matched as whole words or word starts, lower case.
_RULES: list[tuple[str, list[str], list[str]]] = [
    (
        "Healthcare",
        ["hospital", "hospitals", "health system", "healthcare", "medical center", "clinic", "clinics", "health", "medical",
         "physicians", "pediatric", "oncology", "dental", "hospice", "behavioral"],
        ["nurse", "rn", "lpn", "cna", "clinical", "patient", "physician", "therapist", "pharmacist", "pharmacy", "medical assistant",
         "surgeon", "radiology", "radiologic", "phlebotomist", "hospice", "dental", "behavioral health", "care coordinator",
         "revenue cycle", "denials", "medical coding", "prior authorization", "patient access", "clinician", "caregiver",
         "sonographer", "paramedic", "psychiatrist", "psychologist", "counselor"],
    ),
    (
        "Technology",
        ["software", "technologies", "technology", "labs", "cloud", "digital", "cyber", "robotics"],
        ["software", "developer", "devops", "sre", "machine learning", "data scientist", "data engineer", "backend", "frontend",
         "front end", "back end", "full stack", "platform engineer", "solutions engineer", "security engineer", "product designer",
         "product manager", "qa engineer", "engineering manager", "site reliability", "ml engineer", "infrastructure engineer"],
    ),
    (
        "Finance and insurance",
        ["bank", "bancorp", "financial", "capital", "insurance", "assurance", "credit union", "mortgage", "wealth", "investments",
         "asset management", "advisors", "payments", "lending"],
        ["accountant", "accounting", "financial analyst", "auditor", "underwriter", "actuary", "actuarial", "loan", "mortgage",
         "banker", "wealth", "portfolio", "treasury", "tax", "controller", "fp&a", "investment", "claims adjuster", "branch manager",
         "teller", "credit analyst", "risk analyst", "compliance analyst"],
    ),
    (
        "Consulting and professional services",
        ["consulting", "consultants", "advisory", "law", "llp"],
        ["consultant", "consulting", "advisory", "attorney", "paralegal", "counsel", "engagement manager", "management consultant",
         "strategy", "associate director", "senior associate"],
    ),
    (
        "Education",
        ["university", "college", "school", "schools", "academy", "institute", "education", "learning"],
        ["professor", "teacher", "faculty", "lecturer", "academic", "curriculum", "instructor", "admissions", "campus", "tutor",
         "student", "registrar", "dean"],
    ),
    (
        "Government and nonprofit",
        ["city of", "county", "state of", "department of", "foundation", "nonprofit", "association", "ymca", "united way", "council"],
        ["program officer", "grants", "policy analyst", "public policy", "outreach", "caseworker", "advocacy", "fundraising",
         "development officer", "community"],
    ),
    (
        "Retail and consumer",
        ["stores", "retail", "foods", "brands", "apparel", "restaurants", "beverage", "grocery", "outfitters"],
        ["store manager", "cashier", "merchandiser", "merchandising", "retail", "barista", "sales associate", "stylist", "buyer",
         "shift leader", "crew member", "ecommerce", "e-commerce"],
    ),
    (
        "Manufacturing and industrial",
        ["manufacturing", "industries", "industrial", "materials", "chemical", "steel", "aerospace", "automotive", "devices"],
        ["machinist", "manufacturing", "assembler", "production operator", "quality technician", "welder", "maintenance technician",
         "plant", "process engineer", "mechanical engineer", "manufacturing engineer", "tooling", "cnc"],
    ),
    (
        "Transportation and logistics",
        ["logistics", "freight", "transport", "shipping", "airlines", "railroad", "trucking", "delivery"],
        ["driver", "logistics", "warehouse", "dispatcher", "supply chain", "freight", "fleet", "forklift", "carrier", "courier",
         "pilot", "flight attendant"],
    ),
    (
        "Energy and utilities",
        ["energy", "electric", "utility", "utilities", "solar", "oil", "petroleum", "renewables"],
        ["lineworker", "lineman", "utility", "solar", "power plant", "renewable", "grid", "pipeline", "drilling", "substation",
         "energy"],
    ),
    (
        "Media and entertainment",
        ["media", "entertainment", "studios", "games", "publishing", "broadcasting", "pictures"],
        ["editor", "producer", "journalist", "reporter", "broadcast", "animator", "game designer", "copywriter", "content creator",
         "videographer", "art director"],
    ),
    (
        "Real estate and construction",
        ["realty", "real estate", "properties", "construction", "builders", "homes", "architects"],
        ["property manager", "leasing", "construction", "estimator", "superintendent", "architect", "real estate", "broker",
         "project engineer", "site manager", "carpenter", "electrician"],
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
