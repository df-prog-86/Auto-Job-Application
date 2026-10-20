# Search quality test set

24 fixed searches (`test_searches.json`), each with a plain description of what counts as a relevant result.
The script and the review screen turn them into numbers, so every change to job search is a before and after.

Run order (from `backend`, see `python -m scripts.eval_search --help`):

1. `snapshot` freezes a copy of the saved job lists, so every run reads the same jobs.
2. `run --arm saved|full|deep --name baseline` runs the searches (saved lists only, today's full search, the wider candidate list).
3. `pool` gathers every job the runs returned. `prelabel` adds AI suggestions (a few cents).
4. Open http://127.0.0.1:8765/eval-review to confirm or change the suggestions and to add jobs found by hand on LinkedIn, Indeed or Google Jobs.
5. `score --runs baseline` prints the report.

Runs, pool and labels live in `backend/data/eval/` (local only, never committed).

## Description search before and after

Search can also read the opening lines of each job's description (switch: `JOB_SEARCH_USE_DESCRIPTION`, on by default). To compare:

1. `python -m scripts.cache_tools reindex --db data/eval/job_cache_frozen.db` builds the description index on the frozen copy.
2. `JOB_SEARCH_USE_DESCRIPTION=false python -m scripts.eval_search run --arm saved --name desc-off`, then `python -m scripts.eval_search run --arm saved --name desc-on`.
3. `pool`, `prelabel` (jobs found through descriptions are new to the pool), then `score --runs desc-off,desc-on`.
