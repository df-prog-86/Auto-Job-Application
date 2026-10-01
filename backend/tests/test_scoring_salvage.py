"""A model that runs on in the summary must not make scoring fail outright."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.services.llm.client import ChatCompletionResult
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import ResumeJobMatchResult
from app.services.qualification.pipeline import _salvage_match

RUNAWAY = '{\n "match_percentage": 65,\n "summary": "Strong operations background but no coding certification. ' + (
    "The role's analysis " * 2000
)


def test_salvage_keeps_score_and_a_short_clean_summary():
    out = _salvage_match(RUNAWAY)
    assert out is not None
    assert out.match_percentage == 65
    assert out.summary.startswith("Strong operations background but no coding certification.")
    assert len(out.summary) <= 410
    assert out.gaps == []


def test_salvage_refuses_without_a_usable_score():
    assert _salvage_match('{"summary": "no score here"') is None
    assert _salvage_match('{"match_percentage": 250, "summary": "x"') is None


class _RunawayClient:
    def __init__(self):
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return ChatCompletionResult(content=RUNAWAY, input_tokens=1, output_tokens=1, raw={})


def test_router_uses_salvage_after_retries_and_passes_the_token_cap(app_and_db, monkeypatch):
    _, SessionLocal = app_and_db
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "test-model")
    client = _RunawayClient()
    with SessionLocal() as db:
        router = ModelRouter(db, client=client)
        result = asyncio.run(
            router.get_structured(
                purpose="resume_job_match",
                prompt_version="v1",
                messages=[{"role": "user", "content": "x"}],
                response_model=ResumeJobMatchResult,
                max_tokens=900,
                salvage=_salvage_match,
            )
        )
    assert result.match_percentage == 65
    assert len(client.calls) == 3  # retried the normal number of times first
    assert all(c["max_tokens"] == 900 for c in client.calls)
