"""Safe SQL construct classification. Unknown constructs fail closed."""

from __future__ import annotations

SAFE_STATEMENT_TYPES: frozenset[str] = frozenset(
    {
        "SELECT",
        "WITH",
        "EXPLAIN",
        "DESCRIBE",
        "DESC",
        "SHOW",
    }
)

DESTRUCTIVE_STATEMENT_TYPES: frozenset[str] = frozenset(
    {
        "DELETE",
        "DROP",
        "TRUNCATE",
        "UPDATE",
        "MERGE",
        "INSERT",
        "ALTER",
        "GRANT",
        "REVOKE",
        "UNDROP",
        "REPLACE",
    }
)

WRITE_STATEMENT_TYPES: frozenset[str] = DESTRUCTIVE_STATEMENT_TYPES | frozenset(
    {
        "CREATE",
        "COPY",
        "PUT",
        "GET",
        "CALL",
        "EXECUTE",
    }
)

UNSAFE_CONSTRUCT_MARKERS: frozenset[str] = frozenset(
    {
        "EXECUTE",
        "EXECUTE IMMEDIATE",
        "CALL",
        "USE ROLE",
        "USE SECONDARY ROLES",
        "ALTER SESSION",
        "ALTER USER",
        "ALTER ROLE",
        "ALTER WAREHOUSE",
        "CREATE USER",
        "CREATE ROLE",
        "CREATE STAGE",
        "PUT",
        "GET",
        "LIST",
        "REMOVE",
        "COPY INTO",
    }
)
