"""
Review screen for the search test set: confirm or change the labels on the jobs each test search returned, and add jobs
found by hand on LinkedIn, Indeed or Google Jobs. Only reads and writes the local test-set files (see services/evalset.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.services import evalset

router = APIRouter(tags=["eval"])
PAGE = Path(__file__).resolve().parents[2] / "eval" / "review.html"


class LabelIn(BaseModel):
    key: str = Field(min_length=1, max_length=400)
    label: Literal["rel", "no", "unsure"] | None = None


class ManualJobIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=2, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    source: Literal["LinkedIn", "Indeed", "Google Jobs", "Other"] = "LinkedIn"
    in_today: bool = False


def _search(search_id: str) -> dict[str, Any]:
    s = evalset.search_by_id(search_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Unknown test search")
    return s


def _detail(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": s["id"],
        "group": s.get("group"),
        "title": s["criteria"].titles,
        "chips": evalset.describe(s["criteria"]),
        "relevant": s["relevant"],
        "not_relevant": s["not_relevant"],
        "progress": evalset.progress(s["id"]),
    }


@router.get("/eval-review", include_in_schema=False)
def review_page() -> HTMLResponse:
    try:
        return HTMLResponse(PAGE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Review page missing")


@router.get("/api/v1/eval/searches")
def list_searches() -> dict[str, Any]:
    return {"searches": [_detail(s) for s in evalset.load_searches()]}


@router.get("/api/v1/eval/searches/{search_id}")
def get_search(search_id: str) -> dict[str, Any]:
    s = _search(search_id)
    return {**_detail(s), "rows": evalset.rows_for(search_id)}


@router.put("/api/v1/eval/searches/{search_id}/label")
def put_label(search_id: str, body: LabelIn) -> dict[str, Any]:
    _search(search_id)
    if body.key not in {r["key"] for r in evalset.rows_for(search_id)}:
        raise HTTPException(status_code=404, detail="That job is not in this search")
    evalset.set_label(search_id, body.key, body.label, by="user")
    return {"ok": True, "progress": evalset.progress(search_id)}


@router.post("/api/v1/eval/searches/{search_id}/confirm-ai")
def confirm_ai(search_id: str) -> dict[str, Any]:
    _search(search_id)
    return {"confirmed": evalset.confirm_ai_labels(search_id), "progress": evalset.progress(search_id)}


@router.post("/api/v1/eval/searches/{search_id}/jobs")
def add_job(search_id: str, body: ManualJobIn) -> dict[str, Any]:
    _search(search_id)
    item = {"title": body.title.strip(), "company": body.company.strip(), "location": (body.location or "").strip() or None, "url": (body.url or "").strip()}
    key, _ = evalset.add_manual(search_id, item, body.source, body.in_today)
    return {"key": key, "progress": evalset.progress(search_id)}
