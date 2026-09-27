from __future__ import annotations


class LLMError(Exception):
    """Base class for all model-router failures."""


class LLMNotConfiguredError(LLMError):
    """
    Raised when a required model role has no model identifier configured
    (settings.PRIMARY_FAST_MODEL etc. is None) or no API base/key is set.
    Callers must handle this by falling back to a manual/Needs-Attention
    path (spec §76: "the system must remain functional if the primary
    model becomes unavailable") — never by silently skipping validation.
    """


class StructuredOutputError(LLMError):
    """
    Raised when structured output could not be produced within the
    configured retry-then-fallback budget (spec §11: at most two structured
    retries before escalating to the fallback model).
    """

    def __init__(self, message: str, attempts: list[str]):
        super().__init__(message)
        self.attempts = attempts
