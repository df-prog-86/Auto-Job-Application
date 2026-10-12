"""
Suggestions while typing a job title or a keyword in Job Search. Titles come from the postings saved on this computer
(so every suggestion has openings behind it, most common first). Keywords are common skills, tools and credentials.
Nothing is sent anywhere; this is plain text matching.
"""

from __future__ import annotations

import re

from app.services.jobcache.text import fold

_KEYWORDS = """
Agile;Scrum;Kanban;Lean;Six Sigma;PMP;PMO;PMI;PMBOK;Prince2;SAFe;Waterfall;Jira;Confluence;Smartsheet;Asana;Microsoft Project;
Excel;PowerPoint;Power BI;Tableau;Looker;SQL;Python;R;SAS;Java;JavaScript;TypeScript;React;Node.js;C#;C++;Go;Ruby;Swift;Kotlin;
AWS;Azure;GCP;Docker;Kubernetes;Terraform;Linux;DevOps;CI/CD;Git;REST API;GraphQL;Machine learning;Data analysis;Data science;
Data engineering;ETL;Snowflake;Databricks;Spark;Salesforce;HubSpot;SAP;Oracle;Workday;NetSuite;ServiceNow;Epic;Cerner;EHR;EMR;
HIPAA;FDA;GCP clinical;GMP;GxP;Clinical research;Clinical trials;Regulatory affairs;Healthcare;Biotech;Pharma;Medical device;Public health;
Nonprofit;Higher education;Grant writing;Fundraising;SaaS;B2B;B2C;Fintech;Banking;Insurance;Compliance;Audit;SOX;GAAP;CPA;CFA;
Financial modeling;FP&A;Accounting;Budgeting;Forecasting;Procurement;Supply chain;Logistics;Operations;Process improvement;Change management;
Stakeholder management;Vendor management;Risk management;Business analysis;Product management;UX;UI;Figma;Marketing;SEO;Content;
Customer success;Sales;Account management;Recruiting;HR;Payroll;Training;Remote;Hybrid;Bilingual;Security clearance;CISSP;Cybersecurity
"""


def _keyword_pool() -> list[str]:
    return [k.strip() for k in _KEYWORDS.replace("\n", "").split(";") if k.strip()]


def keywords(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Skills and terms that start with what was typed ("pm" offers PMP, PMO, PMI, PMBOK), shorter first."""
    q = fold(query)
    if len(q) < 2:
        return []
    pool = _keyword_pool()
    starts = [k for k in pool if fold(k).startswith(q)]
    inside = [k for k in pool if k not in starts and any(w.startswith(q) for w in fold(k).split())]
    ordered = sorted(starts, key=len) + inside
    return [{"label": k} for k in ordered[:limit]]


def titles(query: str, rows: list[tuple[str, int]], limit: int = 8) -> list[dict[str, str]]:
    """Job titles that start with, or contain a word starting with, what was typed. `rows` is (title, how many postings)."""
    q = fold(query)
    if len(q) < 2:
        return []
    scored: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    for title, count in rows:
        clean = re.sub(r"\s+", " ", title or "").strip()
        f = fold(clean)
        # Skip titles with a code, a level number or a trailing detail; the plain role is the useful suggestion.
        if not clean or len(clean) > 60 or f in seen or re.search(r"\b(?:i{1,3}|iv|v|\d+)\b$", f) or re.search(r"[,(/\-]", clean):
            continue
        if f.startswith(q):
            rank = 0
        elif f" {q}" in f:
            rank = 1
        else:
            continue
        seen.add(f)
        scored.append((rank, -count, len(clean), clean))
    scored.sort()
    return [{"label": t} for _, _, _, t in scored[:limit]]
