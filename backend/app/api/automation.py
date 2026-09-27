"""Automation start/pause (spec §79). Full REVIEW/AUTO mode logic and the
rate controller land in Milestone 11 — this is the minimal control surface
Milestone 1 needs so the dashboard's Start/Pause control is real, not a stub.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.system import AutomationState

router = APIRouter(prefix="/api/v1/automation", tags=["automation"])


class AutomationModeResponse(BaseModel):
    mode: str


def _get_or_create_state(db: Session) -> AutomationState:
    state = db.query(AutomationState).first()
    if state is None:
        state = AutomationState(mode="PAUSED")
        db.add(state)
        db.commit()
    return state


@router.post("/start", response_model=AutomationModeResponse)
def start_automation(db: Session = Depends(get_db)) -> AutomationModeResponse:
    state = _get_or_create_state(db)
    # Milestone 1: binary on/off only. REVIEW vs AUTO mode selection and the
    # per-adapter certification gate (spec §80) are wired in with Milestone 7+.
    state.mode = "REVIEW"
    db.commit()
    return AutomationModeResponse(mode=state.mode)


@router.post("/pause", response_model=AutomationModeResponse)
def pause_automation(db: Session = Depends(get_db)) -> AutomationModeResponse:
    state = _get_or_create_state(db)
    state.mode = "PAUSED"
    db.commit()
    return AutomationModeResponse(mode=state.mode)
