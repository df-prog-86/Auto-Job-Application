"""
One-time download of O*NET job titles, so a search also finds the other names employers use for the same job.

  cd backend
  python -m scripts.load_onet                       # downloads from onetcenter.org and saves backend/data/onet/titles.json
  python -m scripts.load_onet --file PATH.zip       # use the "Text" format zip you downloaded yourself from
                                                    # https://www.onetcenter.org/database.html
  python -m scripts.load_onet --url URL             # a different address

Data: O*NET Database, U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), CC BY 4.0.
The credit is written to ATTRIBUTION.txt beside the file. Nothing is added to your job database.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from app.services.jobcache import onet

DEFAULT_URL = "https://www.onetcenter.org/dl_files/database/db_31_0_text.zip"
MAX_BYTES = 80 * 1024 * 1024


def _rows(z: zipfile.ZipFile, fragment: str) -> list[list[str]]:
    name = next((n for n in z.namelist() if fragment.lower() in n.lower() and n.lower().endswith(".txt")), None)
    if not name:
        return []
    lines = z.read(name).decode("utf-8", errors="replace").splitlines()
    return [ln.split("\t") for ln in lines[1:] if ln.strip()]


def build(z: zipfile.ZipFile) -> dict:
    titles = {r[0]: r[1].strip() for r in _rows(z, "Occupation Data") if len(r) >= 2}
    alts: dict[str, list[str]] = {}
    for r in _rows(z, "Alternate Titles"):
        if len(r) >= 2 and r[1].strip():
            alts.setdefault(r[0], []).append(r[1].strip())
    for r in _rows(z, "Sample of Reported Titles"):
        if len(r) >= 2 and r[1].strip():
            alts.setdefault(r[0], []).append(r[1].strip())
    occupations = [[titles.get(code, code), sorted(set(names))] for code, names in alts.items() if code in titles]
    m = re.search(r"db_(\d+)_(\d+)", " ".join(z.namelist()))
    return {"release": f"O*NET {m.group(1)}.{m.group(2)}" if m else "O*NET", "occupations": occupations}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file")
    p.add_argument("--url", default=DEFAULT_URL)
    args = p.parse_args()
    try:
        if args.file:
            raw = Path(args.file).read_bytes()
        else:
            print(f"Downloading {args.url} ...")
            with urllib.request.urlopen(args.url, timeout=120) as r:  # noqa: S310 (https address you can see)
                raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                print("The download was larger than expected, so it was not used.")
                return 1
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            data = build(z)
    except Exception as exc:  # a wrong address or a different file layout: say what to do instead of a traceback
        print(f"Could not load the titles ({type(exc).__name__}: {str(exc)[:120]}).")
        print("Download the \"Text\" version of the database from https://www.onetcenter.org/database.html and run again with --file PATH.zip")
        return 1
    if len(data["occupations"]) < 300:
        print(f"Only {len(data['occupations'])} occupations with other titles were found, so nothing was saved. Is this the Text format zip?")
        return 1
    dest = onet.data_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dest)
    (dest.parent / "ATTRIBUTION.txt").write_text(onet.ATTRIBUTION + "\n", encoding="utf-8")
    print(f"Saved {len(data['occupations'])} occupations ({data['release']}) to {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
