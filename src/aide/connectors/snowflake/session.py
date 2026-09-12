"""Blocking Snowflake session. Runs on a thread boundary from async handlers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)
from pydantic import SecretStr

from aide.connectors.snowflake.config import SnowflakeSettings
from aide.connectors.snowflake.errors import SnowflakeMappedError, raise_mapped
from aide.domain.failures import FailureClass
from aide.secrets.resolvers import UnresolvedSecretError

try:
    import snowflake.connector
    from snowflake.connector import DictCursor
except ImportError:  # pragma: no cover - dependency is required; kept for typed import
    snowflake = None  # type: ignore[assignment]
    DictCursor = None  # type: ignore[misc, assignment]


def _pem_bytes(raw: str) -> bytes:
    text = raw.strip()
    if "\\n" in text and "BEGIN" in text:
        text = text.replace("\\n", "\n")
    return text.encode("utf-8")


def private_key_der(pem: SecretStr, passphrase: SecretStr | None) -> bytes:
    try:
        password = passphrase.get_secret_value().encode("utf-8") if passphrase is not None else None
        key = load_pem_private_key(_pem_bytes(pem.get_secret_value()), password=password)
        return key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    except SnowflakeMappedError:
        raise
    except Exception as exc:
        raise SnowflakeMappedError(
            FailureClass.CONNECTOR_FAILURE,
            "Snowflake private key could not be loaded",
        ) from exc


class SnowflakeSession:
    """Synchronous vendor session. Call only from a worker thread."""

    def __init__(
        self,
        settings: SnowflakeSettings,
        *,
        account: SecretStr,
        user: SecretStr,
        private_key: SecretStr,
        warehouse: SecretStr,
        passphrase: SecretStr | None,
        query_tag: str,
        timeout_seconds: int,
    ) -> None:
        if snowflake is None:
            raise SnowflakeMappedError(
                FailureClass.CONNECTOR_FAILURE,
                "snowflake-connector-python is not installed",
            )
        self._settings = settings
        try:
            key = private_key_der(private_key, passphrase)
            self._connection = snowflake.connector.connect(
                account=account.get_secret_value(),
                user=user.get_secret_value(),
                private_key=key,
                warehouse=warehouse.get_secret_value(),
                role=settings.role,
                database=settings.database,
                autocommit=True,
                client_session_keep_alive=False,
                session_parameters={
                    "QUERY_TAG": query_tag,
                    "STATEMENT_TIMEOUT_IN_SECONDS": timeout_seconds,
                    "AUTOCOMMIT": True,
                },
            )
        except UnresolvedSecretError as exc:
            raise SnowflakeMappedError(
                FailureClass.CONNECTOR_FAILURE,
                f"SECRET_UNRESOLVED:{exc.args[0] if exc.args else 'UNKNOWN'}",
            ) from exc
        except Exception as exc:
            raise_mapped(exc)
            raise  # pragma: no cover
        self._query_tag = query_tag
        self._timeout_seconds = timeout_seconds

    def close(self) -> None:
        try:
            self._connection.close()
        except Exception:
            return

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | dict[str, Any] | None = None,
    ) -> tuple[tuple[str, ...], list[dict[str, Any]], str | None]:
        try:
            cursor = self._connection.cursor(DictCursor)
            cursor.execute("ALTER SESSION SET QUERY_TAG = %s", (self._query_tag,))
            cursor.execute(
                "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = %s", (self._timeout_seconds,)
            )
            cursor.execute("ALTER SESSION SET AUTOCOMMIT = TRUE")
            cursor.execute(sql, params)
            query_id = getattr(cursor, "sfqid", None)
            description = cursor.description or []
            columns = tuple(str(item[0]) for item in description)
            rows_raw = cursor.fetchall() if cursor.description is not None else []
            rows: list[dict[str, Any]] = []
            for row in rows_raw:
                if isinstance(row, dict):
                    rows.append({str(key): _jsonable(value) for key, value in row.items()})
                else:
                    rows.append(
                        {columns[index]: _jsonable(value) for index, value in enumerate(row)}
                    )
            return columns, rows, str(query_id) if query_id else None
        except Exception as exc:
            raise_mapped(exc)
            raise  # pragma: no cover


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value
