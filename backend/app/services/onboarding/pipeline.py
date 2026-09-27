"""
Onboarding pipeline orchestration (spec §10): ties together validation,
local text extraction, structured LLM extraction, and verified-claim
generation. Nothing here commits to the database — that happens only after
the candidate has reviewed the result (see api/profile.py's commit
endpoint), per spec §10's "Candidate review" step preceding "Commit
profile."
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.profile import DraftClaimOut, ResumeParseResponse
from app.services.llm.router import ModelRouter, build_extraction_prompt
from app.services.llm.schemas import ResumeExtraction
from app.services.onboarding.claims import generate_claims
from app.services.onboarding.text_extraction import extract_docx_text, extract_pdf_text
from app.services.onboarding.validation import validate_resume_upload

TEXT_PREVIEW_CHARS = 2000


class ResumeValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def parse_resume(db: Session, filename: str, data: bytes) -> ResumeParseResponse:
    validation = validate_resume_upload(filename, data)
    if not validation.valid:
        raise ResumeValidationError(validation.error or "Invalid resume file.")

    if validation.detected_type == "pdf":
        extracted = extract_pdf_text(data)
    else:
        extracted = extract_docx_text(data)

    if not extracted.text.strip():
        raise ResumeValidationError(
            "Could not extract any text from this file, even with OCR. It may be corrupted "
            "or image-only in a way local OCR couldn't read."
        )

    router = ModelRouter(db)
    messages = build_extraction_prompt(extracted.text, ResumeExtraction.model_json_schema())
    extraction = await router.get_structured(
        purpose="resume_extraction",
        prompt_version="v1",
        messages=messages,
        response_model=ResumeExtraction,
    )

    draft_claims = generate_claims(extraction)

    return ResumeParseResponse(
        extracted_text_preview=extracted.text[:TEXT_PREVIEW_CHARS],
        used_ocr=extracted.used_ocr,
        extraction=extraction,
        draft_claims=[
            DraftClaimOut(
                category=c.category,
                canonical_text=c.canonical_text,
                employer=c.employer,
                associated_role=c.associated_role,
                skills=c.skills,
                start_date=c.start_date,
                end_date=c.end_date,
                metrics=c.metrics,
                source_section=c.source_section,
                source_text=c.source_text,
            )
            for c in draft_claims
        ],
    )
