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


# Employers whose name and job titles do not give it away (multinationals, mixed titles, other languages), settled by hand.
# Matched on the lower-case employer name, whole name or the start of it. A hand-set industry always wins.
_P = "Professional, Scientific, and Technical Services"
_M = "Manufacturing"
_R = "Retail Trade"
_W = "Wholesale Trade"
_I = "Information"
_F = "Finance and Insurance"
_H = "Health Care and Social Assistance"
_S = STAFFING
_OVERRIDES: dict[str, str] = {
    # added after the second large employer add
    'jll': 'Professional, Scientific, and Technical Services',
    'ngc': 'Professional, Scientific, and Technical Services',
    'gi': 'Professional, Scientific, and Technical Services',
    'walterpmoore': 'Professional, Scientific, and Technical Services',
    'cecinc': 'Professional, Scientific, and Technical Services',
    'structurepoint': 'Professional, Scientific, and Technical Services',
    'vhb': 'Professional, Scientific, and Technical Services',
    'carollo': 'Professional, Scientific, and Technical Services',
    'eps careers epsii': 'Professional, Scientific, and Technical Services',
    'challp': 'Professional, Scientific, and Technical Services',
    'atwell': 'Professional, Scientific, and Technical Services',
    'tatitlek': 'Professional, Scientific, and Technical Services',
    'internal tatitlek': 'Professional, Scientific, and Technical Services',
    'teksynap': 'Professional, Scientific, and Technical Services',
    'bylight': 'Professional, Scientific, and Technical Services',
    'nakupuna': 'Professional, Scientific, and Technical Services',
    'barbaricum': 'Professional, Scientific, and Technical Services',
    'caci': 'Professional, Scientific, and Technical Services',
    'parsons': 'Professional, Scientific, and Technical Services',
    'external dillon': 'Professional, Scientific, and Technical Services',
    'luster national': 'Professional, Scientific, and Technical Services',
    'b3h': 'Professional, Scientific, and Technical Services',
    'militaryjobs mci': 'Professional, Scientific, and Technical Services',
    'innodata': 'Professional, Scientific, and Technical Services',
    '3m': 'Manufacturing',
    'heinz': 'Manufacturing',
    'intel': 'Manufacturing',
    'bdx': 'Manufacturing',
    'vishay': 'Manufacturing',
    'arrow': 'Manufacturing',
    'baxter': 'Manufacturing',
    'claytonhomes': 'Manufacturing',
    'brunswick': 'Manufacturing',
    'barrywehmiller': 'Manufacturing',
    'genmills': 'Manufacturing',
    'broadcom': 'Manufacturing',
    'marvell': 'Manufacturing',
    'ingredion': 'Manufacturing',
    'novolex': 'Manufacturing',
    'novelis': 'Manufacturing',
    'elkay': 'Manufacturing',
    'aviagen': 'Manufacturing',
    'flextronics': 'Manufacturing',
    'masco': 'Manufacturing',
    'millerknoll': 'Manufacturing',
    'daikinapplied': 'Manufacturing',
    'globalcareers lennox': 'Manufacturing',
    'hrlydistribution lennox': 'Manufacturing',
    'snapon': 'Manufacturing',
    'daifuku america': 'Manufacturing',
    'steeldynamics': 'Manufacturing',
    'sazerac': 'Manufacturing',
    'gdifamilyofbrands': 'Manufacturing',
    'calistacorp': 'Manufacturing',
    'lg electronics': 'Manufacturing',
    'gotion': 'Manufacturing',
    'hyvee': 'Retail Trade',
    'bjswholesaleclub': 'Retail Trade',
    'belk': 'Retail Trade',
    'meijer': 'Retail Trade',
    'lowesfoods': 'Retail Trade',
    'winco': 'Retail Trade',
    'rochebros': 'Retail Trade',
    'mattressfirm': 'Retail Trade',
    'jdgroupnam': 'Retail Trade',
    'group1auto': 'Retail Trade',
    'kengarff': 'Retail Trade',
    'drivetime': 'Retail Trade',
    'sunauto': 'Retail Trade',
    'midtown': 'Retail Trade',
    'invesco': 'Finance and Insurance',
    'hubinternational': 'Finance and Insurance',
    'bbinsurance': 'Finance and Insurance',
    'internal libertymutual': 'Finance and Insurance',
    'americanredcross': 'Health Care and Social Assistance',
    'athletico': 'Health Care and Social Assistance',
    'lifestance': 'Health Care and Social Assistance',
    'internal usesalvationarmy': 'Health Care and Social Assistance',
    'usesalvationarmy': 'Health Care and Social Assistance',
    'mchapusa': 'Health Care and Social Assistance',
    'thinktogether': 'Health Care and Social Assistance',
    'miltoncat': 'Wholesale Trade',
    'quinngroup': 'Wholesale Trade',
    'ringpower': 'Wholesale Trade',
    'careers2 imagefirst': 'Wholesale Trade',
    'envoyair': 'Transportation and Warehousing',
    'us envoyair': 'Transportation and Warehousing',
    'technicians ryder': 'Transportation and Warehousing',
    'eversource': 'Utilities',
    'aes': 'Utilities',
    'casella': 'Utilities',
    'mpc': 'Utilities',
    'ncr': 'Information',
    'cableone': 'Information',
    'zipline': 'Information',
    'collectorsuniverse': 'Information',
    'cw': 'Administrative and Support and Waste Management and Remediation Services',
    'internalcareers aus': 'Administrative and Support and Waste Management and Remediation Services',
    'corporatecareers aus': 'Administrative and Support and Waste Management and Remediation Services',
    'startup aus': 'Administrative and Support and Waste Management and Remediation Services',
    'diversifiedm aus': 'Administrative and Support and Waste Management and Remediation Services',
    'propark': 'Administrative and Support and Waste Management and Remediation Services',
    'careersus teleperformance': 'Administrative and Support and Waste Management and Remediation Services',
    'thesydneycentre': 'Administrative and Support and Waste Management and Remediation Services',
    'cbps': 'Administrative and Support and Waste Management and Remediation Services',
    'tkcholdings': 'Accommodation and Food Services',
    'hub hochunk': 'Accommodation and Food Services',
    'comfortsystemsusa': 'Construction',
    'rrsc': 'Construction',
    'maine': 'Public Administration',
    'nascar': 'Arts, Entertainment, and Recreation',
    'hines': 'Real Estate and Rental and Leasing',
    'greystar': 'Real Estate and Rental and Leasing',
    'nationalalamo erac': 'Real Estate and Rental and Leasing',
    'mosaic': 'Mining, Quarrying, and Oil and Gas Extraction',
    # health care
    "centria autism": _H, "oos management": _H, "napaanesthesia": _H, "alpacahealth": _H, "allarahealth": _H, "artemed": _H,
    "ouihelp": _H, "joya": _H, "robert bosch krankenhaus": _H,
    # veterinary care is a professional service in NAICS (54)
    "veterinary emergency group": _P, "veterinary practice partners": _P, "lap of love": _P, "vetevolve": _P,
    # engineering, architecture, testing, consulting
    "aecom": _P, "eurofins": _P, "sgs": _P, "alten": _P, "assystem": _P, "afry": _P, "socotec": _P, "cima+": _P, "olsson": _P,
    "deloitte": _P, "labella": _P, "dlr group": _P, "woolpert": _P, "llnl": _P, "ergomed": _P, "eversana": _P,
    "transperfect": _P, "geeks on site": _P, "actionet": _P, "credence": _P, "sosi": _P, "sqli": _P,
    # manufacturing
    "bosch": _M, "renesas": _M, "wabtec": _M, "aumovio": _M, "continental": _M, "syngenta": _M, "avery dennison": _M,
    "lucid motors": _M, "kronospan": _M, "jbs": _M, "beumer": _M, "lesaffre": _M, "o-i": _M, "jacobs douwe egberts": _M, "bertelsmann-jobs": _I,
    "stäubli": _M,
    # retail and wholesale
    "h&m": _R, "a.t.u": _R, "reitmans": _R, "lush": _R, "redcare": _R, "kiabi": _R, "e. breuninger": _R, "conforama": _R,
    "groupement mousquetaires": _R, "metro/makro": _W, "baywa": _W, "rexel": _W,
    # other sectors
    "bertelsmann": _I, "ubisoft": _I, "zayo": _I, "informa": _I, "fluidstack": _I,
    "acrisure": _F, "coface": _F, "xp inc": _F, "tbcbank": _F,
    "veolia": "Utilities", "vattenfall": "Utilities", "expeditors": "Transportation and Warehousing",
    "sixt": "Real Estate and Rental and Leasing", "renuity": "Construction", "besix": "Construction",
    "securitas": _S, "walden security": _S, "rentokil": _S, "sutherland": _S, "wns global": _S,
    "junior adventures": "Educational Services", "evolution": "Arts, Entertainment, and Recreation",
    "bibibop": "Accommodation and Food Services", "accor": "Accommodation and Food Services", "accorhotel": "Accommodation and Food Services", "accorcorpo": "Accommodation and Food Services",
    "provalliance": "Other Services (except Public Administration)", "the wonderful company": "Agriculture, Forestry, Fishing and Hunting",
}

# Proper display names for employers whose saved name is just the web address slug (lower-case slug -> name).
DISPLAY_NAMES: dict[str, str] = {
    "jll": "JLL", "ngc": "Northrop Grumman", "hyvee": "Hy-Vee", "bjswholesaleclub": "BJ's Wholesale Club", "belk": "Belk",
    "meijer": "Meijer", "jdgroupnam": "JD Sports", "ecolab": "Ecolab", "heinz": "Kraft Heinz", "3m": "3M", "intel": "Intel",
    "cox": "Cox Enterprises", "bdx": "BD", "vishay": "Vishay", "hubinternational": "HUB International", "arrow": "Arrow Electronics",
    "baxter": "Baxter", "claytonhomes": "Clayton Homes", "brunswick": "Brunswick", "barrywehmiller": "Barry-Wehmiller",
    "genmills": "General Mills", "broadcom": "Broadcom", "americanredcross": "American Red Cross", "marvell": "Marvell",
    "bbinsurance": "Brown & Brown", "envoyair": "Envoy Air", "daikinapplied": "Daikin Applied", "ingredion": "Ingredion",
    "invesco": "Invesco", "eversource": "Eversource", "collectorsuniverse": "Collectors Universe", "mattressfirm": "Mattress Firm",
    "millerknoll": "MillerKnoll", "ncr": "NCR", "comfortsystemsusa": "Comfort Systems USA", "kengarff": "Ken Garff",
    "drivetime": "DriveTime", "elkay": "Elkay", "aviagen": "Aviagen", "aaamidatlantic": "AAA Mid-Atlantic", "mpc": "Marathon Petroleum",
    "flextronics": "Flex", "nascar": "NASCAR", "lifestance": "LifeStance Health", "cableone": "Cable One", "aes": "AES",
    "masco": "Masco", "lowesfoods": "Lowes Foods", "usesalvationarmy": "The Salvation Army", "internal usesalvationarmy": "The Salvation Army",
    "group1auto": "Group 1 Automotive", "athletico": "Athletico Physical Therapy", "winco": "WinCo Foods", "novolex": "Novolex",
    "novelis": "Novelis", "casella": "Casella Waste Systems", "propark": "Propark", "snapon": "Snap-on",
    "internal libertymutual": "Liberty Mutual", "globalcareers pepsico": "PepsiCo", "uscareers pepsico": "PepsiCo",
    "technicians ryder": "Ryder", "careersus teleperformance": "Teleperformance", "hines": "Hines", "vhb": "VHB",
    "cvshealth": "CVS Health", "lowes": "Lowe's", "michaels": "Michaels", "dickssportinggoods": "Dick's Sporting Goods",
    "fivebelow": "Five Below", "davita": "DaVita", "ccf": "Cleveland Clinic", "pnc": "PNC", "nvidia": "NVIDIA", "labcorp": "Labcorp",
    "highmarkhealth": "Highmark Health", "ochsner": "Ochsner Health", "caci": "CACI", "td": "TD Bank", "ms": "Morgan Stanley",
    "carmax": "CarMax", "att": "AT&T", "amat": "Applied Materials", "dxctechnology": "DXC Technology", "osu": "Ohio State University",
    "basspro": "Bass Pro Shops", "greystar": "Greystar", "bhs": "Baptist Health South Florida", "lvhn": "Lehigh Valley Health Network",
    "republic": "Republic Services", "genpt": "Genuine Parts Company", "aah": "Advocate Health", "communicarehealth": "CommuniCare Health Services",
    "knitwellgroup": "Knitwell Group", "ghr": "Guardian Health Resources", "calibercollision": "Caliber Collision",
    "daveandbusters": "Dave & Buster's", "firststudent": "FirstStudent", "parsons": "Parsons",
}


def _override(name: str) -> str | None:
    n = (name or "").strip().lower()
    for key, sector in _OVERRIDES.items():
        if n == key or n.startswith(key + " ") or n.startswith(key + "-") or n.startswith(key + "/"):
            return sector
    return None


def classify(name: str, titles: Iterable[str]) -> str:
    """The industry of one employer, from its name and its open posting titles."""
    fixed = _override(name)
    if fixed:
        return fixed
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
    slug_of = {r["id"]: (r["name"] or "").strip().lower() for r in db.execute("SELECT id, name FROM employers")}
    if todo:
        titles: dict[int, list[str]] = {}
        for r in db.execute("SELECT employer_id, title FROM postings WHERE closed_at IS NULL"):
            titles.setdefault(r["employer_id"], []).append(r["title"])
        db.executemany(
            "UPDATE employers SET industry = ? WHERE id = ?",
            [(classify(name, titles.get(eid, [])), eid) for eid, name in todo],
        )
    for eid, slug in slug_of.items():  # replace address-style names with proper ones, after classifying by the original
        proper = DISPLAY_NAMES.get(slug)
        if proper:
            db.execute("UPDATE employers SET name = ? WHERE id = ? AND name <> ?", (proper, eid, proper))
    out: dict[str, tuple[int, int]] = {}
    for r in db.execute(
        "SELECT COALESCE(NULLIF(industry, ''), ?) AS ind, COUNT(*) AS n, COALESCE(SUM(open_count), 0) AS jobs FROM employers GROUP BY ind",
        (OTHER,),
    ):
        out[r["ind"]] = (r["n"], r["jobs"])
    return out
