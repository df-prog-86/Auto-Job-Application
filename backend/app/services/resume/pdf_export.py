"""
PDF from the tailored Word copy using LibreOffice (free), so the PDF keeps the
Word layout. Runs a fixed local command, no shell, on files this app wrote.
If LibreOffice isn't installed the Word file is still produced and the
changelog says so.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_MAC_PATH = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def find_soffice() -> str | None:
    return shutil.which("soffice") or (_MAC_PATH if Path(_MAC_PATH).exists() else None)


def convert_to_pdf(docx_path: Path, out_dir: Path) -> Path | None:
    soffice = find_soffice()
    if soffice is None:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    # A throwaway profile folder so this never collides with a LibreOffice window the user has open.
    with tempfile.TemporaryDirectory() as profile:
        try:
            subprocess.run(
                [
                    soffice,
                    f"-env:UserInstallation=file://{profile}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_dir),
                    str(docx_path),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError):
            return None
    pdf = out_dir / (docx_path.stem + ".pdf")
    return pdf if pdf.exists() else None


def page_count(pdf_path: Path) -> int | None:
    try:
        import fitz

        with fitz.open(str(pdf_path)) as doc:
            return doc.page_count
    except Exception:
        return None
