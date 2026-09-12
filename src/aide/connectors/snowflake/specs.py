"""Fake Snowflake advertisements (same ids as V1, MOCK provenance)."""

from __future__ import annotations

from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO

FAKE_SNOWFLAKE_RO = SNOWFLAKE_RO.model_copy(update={"is_fake": True})
FAKE_SNOWFLAKE_DEV = SNOWFLAKE_DEV.model_copy(update={"is_fake": True})
