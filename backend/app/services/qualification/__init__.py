"""
Qualification (Milestone 4, simplified): scores a stored Job against the
candidate's own resume/profile with a single, direct comparison -- one LLM
call reads the candidate's background and the job description and returns
a match percentage, a plain-language explanation, and a short list of
concrete gaps (see resume_summary.py and pipeline.py).

This replaces an earlier four-stage design (free hard-constraint checks,
separate structured requirement extraction, deterministic evidence
matching, and a five-component weighted score) per product direction: the
score doesn't need to be that elaborate, it just needs to compare the
resume to the posting.

Only ever runs when the candidate explicitly clicks "Score match" /
"Re-score match" on the Jobs page (app/api/jobs.py) -- never automatically
on add, so adding a job never costs an LLM call by itself. Nothing past
this point (tailoring, application) starts on its own either; that needs
the candidate to click "Proceed with Application" (Job.application_status).
"""
