"""Snowflake connector package: real + fake, same handler set."""

from aide.connectors.snowflake.config import (
    REQUIRED_SECRET_NAMES,
    FakeSnowflakeSettings,
    SnowflakeSettings,
    missing_secret_names,
    settings_for_identity,
    snowflake_credentials_available,
)
from aide.connectors.snowflake.errors import FakeSnowflakeError, SnowflakeMappedError, map_error
from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.connectors.snowflake.namespace import workflow_short_id
from aide.connectors.snowflake.query_tags import (
    QueryTag,
    format_query_tag,
    parse_query_tag,
    query_tag_from_context,
)
from aide.connectors.snowflake.real import RealSnowflakeConnector, build_real_pair
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO

__all__ = [
    "FAKE_SNOWFLAKE_DEV",
    "FAKE_SNOWFLAKE_RO",
    "FakeSnowflakeConnector",
    "FakeSnowflakeError",
    "FakeSnowflakeSettings",
    "QueryTag",
    "REQUIRED_SECRET_NAMES",
    "RealSnowflakeConnector",
    "SnowflakeMappedError",
    "SnowflakeSettings",
    "build_fake_pair",
    "build_real_pair",
    "format_query_tag",
    "map_error",
    "missing_secret_names",
    "parse_query_tag",
    "query_tag_from_context",
    "settings_for_identity",
    "snowflake_credentials_available",
    "workflow_short_id",
]
