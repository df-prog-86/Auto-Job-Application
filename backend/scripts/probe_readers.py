"""
Reads real employers with the new readers and prints what came back. Nothing is saved to the app: it only makes read requests,
and it writes one text file of raw samples next to the other experiment reports.

    PYTHONPATH=. python -m scripts.probe_readers URL [URL ...]
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from app.services.jobcache import readers

RAW = {
    "breezy": lambda i: f"https://{i}.breezy.hr/json",
    "workable": lambda i: f"https://apply.workable.com/api/v1/widget/accounts/{i}",
    "bamboohr": lambda i: f"https://{i}.bamboohr.com/careers/list",
    "pinpoint": lambda i: f"https://{i}.pinpointhq.com/postings.json",
    "jazzhr": lambda i: f"https://{i}.applytojob.com/apply",
    "jobvite": lambda i: f"https://jobs.jobvite.com/{i}/jobs",
    "icims": lambda i: f"https://{i}/jobs/search?ss=1&in_iframe=1",
    "taleo": lambda i: "https://%s/%s/ats/careers/v2/searchResults?org=%s&cws=%s" % tuple(i.split("|")),
    "successfactors": lambda i: "https://%s/%s/search/?q=&optionsFacetsDD_country=US&startrow=0" % tuple(i.split("|")),
    "oracle": lambda i: "https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber=%s,limit=2" % tuple(i.split("|")),
}


async def main(urls: list[str]) -> None:
    out_dir = pathlib.Path.home() / "Desktop" / "job-agent-experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = out_dir / "probe-raw-samples.txt"
    lines: list[str] = []
    throttle = readers.Throttle()
    async with readers.make_client() as client:
        for url in urls:
            ref = readers.employer_ref(url)
            print(f"\n== {url}")
            if ref is None:
                print("   not recognised as a supported hiring system")
                continue
            system, ident = ref
            print(f"   system={system} identifier={ident}")
            try:
                res = await readers.read_employer(system, ident, client, throttle)
                print(f"   OK: {len(res.postings)} jobs, complete={res.complete}, name={res.name!r}")
                for p in res.postings[:3]:
                    print(f"     - {p.title} | {p.location} | {p.work_type} | pay={p.pay_text} | posted={p.posted_at} | {p.url}")
            except readers.ReaderError as exc:
                print(f"   FAILED: {exc}")
            raw_url = RAW[system](ident) if system in RAW else None
            if raw_url:
                try:
                    r = await client.get(raw_url, headers={"Accept": "application/json, text/html;q=0.9"})
                    lines += [f"===== {system} {ident} -> HTTP {r.status_code} ({len(r.text)} chars)", r.text[:6000], ""]
                except Exception as exc:  # a probe: report and carry on
                    lines += [f"===== {system} {ident} -> {type(exc).__name__}", ""]
    sample.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRaw samples saved to {sample}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
