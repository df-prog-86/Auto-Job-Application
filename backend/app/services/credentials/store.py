"""
OS credential store access (spec §45): Python `keyring` talks to Windows
Credential Manager / macOS Keychain / Linux Secret Service depending on
platform. This module is the *only* place that touches `keyring` directly —
everything else (LLM client, ATS account login) goes through
`resolve_secret`/`store_secret` so credential access stays auditable to one
file.

Nothing here ever logs a secret value. Callers must not either.
"""

from __future__ import annotations

SERVICE_NAME = "job-agent"


def store_secret(reference: str, value: str) -> None:
    import keyring

    keyring.set_password(SERVICE_NAME, reference, value)


def resolve_secret(reference: str) -> str:
    import keyring

    value = keyring.get_password(SERVICE_NAME, reference)
    if value is None:
        raise KeyError(f"No credential stored under reference {reference!r}")
    return value


def delete_secret(reference: str) -> None:
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(SERVICE_NAME, reference)
    except PasswordDeleteError:
        pass  # already absent; deletion is idempotent from the caller's perspective
