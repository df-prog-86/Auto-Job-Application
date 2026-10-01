"""
Milestone 5 for one job: copy the master Word resume, reorder/lightly reword
its bullets per a validated plan, clean dashes and trailing blank paragraphs,
save as Word, and record the file plus a changelog. The master file itself is never written to.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from sqlalchemy.orm import Session

from app.config import settings
from app.models.documents import GeneratedDocument
from app.models.jobs import Job
from app.services.resume import docx_editor
from app.services.resume.generation import generate_plan
from app.services.resume.master import master_path
from app.services.resume.naming import resume_filename
from app.services.resume.validation import plan_to_dict

TEMPLATE_VERSION = "docx-inplace-1"


class MasterMissingError(RuntimeError):
    """No master Word resume has been saved yet."""


@dataclass
class TailorOutcome:
    documents: list[GeneratedDocument]
    used_original_wording: bool
    problems: list[str]
    changelog: list[str]


def _documents_dir() -> Path:
    return Path(settings.GENERATED_DOCUMENTS_DIR).resolve()


def _remove_existing(db: Session, job: Job) -> None:
    for doc in db.query(GeneratedDocument).filter(
        GeneratedDocument.job_id == job.id, GeneratedDocument.document_type.in_(("resume", "changelog"))
    ):
        try:
            Path(doc.local_path).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(doc)
    db.flush()


async def tailor_resume(db: Session, job: Job, candidate_name: str) -> TailorOutcome:
    master = master_path()
    if master is None:
        raise MasterMissingError(
            "No master Word resume is saved yet. Upload your resume as a Word (.docx) file on the Profile page."
        )

    doc = Document(str(master))  # read-only use of the master; saved elsewhere below
    blocks = docx_editor.find_blocks(doc)
    result = await generate_plan(db, job, blocks, docx_editor.full_text(doc))
    if result.plan is not None:
        docx_editor.apply_plan(blocks, plan_to_dict(result.plan))
    docx_editor.clean_dashes(doc)
    docx_editor.strip_trailing_blank_paragraphs(doc)

    out_dir = _documents_dir() / f"job_{job.id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / resume_filename(candidate_name, job.company, "docx")

    _remove_existing(db, job)
    doc.save(str(docx_path))
    changelog = list(result.changelog)

    changelog_path = out_dir / f"Tailoring changelog_{job.company}.txt".replace("/", "")
    changelog_path.write_text(
        f"Tailoring changelog: {job.title}, {job.company}\n\n"
        + ("\n".join(f"- {n}" for n in changelog) or "- No notes.")
        + "\n",
        encoding="utf-8",
    )

    now = dt.datetime.now(dt.timezone.utc)
    files = [("docx", docx_path, "resume"), ("txt", changelog_path, "changelog")]
    docs = [
        GeneratedDocument(
            job_id=job.id,
            document_type=kind,
            local_path=str(path),
            format=fmt,
            generated_at=now,
            template_version=TEMPLATE_VERSION,
            source_claim_ids=[],
            content_hash=_sha256(path),
        )
        for fmt, path, kind in files
    ]
    db.add_all(docs)
    db.commit()
    for d in docs:
        db.refresh(d)
    return TailorOutcome(docs, result.plan is None, result.problems, changelog)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_safe_document_path(path: str) -> bool:
    """Download guard: only files inside the generated-documents folder."""
    try:
        Path(path).resolve().relative_to(_documents_dir())
        return True
    except ValueError:
        return False
