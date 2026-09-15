# AIDataEngineer — Project Context

Keep this file concise. It orients agents. It is not a substitute for architecture.

## Project name

AI Data Engineer (repository: `AIDataEngineer`)

## Product north star

An enterprise-grade AI Data Engineer that converts business intent into governed, tested, and
deployable data workflows across databases, warehouses, transformation tools, cloud platforms,
and Git-based delivery, with human approval for sensitive actions.

It is not a SQL chatbot and not a static code generator. It must plan, discover, act, execute,
test, observe, correct, and escalate.

## Current phase

The DE001 product architecture is **ACCEPTED** and DE002–DE008A foundations are merged.
PIVOT001 records the constrained Interview MVP contract (DE-ADR-028). MVP001–MVP004 are
merged. Compact contract: `.ai/ARCHITECTURE.md`; active boundary:
`docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md`. Recruiter landing page: `README.md`. Interview
demo: `docs/INTERVIEW_DEMO.md`.

## Initial intended stack (direction only, not a freeze)

- Snowflake as the first warehouse
- dbt for transformation, tests, and documentation
- Python for orchestration and connectors
- GitHub for version control and pull requests
- A simple web interface for prompt, plan, actions, approvals, and results
- Observability for traces, tool calls, errors, costs, and evaluations

Exact orchestration framework, service layout, and data model are deferred to DE 001.

## Data Engineering automation objective

Receive a natural-language requirement, inspect connected systems, generate and execute work,
validate results, self-correct failures, and prepare safe deployment actions with auditability.

## Current MVP direction

The current MVP is one Vantara customer-revenue closed loop. MVP001–MVP004 are merged:
Digital Twin, Supervisor and Governed Tool Gateway, bounded repair and Independent
Verifier, deterministic benchmark, evidence completeness gate, interview demo CLI, and
credential-gated Snowflake live smoke.

GitHub delivery, frontend, monitoring, additional vendors/use cases/repair classes, graph
or agent frameworks, enterprise IAM, and production or staging actions are deferred.

## Development operating philosophy

- Repository and verified evidence beat chat history.
- Lowest-cost model with a high probability of success; escalate for complexity, ambiguity,
  blast radius, security, architecture, or repeated failure.
- One writer per branch. Parallel work only with isolated tasks and explicit file ownership.
- Private AI context stays local. Cloud work uses tracked GitHub state only.
- Human gates for merge, secrets, production data, and deployment.

## Known source documents

Private bootstrap sources (ignored, not committed) informed this operating system:

- AI Data Engineer Agentic Platform project handoff
- AlphaTrade AI development operating protocol (workflow mechanisms only)
- OnePilot AI development operating protocol (workflow mechanisms only)
- AI Software Factory model routing protocol

Do not copy AlphaTrade or OnePilot product behavior into this repository.
