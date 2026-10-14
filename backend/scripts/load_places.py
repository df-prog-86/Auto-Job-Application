"""
One-time download of US place coordinates, so "around <city>" works for every town and not just the built-in list.

  cd backend
  python -m scripts.load_places              # downloads about 3 MB from geonames.org and saves backend/data/geo/us_places.json
  python -m scripts.load_places --file PATH  # use a cities5000.zip you already downloaded

Data: GeoNames (https://www.geonames.org), licensed CC BY 4.0. The credit line is written to ATTRIBUTION.txt beside the file.
The app works without this file (it has a built-in table of large cities and the greater Boston area). Nothing is added to your
job database.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

from app.services.jobcache import geo

URL = "https://download.geonames.org/export/dump/cities5000.zip"
MAX_BYTES = 30 * 1024 * 1024


def parse(text: str) -> list[list]:
    """GeoNames lines (tab separated): 1 name, 4 latitude, 5 longitude, 7 feature code, 8 country, 10 state, 14 population."""
    out: list[list] = []
    for line in text.splitlines():
        c = line.split("\t")
        if len(c) < 15 or c[8] != "US" or not c[10]:
            continue
        try:
            out.append([c[1], c[10], round(float(c[4]), 4), round(float(c[5]), 4), int(c[14] or 0)])
        except ValueError:
            continue
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file")
    args = p.parse_args()
    if args.file:
        raw = Path(args.file).read_bytes()
    else:
        print(f"Downloading {URL} ...")
        with urllib.request.urlopen(URL, timeout=60) as r:  # noqa: S310 (fixed https address)
            raw = r.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            print("The download was larger than expected, so it was not used.")
            return 1
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next((n for n in z.namelist() if n.endswith(".txt")), None)
        if not name:
            print("That zip has no place list in it.")
            return 1
        rows = parse(z.read(name).decode("utf-8"))
    if len(rows) < 500:
        print(f"Only {len(rows)} US places were found, so the file was not saved.")
        return 1
    dest = geo.geo_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dest)
    (dest.parent / "ATTRIBUTION.txt").write_text("Place coordinates: GeoNames (https://www.geonames.org), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).\n", encoding="utf-8")
    print(f"Saved {len(rows)} US places to {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
