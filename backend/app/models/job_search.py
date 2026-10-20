from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class JobSearchResult(Base, TimestampMixin):
    """
    A posting the web search found. It stays on the Job Search page until the
    person adds it to their jobs or removes it; removed results are kept (hidden)
    so the same posting is not offered again.
    """

    __tablename__ = "job_search_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    work_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    salary_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    posted_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # The posting's requirements as read from its page, kept so scoring and adding do not read it twice.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How well the title, place and date fit the search (0 to 1), worked out by code when the result was found, and a short why.
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fit_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0 to 1, set when the person asks
    match_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_gaps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    match_from_page: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # False = scored from the short summary only
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), index=True)
    url_key: Mapped[str] = mapped_column(String(1000), index=True)  # host + path, for de-duplication
    # True when the link appeared in the search engine's own sources, not only in the model's answer.
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new / added / removed / stale (from an earlier search; kept for its scores)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)

    @property
    def page_no(self) -> int | None:
        """The page it was opened from (pages 1 and later of the saved-list matches); None for a job a search itself returned."""
        page = (self.criteria or {}).get("page")
        return page if isinstance(page, int) and page > 0 else None
