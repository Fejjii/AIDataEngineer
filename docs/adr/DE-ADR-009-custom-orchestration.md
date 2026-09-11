# DE-ADR-009 — Custom deterministic orchestration; no agent framework

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001

## Context
Control flow must be explicit, auditable, resumable, bounded, and testable. Previous
projects used LangGraph/LangChain; the engineering delta requires independent evaluation.

## Decision
Implement the orchestrator in plain Python: a transition table (data), phase controller,
phase templates, planner-validation, and a worker loop over PostgreSQL. No LangGraph,
LangChain, CrewAI, AutoGen, or Semantic Kernel in the control path.

## Alternatives
- **LangGraph**: rejected — the graph and its state semantics *are* the product's core
  and must be owned; hidden checkpointing semantics complicate audit; version churn.
- **Temporal**: strong durability model; rejected for V1 because it adds a server and
  SDK and our durability needs are met by PostgreSQL leases and idempotency. Documented
  re-evaluation trigger: multi-node workers or long-running (days) workflows.
- **Airflow/Prefect/Dagster**: batch schedulers, not interactive control planes;
  candidates as *connectors* (orchestration kind), not as the core.

## Consequences
- ~1–2k LOC of orchestration code with property tests; explicit budgets for every loop.
- Framework utilities (e.g., a provider SDK helper) may still be used at the edges by ADR.
