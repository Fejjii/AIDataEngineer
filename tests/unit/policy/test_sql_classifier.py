from __future__ import annotations

from aide.domain.sql import SqlText
from aide.policy.sql.classifier import classify_sql
from aide.policy.sql.dialects import DialectId, registered_dialects


def _sf(text: str) -> SqlText:
    return SqlText(dialect=DialectId.SNOWFLAKE.value, text=text)


def test_dialects_are_extensible() -> None:
    assert "snowflake" in registered_dialects()
    assert "postgres" in registered_dialects()
    unknown = classify_sql(SqlText(dialect="not_a_real_dialect", text="SELECT 1"))
    assert unknown.parse_ok is False
    assert unknown.is_destructive is True
    assert unknown.is_read_only is False


def test_snowflake_round_trip_and_safe_select() -> None:
    result = classify_sql(
        _sf('SELECT COUNT(*) AS c FROM RAW.SALES.ORDERS WHERE "orderId" IS NOT NULL')
    )
    assert result.parse_ok is True
    assert result.is_read_only is True
    assert result.is_destructive is False
    assert result.normalized_sql
    addresses = {asset.address for asset in result.objects_read}
    assert any(
        part == "ORDERS" or part == "orders" or "ORDERS" in part
        for addr in addresses
        for part in addr
    )


def test_sql_adversarial_cases_fail_closed() -> None:
    cases = [
        "DROP TABLE RAW.SALES.ORDERS",
        "DELETE FROM RAW.SALES.ORDERS",
        "INSERT INTO RAW.SALES.ORDERS SELECT * FROM RAW.SALES.ORDERS",
        "UPDATE RAW.SALES.ORDERS SET X = 1",
        (
            "MERGE INTO RAW.SALES.ORDERS t USING RAW.SALES.ORDERS s "
            "ON t.ID = s.ID WHEN MATCHED THEN UPDATE SET t.X = 1"
        ),
        "GRANT SELECT ON RAW.SALES.ORDERS TO ROLE PUBLIC",
        "ALTER SESSION SET QUERY_TAG = 'x'",
        "USE ROLE ACCOUNTADMIN",
        "EXECUTE IMMEDIATE 'SELECT 1'",
        "SELECT * FROM @RAW.STAGE/data.csv",
        "SELECT SYSTEM$ABORT_SESSION(1)",
        "SELECT 1; DROP TABLE RAW.SALES.ORDERS",
        "CREATE USER evil PASSWORD = 'x'",
        "COPY INTO RAW.SALES.ORDERS FROM @RAW.STAGE",
        "SELECT unknown_udf_xyz(col) FROM RAW.SALES.ORDERS",
    ]
    for sql in cases:
        result = classify_sql(_sf(sql))
        assert result.is_read_only is False, sql
        assert (
            result.parse_ok is False
            or result.is_destructive
            or result.unsafe_constructs
            or result.stages_or_urls
            or result.is_multi_statement
            or result.has_dynamic_sql
            or result.unknown_ast_nodes
            or result.objects_written
        ), sql


def test_unparseable_is_destructive() -> None:
    result = classify_sql(_sf("SELCT $$$ NOT SQL"))
    assert result.parse_ok is False
    assert result.is_read_only is False
    assert result.is_destructive is True
