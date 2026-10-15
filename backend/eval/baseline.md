# Search baseline, October 13, 2026

Labels: 1,043 jobs. 90 were set by the owner during review; 953 are AI suggestions the owner accepted as good enough. The AI labeler
was corrected first (missing pay or place no longer means unsure), then the unsure jobs were asked again.
This is the number every later change has to beat.

Saved job lists frozen for the run: 66 employers, 19,615 open postings. 24 test searches, up to 15 results each.

| Variant | Avg results | Avg relevant | Relevant share | Best possible found | Duplicates | Dead links | Median s | Slowest 5% s | Avg cost |
|---|---|---|---|---|---|---|---|---|---|
| full (today's search as the app runs it) | 14.4 | 5.0 | 36% | 63% | 0 | 0% | 24.4 | 38.5 | $0.0278 |
| saved (saved lists only, no web search) | 14.3 | 4.4 | 32% | 55% | 0 | 0% | 6.4 | 10.6 | $0 |
| deep (wider candidate list from the saved lists, up to 60) | 43.0 | 10.4 | 27% | 95% | 70 in 20 searches | not checked | 1.8 | 2.7 | $0.0001 |

How to read it
- "Best possible found" counts a full screen of relevant results (15) as 100%, so a search is not penalized for what does not fit.
- The deep figure is high partly because most of the labeled pool came from that variant. Read it as headroom: the saved lists hold
  relevant jobs the top 15 does not show.
- The paid web search changed the label counts in about half of the 24 searches. Where it helped (nurse manager, compliance analyst,
  HR manager) the saved lists lack the employers.
- Many jobs were relevant but had no pay or place listed. Pay and location cleanup is the first data-quality change (step 2).
- "Duplicates" counts results with the same employer, title and city. Since step 2.6 two real openings that share all three are kept apart, so a few counted here may be legitimate.
- About 4 of 24 full searches billed one web call ($0.015) instead of two: one call probably failed. Not yet investigated.

Targets to beat (proposals): relevant share above 36%, best possible found above 63%, median under 1 second for index results,
average cost under $0.005, no duplicates, dead links under 1% (owner's goal).

## Step 2 result, October 14, 2026 (pool grew to 1,133 labeled jobs, so the baseline was re-scored on it)

| Variant | Relevant share | Best possible found | Median s | Slowest 5% s | Avg cost | Duplicates (old count) |
|---|---|---|---|---|---|---|
| full, baseline | 36% | 46% | 24.4 | 38.5 | $0.0278 | 0 |
| full, after step 2 | 44% | 58% | 22.2 | 27.1 | $0.0287 | 20 in 9 searches |
| saved, baseline | 32% | 41% | 6.4 | 10.6 | $0 | 0 |
| saved, after step 2 | 32% | 39% | 5.4 | 13.2 | $0 | 22 in 11 searches |
| deep, baseline | 27% | 79% | 1.8 | 2.7 | $0.0001 | 70 |
| deep, after step 2 | 27% | 80% | 0.0 | 0.0 | $0 | 70 |

Reading it
- The earlier "best possible found" figures (63%, 56%, 47%) were measured on a smaller pool. Compare only numbers from the same table.
- The gain is in the full search (web search plus saved lists): +8 points relevant share, +12 points best possible found. The saved-only
  search did not improve, so the data-quality changes alone did not lift ranking inside the saved lists. Web search results vary from run to
  run, so part of the full-search gain may be noise until it is repeated.
- Duplicates rose from 0 because step 2.6 no longer merges two job numbers on one board. Those were counted as duplicates by the old rule.
  Scoring now counts a repeat once and reports separate openings on their own (`eval_search dupes --run NAME` lists them).
- Dead links were not checked in this run (add `--check-live`). The goal is under 1%.
- Saved-search slowest 5% got slower (10.6 to 13.2 seconds), probably from reading saved descriptions. To check.
- Pay is now filled for only 3% of saved postings and coordinates resolve for 28% of place names, because most employers
  (Workday and others) do not give pay in their lists.

## Step 2 repeat run, October 14, 2026 (pool 1,165 labeled jobs; every row below is on that same pool)

| Variant | Relevant share | Best possible found | Dead links | Median s | Slowest 5% s | Avg cost |
|---|---|---|---|---|---|---|
| full, baseline | 36% | 44% | 0% | 24.4 | 38.5 | $0.0278 |
| full, after step 2 | 44% | 55% | not checked | 22.2 | 27.1 | $0.0287 |
| full, after step 2, repeated with link check | 46% | 55% | 0% | 24.3 | 33.9 | $0.0244 |
| saved, baseline | 32% | 40% | 0% | 6.4 | 10.6 | $0 |
| saved, after step 2 (twice, identical) | 33% | 37% | 0% | 6.5 | 10.1 | $0 |

- The full-search gain repeated (44% then 46% relevant share, 55% best possible both times), so it is not noise. Cost came down slightly.
- Saved-only search did not improve (best possible found 40% to 37%): step 2 did not fix ranking inside the saved lists.
- Dead links 0% on both searches with the link check on; the goal is under 1%.
- The saved-search slowdown seen earlier was noise (slowest 5% back to 10.1 seconds).
- Repeats still show in the full and saved searches (13 to 17 per run). Whether they are true repeats is being checked with `eval_search dupes`
  and `eval_search misses`; the repeat rule was tightened so separate requisition numbers count as separate openings.
