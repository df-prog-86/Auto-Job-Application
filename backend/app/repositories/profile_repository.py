"""
Persists a reviewed/approved onboarding result into the profile tables
(spec §10 "Commit profile"). Single-user local product: there is at most
one CandidateProfile row; re-committing (e.g. after a resume update)
updates it in place rather than creating a second candidate.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.candidate import (
    CandidateProfile,
    Certification,
    Education,
    EmploymentHistory,
    Skill,
    VerifiedClaim,
)
from app.schemas.profile import CommitProfileRequest
from app.services.onboarding.claims import parse_partial_date


def get_current_profile(db: Session) -> CandidateProfile | None:
    return db.query(CandidateProfile).order_by(CandidateProfile.id).first()


def commit_profile(db: Session, request: CommitProfileRequest) -> CandidateProfile:
    extraction = request.extraction
    profile = get_current_profile(db)

    if profile is None:
        profile = CandidateProfile(
            name=extraction.contact.name,
            preferred_name=extraction.contact.preferred_name,
            email=extraction.contact.email or "",
            phone=extraction.contact.phone,
            location=extraction.contact.location,
            linkedin_url=extraction.contact.linkedin_url,
            portfolio_urls=extraction.contact.portfolio_urls,
        )
        db.add(profile)
        db.flush()  # assign profile.id before attaching children
    else:
        profile.name = extraction.contact.name
        profile.preferred_name = extraction.contact.preferred_name
        profile.email = extraction.contact.email or profile.email
        profile.phone = extraction.contact.phone
        profile.location = extraction.contact.location
        profile.linkedin_url = extraction.contact.linkedin_url
        profile.portfolio_urls = extraction.contact.portfolio_urls

    # Re-committing replaces resume-derived history/claims rather than
    # accumulating duplicates on every re-upload. Answers/voluntary
    # disclosures live in separate tables untouched by this function.
    for existing in list(profile.employment_history):
        db.delete(existing)
    for existing in list(profile.education):
        db.delete(existing)
    for existing in list(profile.skills):
        db.delete(existing)
    for existing in list(profile.certifications):
        db.delete(existing)
    db.query(VerifiedClaim).filter(VerifiedClaim.profile_id == profile.id).delete()

    for entry in extraction.employment:
        db.add(
            EmploymentHistory(
                profile_id=profile.id,
                employer=entry.employer,
                title=entry.title,
                start_date=parse_partial_date(entry.start_date),
                end_date=parse_partial_date(entry.end_date),
                original_resume_text=entry.source_text,
            )
        )

    for edu in extraction.education:
        db.add(
            Education(
                profile_id=profile.id,
                institution=edu.institution,
                degree=edu.degree,
                field=edu.field,
                start_date=parse_partial_date(edu.start_date),
                end_date=parse_partial_date(edu.end_date),
                source="resume",
            )
        )

    for skill_name in extraction.skills:
        db.add(
            Skill(
                profile_id=profile.id,
                canonical_skill=skill_name,
                candidate_confirmed=True,  # reached here only after candidate review
                source="resume",
            )
        )

    for cert in extraction.certifications:
        db.add(
            Certification(
                profile_id=profile.id,
                certification=cert.certification,
                issuer=cert.issuer,
                date=parse_partial_date(cert.date),
                expiration=parse_partial_date(cert.expiration),
                source="resume",
            )
        )

    for claim in request.approved_claims:
        db.add(
            VerifiedClaim(
                profile_id=profile.id,
                category=claim.category,
                canonical_text=claim.canonical_text,
                employer=claim.employer,
                associated_role=claim.associated_role,
                skills=claim.skills,
                start_date=claim.start_date,
                end_date=claim.end_date,
                metrics=claim.metrics,
                source_document=request.resume_filename,
                source_section=claim.source_section,
                source_text=claim.source_text,
                verified=True,  # candidate explicitly approved this claim before commit
            )
        )

    db.commit()
    db.refresh(profile)
    return profile
