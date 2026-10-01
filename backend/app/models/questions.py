from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class PendingQuestion(Base, TimestampMixin):
    """
    An application question the extension left blank because it wasn't sure
    how to answer it. Shown on the Needs Attention page; once the candidate
    answers, the answer is also remembered (as a CandidateAnswer keyed
    "q:<question_key>") so the same question is filled automatically next time.
    """

    __tablename__ = "pending_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(500))
    question_key: Mapped[str] = mapped_column(String(500), index=True)
    field_type: Mapped[str] = mapped_column(String(30), default="text")
    options: Mapped[list] = mapped_column(JSON, default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / answered / dismissed
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
