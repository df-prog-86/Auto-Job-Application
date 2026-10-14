# Search baseline, October 13, 2026

Provisional: every label is an AI suggestion (1,043 jobs, none confirmed by a person yet). Replace this file with the numbers
from `python -m scripts.eval_search score --only-you` once the labels are reviewed.

Saved job lists frozen for the run: 66 employers, 19,615 open postings. 24 test searches, up to 15 results each.

| Variant | Avg results | Avg relevant | Relevant share | Best possible found | Duplicates | Dead links | Median s | Slowest 5% s | Avg cost |
|---|---|---|---|---|---|---|---|---|---|
| full (today's search as the app runs it) | 14.4 | 3.6 | 31% | 56% | 0 | 0% | 24.4 | 38.5 | $0.0278 |
| saved (saved lists only, no web search) | 14.3 | 3.1 | 27% | 47% | 0 | 0% | 6.4 | 10.6 | $0 |
| deep (wider candidate list from the saved lists, up to 60) | 43.0 | 7.8 | 22% | 89% | 70 in 20 searches | not checked | 1.8 | 2.7 | $0.0001 |

How to read it
- "Best possible found" counts a full screen of relevant results (15) as 100%, so a search is not penalized for what does not fit.
- The deep figure is high partly because most of the labeled pool came from that variant. Read it as headroom: the saved lists hold
  relevant jobs the top 15 does not show.
- The paid web search changed the label counts in about half of the 24 searches. Where it helped (nurse manager, compliance analyst,
  HR manager) the saved lists lack the employers.
- About 4 of 24 full searches billed one web call ($0.015) instead of two: one call probably failed. Not yet investigated.

Targets to beat (proposals): relevant share above 31%, best possible found above 56%, median under 1 second for index results,
average cost under $0.005, no duplicates, dead links under 5%.
