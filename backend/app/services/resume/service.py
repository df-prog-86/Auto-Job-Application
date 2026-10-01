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
    # Clear the previous version first: the new files reuse the same paths, so
    # deleting afterwards would delete the files we just wrote.
    _remove_existing(db, job)
    pages = rendering.render_pdf(resume, pdf_path)
    rendering.render_docx(resume, docx_path)

    changelog = [rendering.clean_text(note) for note in result.changelog]
    if pages > rendering.MAX_PAGES:
        changelog.append(
            f"The resume runs {pages} pages, over the {rendering.MAX_PAGES}-page limit. "
            "Trim older or less relevant bullets from your profile claims and recreate it."
        )
    changelog_path = out_dir / "changelog.txt"
    changelog_path.write_text(
        f"Tailoring changelog: {job.title}, {job.company}\n\n"
        + ("\n".join(f"- {n}" for n in changelog) or "- No notes.")
        + "\n",
        encoding="utf-8",
    )

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
    docs.append(
        GeneratedDocument(
            job_id=job.id,
            document_type="changelog",
            local_path=str(changelog_path),
            format="txt",
            generated_at=now,
            template_version=rendering.TEMPLATE_VERSION,
            source_claim_ids=[],
            content_hash=digest,
        )
    )
    db.add_all(docs)
    db.commit()
    for d in docs:
        db.refresh(d)
    return TailorOutcome(docs, result.used_original_wording, result.problems, changelog)


def is_safe_document_path(path: str) -> bool:
    """Download guard: only files inside the generated-documents folder."""
    try:
        Path(path).resolve().relative_to(_documents_dir())
        return True
    except ValueError:
        return False
