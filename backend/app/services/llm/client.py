"""
Thin async client for an OpenAI-compatible chat-completions API. No
provider is configured yet (see app/config.py — LLM_API_BASE_URL /
LLM_API_KEY_REF are both None by default); this module is written so that
plugging one in later is a config change, not a rewrite.

Per spec §7, "production code must verify provider capabilities rather than
assume them" — the strict JSON-schema structured-output request format
below is the widely-supported OpenAI-compatible shape, but a provider that
doesn't support it should be reflected in a per-provider capability flag
once one is actually configured, not assumed to always work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.services.llm.exceptions import LLMNotConfiguredError


@dataclass
class ChatCompletionResult:
    content: str
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]


class LLMClient:
    def __init__(self) -> None:
        self._base_url = settings.LLM_API_BASE_URL
        self._api_key_ref = settings.LLM_API_KEY_REF

    def _require_configured(self) -> tuple[str, str]:
        if not self._base_url or not self._api_key_ref:
            raise LLMNotConfiguredError(
                "No LLM provider configured (LLM_API_BASE_URL / LLM_API_KEY_REF unset)."
            )
        # Resolved via the credentials service (keyring), never logged or
        # persisted in plaintext — see app/services/credentials/.
        from app.services.credentials.store import resolve_secret

        api_key = resolve_secret(self._api_key_ref)
        return self._base_url, api_key

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        extra: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> ChatCompletionResult:
        base_url, api_key = self._require_configured()

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if extra:
            payload.update(extra)  # provider options such as OpenRouter's {"plugins": [{"id": "web"}]}
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_response", "strict": True, "schema": json_schema},
            }

        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            resp = await client.post(
                "/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return ChatCompletionResult(
            content=choice,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )
