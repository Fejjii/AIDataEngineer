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

Development operating system installed (DE 000). Product architecture is **DESIGNED —
PROPOSED** (DE 001 + DE 001R1 + DE 001R2A + DE 001R2B on
`docs/DE001_mvp_architecture`). Independent GPT 5.6 Sol High review and Fable R2V
verification residuals are closed at the document level. Operator acceptance remains
required before DE 002A. Compact contract:
`.ai/ARCHITECTURE.md`; full set: `docs/ARCHITECTURE.md` and companions.

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

One strong end-to-end workflow first: discover source tables, propose a model, generate dbt/SQL,
run in development, add tests, repair at least one failure, prepare a pull request, and require
human approval for production actions. Do not start with every cloud connector or a large UI.

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
