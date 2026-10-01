"""
Provider-neutral model routing (spec §76). Four roles — FAST, FALLBACK,
ESCALATION, EMBEDDING — map to configured model identifiers, not hard-coded
model names, so swapping providers or models is a config change.

Policy (spec §11, §76):
  - Structured extraction goes to FAST.
  - Invalid structured output, retried up to 2 times on FAST, then escalates
    to FALLBACK once. Still failing -> StructuredOutputError; the caller
    (onboarding service) is responsible for routing that to human review
    rather than proceeding with unvalidated data.
  - Every attempt is logged to ModelRuns (purpose, model, prompt version,
    token counts, success/failure) regardless of outcome.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Callable, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.model_runs import ModelRun
from app.services.llm.client import LLMClient
from app.services.llm.exceptions import LLMNotConfiguredError, StructuredOutputError

ModelRole = Literal["FAST", "FALLBACK", "ESCALATION", "EMBEDDING"]

T = TypeVar("T", bound=BaseModel)

MAX_STRUCTURED_RETRIES_PER_TIER = 2  # spec §11: "no more than two structured retries"


def _model_for_role(role: ModelRole) -> str | None:
    return {
        "FAST": settings.PRIMARY_FAST_MODEL,
        "FALLBACK": settings.FALLBACK_FAST_MODEL,
        "ESCALATION": settings.ESCALATION_MODEL,
        "EMBEDDING": settings.EMBEDDING_MODEL,
    }[role]


class ModelRouter:
    def __init__(self, db: Session, client: LLMClient | None = None) -> None:
        self._db = db
        self._client = client or LLMClient()

    async def get_structured(
        self,
        *,
        purpose: str,
        prompt_version: str,
        messages: list[dict[str, str]],
        response_model: type[T],
        primary_role: ModelRole = "FAST",
        fallback_role: ModelRole = "FALLBACK",
        max_tokens: int | None = None,
        temperature: float | None = None,
        salvage: Callable[[str], T | None] | None = None,
    ) -> T:
        """
        Runs the retry-then-fallback policy and returns a validated instance
        of `response_model`. Raises StructuredOutputError if the whole
        budget is exhausted, or LLMNotConfiguredError if no model is set for
        either role (a real, expected state before any provider is wired
        in — callers must handle it, not treat it as a bug).
        """
        attempts: list[str] = []
        last_content = ""
        schema = response_model.model_json_schema()

        for role in (primary_role, fallback_role):
            model_name = _model_for_role(role)
            if not model_name:
                continue

            max_attempts = MAX_STRUCTURED_RETRIES_PER_TIER + 1 if role == primary_role else 1
            for attempt_num in range(max_attempts):
                attempt_messages = list(messages)
                if attempt_num > 0:
                    attempt_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous response did not match the required JSON "
                                "schema. Return ONLY valid JSON matching the schema exactly."
                            ),
                        }
                    )

                try:
                    extra: dict = {}
                    if max_tokens is not None:
                        extra["max_tokens"] = max_tokens
                    if temperature is not None:
                        extra["temperature"] = temperature
                    result = await self._client.chat_completion(
                        model=model_name, messages=attempt_messages, json_schema=schema, **extra
                    )
                except LLMNotConfiguredError:
                    raise
                except Exception as exc:  # network/HTTP error from the provider
                    attempts.append(f"{model_name} (attempt {attempt_num + 1}): request failed: {exc}")
                    self._log_run(
                        purpose, model_name, prompt_version, 0, 0, success=False, status="request_error"
                    )
                    continue

                last_content = result.content
                try:
                    parsed = response_model.model_validate_json(result.content)
                except (ValidationError, ValueError) as exc:
                    attempts.append(
                        f"{model_name} (attempt {attempt_num + 1}): schema validation failed: {exc}"
                    )
                    self._log_run(
                        purpose,
                        model_name,
                        prompt_version,
                        result.input_tokens,
                        result.output_tokens,
                        success=False,
                        status="schema_invalid",
                    )
                    continue

                self._log_run(
                    purpose,
                    model_name,
                    prompt_version,
                    result.input_tokens,
                    result.output_tokens,
                    success=True,
                    status="valid",
                )
                return parsed

        # Every attempt was unusable. If the caller can safely rescue something
        # from the last reply (e.g. a score from a reply that ran on and was cut
        # off), let it; otherwise fail as before.
        if salvage is not None and last_content:
            rescued = salvage(last_content)
            if rescued is not None:
                return rescued

        if not any(_model_for_role(r) for r in (primary_role, fallback_role)):
            raise LLMNotConfiguredError(
                f"No model configured for role {primary_role!r} or fallback {fallback_role!r}."
            )
        raise StructuredOutputError(
            f"Structured output for purpose={purpose!r} failed after exhausting retry budget. "
            f"Last problem: {(attempts[-1] if attempts else 'none recorded')[:300]}",
            attempts=attempts,
        )

    def _log_run(
        self,
        purpose: str,
        model: str,
        prompt_version: str,
        input_tokens: int,
        output_tokens: int,
        *,
        success: bool,
        status: str,
    ) -> None:
        # Cost estimation requires a per-model pricing table, which is a
        # product-configuration concern (spec §77) added once a real
        # provider is wired in; 0.0 is an honest placeholder, not a claim.
        run = ModelRun(
            purpose=purpose,
            model=model,
            prompt_version=prompt_version,
            timestamp=datetime.now(UTC),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=0.0,
            success=success,
            output_validation_status=status,
        )
        self._db.add(run)
        self._db.commit()


def build_extraction_prompt(resume_text: str, schema: dict) -> list[dict[str, str]]:
    """Shared prompt builder so the exact instructions are reviewable in one place."""
    return [
        {
            "role": "system",
            "content": (
                "You extract structured candidate data from resume text. Return ONLY JSON "
                "matching the provided schema. Never invent employers, dates, titles, skills, "
                "or metrics that are not present in the source text. If a field is not present, "
                "omit it or use null rather than guessing."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Schema:\n{json.dumps(schema, indent=2)}\n\n"
                f"Resume text:\n---\n{resume_text}\n---"
            ),
        },
    ]
