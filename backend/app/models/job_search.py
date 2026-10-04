from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
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
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), index=True)
    url_key: Mapped[str] = mapped_column(String(1000), index=True)  # host + path, for de-duplication
    # True when the link appeared in the search engine's own sources, not only in the model's answer.
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new / added / removed
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
