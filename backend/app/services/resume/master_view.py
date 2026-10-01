"""
Read-only view of the saved master resume's bullets, grouped per role, so the
Profile page can show them under each job. Nothing here ever writes to the
master file.
"""

from __future__ import annotations

import docx

from app.services.resume.docx_editor import find_blocks
from app.services.resume.master import master_path


def master_roles() -> list[dict]:
    path = master_path()
    if path is None:
        return []
    try:
        document = docx.Document(str(path))
        blocks = find_blocks(document)
    except Exception:
        return []
    return [
        {"context": block.context, "bullets": [b.text.strip() for b in block.bullets if b.text.strip()]}
        for block in blocks
    ]
