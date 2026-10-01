"""Output file naming: `First Last_Resume_<Company>_YYYY.pdf`, spaces kept."""

from __future__ import annotations

import datetime as dt
import re

_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def resume_filename(candidate_name: str, company: str, fmt: str, year: int | None = None) -> str:
    year = year or dt.date.today().year
    name = _UNSAFE.sub("", candidate_name).strip() or "Candidate"
    firm = _UNSAFE.sub("", company).strip() or "Company"
    return f"{name}_Resume_{firm}_{year}.{fmt}"
