"""Snowflake connector package. DE 002C ships the fake only."""

from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.connectors.snowflake.query_tags import (
    QueryTag,
    format_query_tag,
    parse_query_tag,
    query_tag_from_context,
)
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO

__all__ = [
    "FAKE_SNOWFLAKE_DEV",
    "FAKE_SNOWFLAKE_RO",
    "FakeSnowflakeConnector",
    "QueryTag",
    "build_fake_pair",
    "format_query_tag",
    "parse_query_tag",
    "query_tag_from_context",
]
