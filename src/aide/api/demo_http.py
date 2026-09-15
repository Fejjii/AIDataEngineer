"""HTTP synthetic demo enablement. Fail closed without a token."""

from __future__ import annotations

TRUE_FLAGS = frozenset({"1", "true", "yes", "on"})


class HttpDemoMisconfiguredError(RuntimeError):
    """HTTP demo is enabled without a required authentication token."""


def env_flag_enabled(raw: str | None) -> bool:
    """Return True when an environment flag is an explicit truthy value."""
    return (raw or "").strip().lower() in TRUE_FLAGS


def parse_demo_token(raw: str | None) -> str | None:
    """Return a nonempty stripped token, or None when absent."""
    value = (raw or "").strip()
    return value or None


def resolve_http_demo(*, http_enabled: bool, token: str | None) -> str | None:
    """Return the token when the HTTP demo may be mounted.

    Disabled HTTP demo returns None. CLI demo is unaffected.
    Enabled HTTP demo without a nonempty token fails closed.
    """
    token = parse_demo_token(token)
    if not http_enabled:
        return None
    if token is None:
        raise HttpDemoMisconfiguredError(
            "AIDE_SYNTHETIC_DEMO_TOKEN is required when AIDE_SYNTHETIC_DEMO_HTTP is enabled"
        )
    return token
