"""
Pairs each saved role with its bullets from a Word resume (the tailored one for a
job, or the master when the original resume is used). Matching mirrors the
Profile page: the company, then the job title, appearing in the lines above a
bullet list; if nothing matches and the counts line up, document order. Anything
uncertain gets no bullets, never the wrong ones.
"""

from __future__ import annotations

from pathlib import Path

import docx

from app.services.resume.docx_editor import find_blocks


def resume_roles(path: str | Path) -> list[dict]:
    """[{context, bullets}] for each run of bullets in the file, in document order."""
    try:
        blocks = find_blocks(docx.Document(str(path)))
    except Exception:
        return []
    return [
        {"context": block.context, "bullets": [b.text.strip() for b in block.bullets if b.text.strip()]}
        for block in blocks
    ]


def match_bullets(roles: list[tuple[str, str]], blocks: list[dict]) -> list[list[str] | None]:
    """`roles` is [(employer, title)]. Returns bullets per role, or None when unsure."""
    used: set[int] = set()
    result: list[list[str] | None] = [None] * len(roles)

    def find(needle: str) -> int:
        n = (needle or "").strip().lower()
        if len(n) < 3:
            return -1
        for i, block in enumerate(blocks):
            if i not in used and n in block["context"].lower():
                return i
        return -1

    for i, (employer, title) in enumerate(roles):
        idx = find(employer)
        if idx == -1:
            idx = find(title)
        if idx != -1:
            used.add(idx)
            result[i] = blocks[idx]["bullets"]
    if not used and roles and len(roles) == len(blocks):
        return [b["bullets"] for b in blocks]
    return result
