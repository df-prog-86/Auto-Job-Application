"""
Is a posting from a staffing or recruiting agency rather than the employer itself? A label only: it is saved beside the posting and
never removes, hides or reorders anything, and the Chrome extension never reads it. A wrong label changes nothing about searching
or applying. True when there is evidence (a name or wording agencies use), otherwise None, which means "not decided", not "direct".
"""

from __future__ import annotations

import re

from app.services.jobcache.text import fold

_NAME_WORDS = re.compile(
    r"\b(staffing|recruiting|recruitment|recruiters?|talent (?:solutions|acquisition partners|partners)|search (?:group|partners|firm)|"
    r"executive search|workforce solutions|placement|headhunt\w*)\b"
)
_KNOWN = {
    "robert half", "randstad", "kforce", "adecco", "manpowergroup", "manpower", "insight global", "teksystems", "aerotek", "kelly services",
    "hays", "apex systems", "cross country healthcare", "amn healthcare", "aya healthcare", "jobot", "cybercoders", "tek systems",
    "volt information sciences", "allegis group", "judge group", "belcan", "actalent", "collabera", "ettain group", "beacon hill staffing",
    "vaco", "motion recruitment", "mastech", "ciber", "creative circle", "the judge group", "medical solutions", "trustaff", "fastaff",
}
_TEXT = re.compile(
    r"\b(on behalf of (?:our|a) client|our client(?: is| has| a| an|,)|we are (?:a )?(?:staffing|recruiting)|staffing (?:agency|firm)|"
    r"recruiting (?:agency|firm)|corp[- ]to[- ]corp|c2c\b|w-?2 (?:contract|only)|contract[- ]to[- ]hire)",
    re.I,
)


def is_agency(company: str | None, description: str | None = None) -> bool | None:
    name = fold(company)
    if name and (name in _KNOWN or any(name.startswith(k + " ") for k in _KNOWN) or _NAME_WORDS.search(name)):
        return True
    if description and _TEXT.search(description[:4000]):
        return True
    return None
