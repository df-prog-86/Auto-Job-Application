"""
Deterministic total-experience calculator (spec §13). Never let an LLM
guess "years of experience" — merge overlapping date intervals for a given
skill/scope so simultaneous jobs/projects aren't double-counted, and be
honest when dates are missing rather than estimating.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class DateInterval:
    start: dt.date
    end: dt.date | None  # None = ongoing/current


def _effective_end(interval: DateInterval, today: dt.date) -> dt.date:
    return interval.end if interval.end is not None else today


def merge_intervals(intervals: list[DateInterval], today: dt.date | None = None) -> list[DateInterval]:
    """Standard interval-merge: sort by start, merge any that overlap or touch."""
    if not intervals:
        return []
    today = today or dt.date.today()

    sortable = sorted(intervals, key=lambda i: i.start)
    merged: list[DateInterval] = [sortable[0]]

    for current in sortable[1:]:
        last = merged[-1]
        last_end = _effective_end(last, today)
        current_end = _effective_end(current, today)

        if current.start <= last_end:
            # Overlapping or adjacent — extend the merged interval instead
            # of adding a new one, so total duration doesn't double-count.
            new_end: dt.date | None
            if last.end is None or current.end is None:
                new_end = None  # either one being "ongoing" makes the merged interval ongoing
            else:
                new_end = max(last_end, current_end)
            merged[-1] = DateInterval(start=last.start, end=new_end)
        else:
            merged.append(current)

    return merged


def total_experience_days(intervals: list[DateInterval], today: dt.date | None = None) -> int:
    """
    Total non-overlapping days of experience across the given intervals.
    Callers with no date data for a claim should exclude it from the input
    entirely and represent that gap explicitly (spec §21: UNKNOWN, not a
    silent zero) — this function has no concept of "missing," only dates.
    """
    today = today or dt.date.today()
    merged = merge_intervals(intervals, today)
    total = 0
    for interval in merged:
        end = _effective_end(interval, today)
        total += max(0, (end - interval.start).days)
    return total


def total_experience_years(intervals: list[DateInterval], today: dt.date | None = None) -> float:
    return total_experience_days(intervals, today) / 365.25
