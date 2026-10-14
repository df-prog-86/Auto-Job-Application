from app.services.discovery import same_job


def test_job_refs_are_read_from_the_main_hiring_systems():
    assert same_job.job_ref("https://boards.greenhouse.io/acme/jobs/123") == ("greenhouse:acme", "123")
    assert same_job.job_ref("https://jobs.lever.co/Acme/AbC-1") == ("lever:acme", "abc-1")
    assert same_job.job_ref("https://jobs.ashbyhq.com/acme/uuid-9") == ("ashby:acme", "uuid-9")
    assert same_job.job_ref("https://x.wd5.myworkdayjobs.com/en-US/Careers/job/Boston/Mgr_R-48213") == ("workday:x.wd5.myworkdayjobs.com:careers", "r-48213")
    assert same_job.job_ref("https://jobs.smartrecruiters.com/Acme/743999-software-engineer") == ("smartrecruiters:acme", "743999")
    assert same_job.job_ref("https://acme.com/careers/1") is None


def test_requisition_numbers_come_from_addresses_and_titles():
    ids = same_job.req_ids({"url": "https://acme.com/job?gh_jid=555&utm=x", "title": "Analyst (Req 48213)"})
    assert {"555", "48213"} <= ids


def test_same_board_job_numbers_always_decide():
    a = {"url": "https://boards.greenhouse.io/acme/jobs/1", "_desc": "x " * 200}
    b = {"url": "https://boards.greenhouse.io/acme/jobs/2", "_desc": "x " * 200}
    assert not same_job.same_posting(a, b)       # identical text, different numbers on one board: two jobs
    assert same_job.same_posting(a, {"url": "https://boards.greenhouse.io/acme/jobs/1?gh_src=abc"})


def test_similarity_needs_enough_words_to_judge():
    long = " ".join(f"word{i}" for i in range(60))
    assert same_job.similarity(long, long) == 1.0 and same_job.similarity("short text", "short text") == 0.0
    assert same_job.similarity(long, " ".join(f"other{i}" for i in range(60))) == 0.0
