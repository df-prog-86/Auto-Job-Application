from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelRun(Base):
    """
    LLM invocation log for cost tracking (spec §9/§77). Never store secrets
    or unnecessary sensitive prompt contents here — this table is for cost
    and reliability accounting, not a prompt archive.
    """

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(50))  # extraction/qualification/tailoring/qa/...
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    output_validation_status: Mapped[str] = mapped_column(String(30), default="unknown")
