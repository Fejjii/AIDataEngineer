"""Identity, allow-list, and deadline enforcement shared by fake and real connectors."""

from __future__ import annotations

from datetime import UTC, datetime

from aide.capabilities.io import DiscoveryScope
from aide.connectors.base.context import CallContext
from aide.connectors.base.spec import ConnectorSpec, IdentityClass, ObjectAllowList
from aide.connectors.snowflake.dialect import normalize_address, normalize_identifier
from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.connectors.snowflake.query_tags import format_query_tag, parse_query_tag
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef


def require_identity(spec: ConnectorSpec, required: IdentityClass) -> None:
    if spec.identity_class is not required:
        raise SnowflakeMappedError(
            FailureClass.PERMISSION_FAILURE,
            (
                f"{spec.connector_id} identity_class={spec.identity_class.value} "
                f"cannot satisfy {required.value}"
            ),
        )


def require_read_identity(spec: ConnectorSpec) -> None:
    require_identity(spec, IdentityClass.READ_ONLY)


def require_write_identity(spec: ConnectorSpec) -> None:
    require_identity(spec, IdentityClass.DEVELOPMENT)


def normalized_asset(asset: AssetRef) -> AssetRef:
    return AssetRef(
        connector_id=asset.connector_id,
        address=normalize_address(asset.address),
        kind=asset.kind,
        platform_type=asset.platform_type or "snowflake",
    )


def allow_list_contains(allow_list: ObjectAllowList, asset: AssetRef) -> bool:
    return allow_list.contains_asset(normalized_asset(asset))


def require_asset_allowed(spec: ConnectorSpec, asset: AssetRef) -> AssetRef:
    normalized = normalized_asset(asset)
    if not spec.allow_list.contains_asset(normalized):
        raise SnowflakeMappedError(
            FailureClass.PERMISSION_FAILURE,
            "asset is outside the connector allow-list",
        )
    return normalized


def require_scope_allowed(spec: ConnectorSpec, scope: DiscoveryScope) -> None:
    allowed_databases = {normalize_identifier(item) for item in spec.allow_list.databases}
    if not allowed_databases:
        raise SnowflakeMappedError(
            FailureClass.PERMISSION_FAILURE,
            "connector allow-list has no databases",
        )
    for database in scope.databases:
        if normalize_identifier(database) not in allowed_databases:
            raise SnowflakeMappedError(
                FailureClass.PERMISSION_FAILURE,
                "discovery scope is outside the connector allow-list",
            )
    if scope.schemas is None:
        return
    allowed_schemas = {
        (normalize_identifier(db), normalize_identifier(schema))
        for db, schema in spec.allow_list.schemas
    }
    if not allowed_schemas:
        return
    for schema in scope.schemas:
        matches = {(db, sch) for db, sch in allowed_schemas if sch == normalize_identifier(schema)}
        if not matches:
            raise SnowflakeMappedError(
                FailureClass.PERMISSION_FAILURE,
                "discovery schema is outside the connector allow-list",
            )


def compatible_now(deadline: datetime) -> datetime:
    if deadline.tzinfo is None:
        return datetime.now(UTC).replace(tzinfo=None)
    return datetime.now(deadline.tzinfo)


def statement_timeout_seconds(context: CallContext, *, now: datetime | None = None) -> int:
    current = now or compatible_now(context.deadline)
    remaining = (context.deadline - current).total_seconds()
    if remaining <= 0:
        raise SnowflakeMappedError(FailureClass.TIMEOUT, "task deadline has passed")
    return max(1, int(remaining))


def canonical_query_tag(context: CallContext) -> str:
    tag = format_query_tag(context)
    parse_query_tag(tag)
    return tag


def asset_from_address(
    connector_id: str, address: tuple[str, ...], *, kind: AssetKind = AssetKind.TABLE
) -> AssetRef:
    return AssetRef(
        connector_id=connector_id,
        address=normalize_address(address),
        kind=kind,
        platform_type="snowflake",
    )
