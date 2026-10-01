"""
Orchestrates Milestone 5 for one job: generate validated content, render it
to PDF and DOCX, and record both files as GeneratedDocument rows. Re-running
replaces the job's previous tailored resume rather than piling up copies.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.candidate import CandidateProfile
from app.models.documents import GeneratedDocument
from app.models.jobs import Job
from app.services.resume import rendering
from app.services.resume.generation import generate_tailored_content


@dataclass
class TailorOutcome:
    documents: list[GeneratedDocument]
    used_original_wording: bool
    problems: list[str]


def _documents_dir() -> Path:
    return Path(settings.GENERATED_DOCUMENTS_DIR).resolve()


def _remove_existing(db: Session, job: Job) -> None:
    for doc in db.query(GeneratedDocument).filter(
        GeneratedDocument.job_id == job.id, GeneratedDocument.document_type == "resume"
    ):
        try:
            Path(doc.local_path).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(doc)
    db.flush()


async def tailor_resume(db: Session, job: Job, profile: CandidateProfile) -> TailorOutcome:
    result = await generate_tailored_content(db, job, profile)
    resume = rendering.build_renderable(profile, result.content)
    digest = rendering.content_hash(resume)

    claim_ids = sorted(
        {cid for exp in result.content.experience for b in exp.bullets for cid in b.source_claim_ids}
        | set(result.content.summary_source_claim_ids)
    )

    out_dir = _documents_dir() / f"job_{job.id}"
    pdf_path = out_dir / "resume.pdf"
    docx_path = out_dir / "resume.docx"
    rendering.render_pdf(resume, pdf_path)
    rendering.render_docx(resume, docx_path)

    _remove_existing(db, job)
    now = dt.datetime.now(dt.timezone.utc)
    docs = [
        GeneratedDocument(
            job_id=job.id,
            document_type="resume",
            local_path=str(path),
            format=fmt,
            generated_at=now,
            template_version=rendering.TEMPLATE_VERSION,
            source_claim_ids=claim_ids,
            content_hash=digest,
        )
        for fmt, path in (("pdf", pdf_path), ("docx", docx_path))
    ]
    db.add_all(docs)
    db.commit()
    for d in docs:
        db.refresh(d)
    return TailorOutcome(docs, result.used_original_wording, result.problems)


def is_safe_document_path(path: str) -> bool:
    """Download guard: only files inside the generated-documents folder."""
    try:
        Path(path).resolve().relative_to(_documents_dir())
        return True
    except ValueError:
        return False
