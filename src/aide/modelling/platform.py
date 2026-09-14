"""Deterministic platform capability lookup from vendor metadata. Never guesses."""

from __future__ import annotations

from aide.capabilities.io import PlatformCapabilities

SNOWFLAKE_CAPABILITIES = PlatformCapabilities(
    supports_merge="TRUE",
    supports_clustering="TRUE",
    supports_time_travel="TRUE",
    supports_streams_tasks="TRUE",
    supports_dynamic_tables="TRUE",
)

UNKNOWN_CAPABILITIES = PlatformCapabilities()


def platform_capabilities_for(
    *,
    vendor: str | None = None,
    dialect: str | None = None,
    platform_type: str | None = None,
) -> PlatformCapabilities:
    tokens = {
        (vendor or "").strip().lower(),
        (dialect or "").strip().lower(),
        (platform_type or "").strip().lower(),
    }
    if "snowflake" in tokens:
        return SNOWFLAKE_CAPABILITIES
    return UNKNOWN_CAPABILITIES
