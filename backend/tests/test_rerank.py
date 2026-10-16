"""The AI second opinion on saved-list matches. No network: the AI call is replaced."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.schemas.job_search import JobSearchIn
from app.services.discovery import rerank
from app.services.llm.client import LLMClient

CRIT = JobSearchIn(titles="revenue cycle manager", location="Boston, MA")


def job(title, fit, company="Acme"):
    return {"title": title, "company": company, "location": "Boston, MA", "fit": fit}


@pytest.fixture()
def ai(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "JOB_CACHE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "m", raising=False)
    monkeypatch.setattr(settings, "JOB_SEARCH_MODEL", "m", raising=False)
    calls = []

    def set_answer(content):
        async def fake(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=content, input_tokens=1, output_tokens=1)
        monkeypatch.setattr(LLMClient, "chat_completion", fake)

    return set_answer, calls


def test_parse_scores_accepts_only_a_full_list_of_numbers():
    assert rerank.parse_scores("[8, 3.5, 10]", 3) == [8.0, 3.5, 10.0]
    assert rerank.parse_scores("here: [11, -2]", 2) == [10.0, 0.0]
    assert rerank.parse_scores("[1, 2]", 3) is None
    assert rerank.parse_scores('["a", 2]', 2) is None
    assert rerank.parse_scores("no list", 1) is None


async def test_the_ai_lifts_a_better_fit_above_a_slightly_higher_word_match(ai):
    answer, calls = ai
    answer(json.dumps([2, 9, 9]))
    items = [job("Revenue Cycle Analyst", 0.70), job("Revenue Cycle Manager", 0.68), job("Manager, Revenue Cycle", 0.60)]
    out = await rerank.rerank(CRIT, items, 2)
    assert [i["title"] for i in out] == ["Revenue Cycle Manager", "Manager, Revenue Cycle"]
    assert "profile" not in calls[0]["messages"][1]["content"].lower()


async def test_the_answer_is_remembered(ai):
    answer, calls = ai
    answer(json.dumps([5, 6]))
    await rerank.rerank(CRIT, [job("A", 0.5), job("B", 0.5)], 2)
    await rerank.rerank(CRIT, [job("A", 0.5), job("B", 0.5)], 2)
    assert len(calls) == 1


async def test_a_bad_answer_or_no_model_leaves_the_order_alone(ai, monkeypatch):
    answer, _ = ai
    answer("sorry, no")
    items = [job("A", 0.9), job("B", 0.8), job("C", 0.7)]
    assert [i["title"] for i in await rerank.rerank(CRIT, items, 2)] == ["A", "B"]
    monkeypatch.setattr(settings, "JOB_SEARCH_MODEL", None, raising=False)
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", None, raising=False)
    assert [i["title"] for i in await rerank.rerank(CRIT, items, 2)] == ["A", "B"]


async def test_it_can_be_switched_off(ai, monkeypatch):
    answer, calls = ai
    answer("[1, 9]")
    monkeypatch.setattr(settings, "JOB_SEARCH_RERANK", "off", raising=False)
    assert [i["title"] for i in await rerank.rerank(CRIT, [job("A", 0.9), job("B", 0.8)], 2)] == ["A", "B"] and not calls
