"""
Qualification pipeline (spec §21-24, Milestone 4): scores a stored Job
against the candidate's own verified profile. Four stages, cheapest first:

1. hard_constraints  -- free, deterministic PASS/FAIL/UNKNOWN checks.
2. requirement_extraction -- one cheap LLM call, only for what stage 1
   didn't already rule out.
3. evidence_matching -- deterministic comparison of each requirement
   against the candidate's verified claims/skills/education/certifications.
4. scoring -- combines 1-3 into an interpretable weighted score, stored on
   JobEvaluation, with every component visible (spec §23: "The UI must show
   why a job qualified").

Runs automatically once a job is added -- ranking a job is informational and
costs nothing to redo. Nothing past this point (tailoring, application)
happens without the candidate explicitly clicking "Proceed with
Application" on the Jobs page; see Job.application_status.
"""
