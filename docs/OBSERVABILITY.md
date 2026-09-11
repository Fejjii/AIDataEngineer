# Observability

**Task:** DE 001 (hardened by DE 001R2A) · **Status:** PROPOSED · ADR: DE-ADR-018

Three streams, one correlation model:

| Stream | Purpose | Store | Retention |
|---|---|---|---|
| **Audit** | Consequential actions, human-facing timeline, compliance | `audit_events` (PostgreSQL, append-only) | long |
| **Telemetry** | Model calls, tool calls, metrics, cost | `model_calls`, `tool_calls`, `workflow_metrics` (PostgreSQL) + OpenTelemetry spans (optional OTLP export) | medium |
| **Debug logs** | Structured JSON logs for engineers | stdout → file/collector | short |

Correlation ids on everything: `workflow_id`, `phase_run_id`, `task_id`,
`operation_idempotency_key`, `resolved_input_digest`, `attempt_id`, `claim_epoch`, `phase`,
capability/input/output schema versions, connector id/version, `trace_id`, `span_id`, `request_id`,
`session_id` (human session), `evaluation_run_id` (when under evaluation).

---

## 1. What is captured

| Domain | Fields |
|---|---|
| Workflow | id, trusted creator principal, grant authorization, state/cancellation epoch/history, outcome, counters, versioned budget ledger/reservations |
| Task | template/phase-run occurrence, materialization digest, operation key, pinned contract versions, status history, max/consumed attempts, owner/claim epoch/heartbeats, reconciliation, all policy reasons and approval subject ids |
| State transitions | workflow_events with sequence number |
| User request | redacted text artifact, length, language, submitted_by |
| Clarifications | questions, options, answers, round, latency-to-answer |
| Plan | plan artifact id, task count, capabilities used, validation result, replan count |
| Model calls | `model_call_id`, task, capability, template id + version, provider, model, temperature, input tokens, output tokens, cached tokens (if provider reports), latency ms, cost (from provider-reported usage × configured price table), status, parse/validation result, retry index, redacted prompt artifact ref, redacted completion artifact ref |
| Capabilities / tool calls | `tool_call_id`, task, capability@version, connector, environment, policy decision, start/end, duration ms, input digest + redacted excerpt, output digest + redacted excerpt, status, failure class, retry index, resource metrics (rows, bytes, query id) |
| Connector | status history (AVAILABLE/DEGRADED/UNAVAILABLE/MOCK), health latency, error counts by class, rate-limit events |
| Execution latency | per task, per phase, per workflow; queue wait vs run time |
| SQL | every executed/validated statement as artifact with classification, query id, query tag, duration, bytes scanned, rows |
| Generated artifacts | type, version, size, sha256, producer task, validation status |
| Validation | `ValidationReport` per attempt; pass/fail/warn counts; regressions |
| Failures | class, source, message (redacted), evidence refs |
| Retries | count, reason class, backoff |
| Repairs | attempt id, failing task, evidence ref, proposal ref, hypothesis hash, validation outcome, accepted/rejected, cost of the repair (tokens + warehouse) |
| Approvals | typed subject/digest, requested/decided timestamps, trusted approver principal, expiry, invalidation/rejection route, wait time |
| Warehouse metrics | per query: duration, bytes scanned, partitions scanned/total, spilled bytes, warehouse size; per workflow: credits (from `WAREHOUSE_METERING_HISTORY` filtered by query tag where possible, else estimated from duration × warehouse rate) |
| Infrastructure cost | LLM cost (exact from usage), warehouse cost (measured or estimated with `estimated=true`), CI minutes (not tracked in V1) |
| Final outcome | `WorkflowSummary`: outcome enum, success flags, first-attempt success, totals of the above |

---

## 2. Model call accounting

- Prefer provider-reported usage; if absent, count with the provider's official tokenizer;
  never estimate from characters.
- Price table in configuration keyed by `(provider, model)`, versioned by date; every
  `model_calls` row stores the price-table version so historical cost is reproducible.
- Before dispatch, the gateway locks the versioned workflow budget row and reserves
  deterministic worst-case cost in the same transaction. Completion settles actual cost
  and releases the remainder. Concurrent calls cannot pass a stale total.
- Reservation above cap creates no provider attempt and requests a
  `BudgetIncreaseApproval` with explicit prior/new cap, delta, unit, scope and ledger
  version. Approval atomically updates the cap before re-evaluation.
- Prompt and completion are stored as **redacted artifacts** (not in the telemetry row) with
  configurable retention; the UI can show them for debugging.
- Cache behaviour: request fingerprint = `(template_id, template_version, model,
  temperature, sha256(rendered_prompt), output_schema_version)`; cached tokens recorded when
  the provider reports them; the fake provider uses the fingerprint for replay.

### 2.1 Audit completeness and integrity claim

Every consequential state write and corresponding audit event use one PostgreSQL
transaction. A locked per-workflow counter allocates sequence numbers, protected by unique
`(workflow_id, sequence)`. The runtime writer role has INSERT/SELECT but no UPDATE/DELETE
on audit rows. Retention deletion uses a separate operator-only role and records a deletion
manifest. This is a transactional append-only application audit guarantee, not
cryptographic tamper resistance.

---

## 3. Tracing

- OpenTelemetry SDK; one root span per workflow phase run, child spans per task, per
  policy evaluation, per model call, per connector call, per dbt subprocess.
- Span attributes = the correlation ids above plus capability/connector/status/failure class.
- Exporter: console/none by default; OTLP endpoint via configuration (e.g., a local
  Jaeger/Tempo container) — optional, not required to run the product.
- Trace ids are stored on `tool_calls` and `model_calls` so the UI can deep-link.

---

## 4. Logging

- `structlog` JSON to stdout; keys: timestamp, level, event, correlation ids, component.
- Redaction processor before rendering (see `docs/PERMISSION_MODEL.md` §9).
- Levels: `INFO` for lifecycle, `WARNING` for degraded/retry, `ERROR` for failures with
  class; debug payloads only at `DEBUG` and still redacted.
- Never log secrets, full source rows, or full prompts.

---

## 5. Metrics (derived, per workflow and aggregated)

| Metric | Derivation |
|---|---|
| `tasks_total`, `tasks_failed`, `tasks_retried` | tasks |
| `model_calls_total`, `tokens_in`, `tokens_out`, `llm_cost` | model_calls |
| `tool_calls_total` by capability/connector, `tool_latency_p50/p95` | tool_calls |
| `warehouse_credits`, `warehouse_cost_estimated` | warehouse metrics |
| `repairs_attempted`, `repairs_succeeded`, `avg_repairs_per_success` | repair_attempts |
| `human_interventions` (clarifications + approvals + resumes) | events |
| `wait_time_human` vs `machine_time` | timestamps |
| `first_attempt_success` (no repair needed) | validation attempt 1 all pass |
| `validation_pass_rate` | ValidationReport |
| `connector_error_rate` by class | tool_calls |
| `automated_steps`, `manual_steps_eliminated`, `estimated_time_saved_hours` | see `docs/EVALUATION_STRATEGY.md` §4 |

Exposed via `GET /workflows/{id}/metrics` and aggregated in the evaluation report.

---

## 6. UI surfaces

- **Timeline**: audit events + task lifecycle, filterable by phase; click → artifact, policy decision, model call (redacted prompt/completion), tool call details.
- **Cost panel**: LLM cost, warehouse credits/cost (with `estimated` badge), running caps.
- **Connector status**: per instance with reason codes.
- **Validation**: checklist from the latest `ValidationReport` with regressions highlighted.
- **Repairs**: each attempt with evidence, hypothesis, validation delta, accepted/rejected.

---

## 7. Privacy and retention

| Data | Retention default | Notes |
|---|---|---|
| Audit events | indefinite (demo: 1 year) | redacted |
| Telemetry rows | 180 days | |
| Prompt/completion artifacts | 30 days | redacted; configurable to 0 (metadata only) |
| Samples / failing rows | 30 days | masked |
| Debug logs | 14 days | |

Deletion is by workflow id through the separate operator-only maintenance role, records a
deletion manifest, and is never available to the runtime agent/writer role.
