"""dbt transformation connector. Real subprocess runner plus deterministic fake."""

from aide.connectors.dbt.config import (
    SNOWFLAKE_DBT_SECRET_NAMES,
    DbtAdapter,
    DbtSettings,
    duckdb_dbt_settings,
    missing_secret_names,
    snowflake_dbt_settings,
)
from aide.connectors.dbt.errors import (
    DbtMappedError,
    DbtProcessTerminatedError,
    DbtTimeoutError,
    map_error,
)
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.namespace import snowflake_workflow_schema, workflow_short_id
from aide.connectors.dbt.real import RealDbtConnector, build_real_duckdb
from aide.connectors.dbt.specs import DBT_DEV, DBT_REQUIRED_PERMISSIONS, FAKE_DBT_DEV

__all__ = [
    "DBT_DEV",
    "DBT_REQUIRED_PERMISSIONS",
    "FAKE_DBT_DEV",
    "DbtAdapter",
    "DbtMappedError",
    "DbtProcessTerminatedError",
    "DbtSettings",
    "DbtTimeoutError",
    "FakeDbtConnector",
    "RealDbtConnector",
    "SNOWFLAKE_DBT_SECRET_NAMES",
    "build_real_duckdb",
    "duckdb_dbt_settings",
    "map_error",
    "missing_secret_names",
    "snowflake_dbt_settings",
    "snowflake_workflow_schema",
    "workflow_short_id",
]
