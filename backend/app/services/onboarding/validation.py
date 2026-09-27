"""File-level validation for resume uploads (spec §10): extension/MIME
sniffing and a size cap, before anything touches a parser."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

ALLOWED_EXTENSIONS = {".pdf", ".docx"}

PDF_MAGIC = b"%PDF-"
DOCX_MAGIC = b"PK\x03\x04"  # DOCX is a zip archive


@dataclass
class ValidationResult:
    valid: bool
    detected_type: str | None  # "pdf" | "docx" | None
    error: str | None = None


def validate_resume_upload(filename: str, data: bytes) -> ValidationResult:
    if len(data) == 0:
        return ValidationResult(valid=False, detected_type=None, error="File is empty.")

    if len(data) > settings.MAX_RESUME_UPLOAD_BYTES:
        limit_mb = settings.MAX_RESUME_UPLOAD_BYTES / (1024 * 1024)
        return ValidationResult(
            valid=False, detected_type=None, error=f"File exceeds the {limit_mb:.0f}MB limit."
        )

    lower_name = filename.lower()
    if not any(lower_name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return ValidationResult(
            valid=False, detected_type=None, error="Only .pdf and .docx files are supported."
        )

    # Trust the file's own magic bytes over its extension — a renamed file
    # shouldn't reach a parser expecting a different format.
    if data.startswith(PDF_MAGIC):
        detected = "pdf"
    elif data.startswith(DOCX_MAGIC):
        detected = "docx"
    else:
        return ValidationResult(
            valid=False, detected_type=None, error="File content doesn't match a PDF or DOCX file."
        )

    claimed = "pdf" if lower_name.endswith(".pdf") else "docx"
    if claimed != detected:
        return ValidationResult(
            valid=False,
            detected_type=detected,
            error=f"File extension says {claimed}, but its content looks like {detected}.",
        )

    return ValidationResult(valid=True, detected_type=detected)
