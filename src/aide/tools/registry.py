"""Tool registry: validate → policy → execute → validate → audit."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import ConnectorSpec
from aide.domain.artifacts import ArtifactProvenance
from aide.domain.principal import GrantAuthorization, PrincipalRef
from aide.domain.sql import SqlClassification
from aide.policy.engine import PolicyEngine
from aide.policy.request import PolicyDecision, PolicyRequest

Handler = Callable[[BaseModel, dict[str, Any]], Awaitable[BaseModel]]


class PolicyParked(RuntimeError):
    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__("policy parked the operation")
        self.decision = decision


class PolicyDenied(RuntimeError):
    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__("policy denied the operation")
        self.decision = decision


class OutputInvalid(ValueError):
    pass


class ToolRegistry:
    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry,
        connectors: ConnectorRegistry,
        policy: PolicyEngine | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._connectors = connectors
        self._policy = policy or PolicyEngine()
        self._handlers: dict[str, Handler] = {}

    def register(self, capability_id: str, handler: Handler) -> None:
        self._handlers[capability_id] = handler

    async def invoke(
        self,
        session: AsyncSession,
        *,
        capability_id: str,
        payload: dict[str, Any] | BaseModel,
        context: dict[str, Any],
        principal: PrincipalRef,
        authorization: GrantAuthorization,
        connector_id: str | None,
        connector_health: ConnectorHealthSnapshot | None,
        sql_classification: SqlClassification | None = None,
        provenance: tuple[ArtifactProvenance, ...] = (),
    ) -> tuple[BaseModel, PolicyDecision]:
        spec = self._capabilities.get(capability_id, 1)
        validated_input = (
            payload
            if isinstance(payload, spec.input_schema)
            else spec.input_schema.model_validate(payload)
        )
        connector: ConnectorSpec | None = None
        advertises = True
        registered = True
        if connector_id is not None:
            registered = self._connectors.contains(connector_id)
            if registered:
                connector = self._connectors.get(connector_id)
                advertises = connector.advertises(capability_id, spec.version)
        now = datetime.now(UTC).replace(tzinfo=None)
        request = PolicyRequest(
            workflow_id=context["workflow_id"],
            phase_run_id=context["phase_run_id"],
            task_id=context["task_id"],
            operation_idempotency_key=context["operation_idempotency_key"],
            resolved_input_digest=context["resolved_input_digest"],
            contract_snapshot_id=context["contract_snapshot_id"],
            principal=principal,
            grant_authorization=authorization,
            capability=spec,
            connector=connector,
            connector_health=connector_health,
            target_environment=connector.target_environment if connector is not None else None,
            workflow_grants=authorization.effective,
            payload_classification=sql_classification,
            artifact_provenance=provenance,
            evaluated_at=now,
            approval_expires_at=now + timedelta(hours=1),
            capability_known=True,
            connector_registered=registered,
            connector_advertises_capability=advertises,
        )
        decision = self._policy.evaluate(request)
        if not session.is_active:
            raise RuntimeError("tool invocation requires an active session")
        if decision.routing == "PARK":
            raise PolicyParked(decision)
        if decision.decision != "ALLOW":
            raise PolicyDenied(decision)
        handler = self._handlers[capability_id]
        output = await handler(validated_input, context)
        try:
            validated_output = spec.output_schema.model_validate(
                output.model_dump(mode="json") if isinstance(output, BaseModel) else output
            )
        except ValidationError as exc:
            raise OutputInvalid(str(exc)) from exc
        return validated_output, decision
