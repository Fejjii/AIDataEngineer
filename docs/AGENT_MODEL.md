# Agent Model

**Task:** DE 001 · **Status:** ACCEPTED · ADR: DE-ADR-010

## 1. Starting position

One orchestrator (deterministic). One planning capability (LLM). Typed workflow state.
Reusable typed capabilities. Controlled tool execution. Deterministic validation.

No specialist *agents*. Instead, **reasoning capabilities**: LLM-backed functions with a
role-specific prompt, a bounded context assembly, a typed output schema, and deterministic
validators. They cannot call tools, cannot loop, cannot talk to each other, and cannot
change workflow state. The orchestrator decides when they run and what happens with their
output.

```text
Orchestrator (Det) ──schedules──► Task(capability) ──► Tool Registry
                                                        ├─ deterministic handler (connector)
                                                        └─ reasoner (LLM Gateway + prompt + schema + validators)
```

## 2. Why not a multi-agent architecture

| Multi-agent property | Cost here | Our substitute |
|---|---|---|
| Agents choose their own tools | Policy must be re-derived per agent; blast radius grows | Planner proposes tasks; policy evaluates each; tools are bound by capability, not by agent |
| Agents converse to coordinate | Integration state lives in text; non-replayable; injection surface | Typed artifacts and persisted tasks |
| Agents loop until satisfied | Unbounded cost and time; hidden retries | Orchestrator owns all loops with explicit budgets |
| "Specialist" persona quality | Claimed but rarely measured | Role prompts + context assembly per reasoning capability give the same specialisation without autonomy |
| Demo theatre | Impressive but unauditable | Audit timeline of typed steps is the demo |

## 3. Reasoning capabilities (V1)

Each has: prompt template (versioned file), context assembler (Det), output schema
(Pydantic), validators (Det), fallback (Det), model config (settings).

| Capability | Role prompt | Context received (all redacted, delimited) | Output contract | Validation | Fallback |
|---|---|---|---|---|---|
| `interpret_requirement` | Senior analytics engineer clarifying requirements | request text, prior Q&A, glossary | `RequirementSpec` | schema; Det ambiguity rules | clarification / BLOCKED |
| `plan_phase` | Data platform lead sequencing work | requirement, phase, prior summaries, phase contract snapshot, registered connector versions, server-authorized grants | `Plan` | structural DAG/version/schema/permission bounds; temporary connector health excluded | replan ×2 → BLOCKED |
| `select_relevant_assets` | Data discovery specialist | requirement, catalogue (names, comments, columns, row counts) | `AssetSelection` | subset check | retry → BLOCKED with question |
| `propose_model_design` | Data architect constrained by `ArchitectureDecision` | requirement, decision, selected assets metadata, profiles, relationships, masked samples | `ModelDesign` | grain provability, column existence, SCD tracking | clarification / BLOCKED |
| `generate_transformation` | Analytics engineer writing dbt for Snowflake | one design unit, upstream metadata, conventions, dialect notes, prior validation feedback | file set | `classify_sql`, ref/source resolution, YAML-column existence, compile, EXPLAIN | regenerate with feedback ×2 → REPAIR/BLOCKED |
| `generate_sql_query` | Analytics engineer writing one safe query | requirement, selected assets metadata, optional DEV target, prior feedback | single `SqlText` + expected columns | `classify_sql` (single statement; read-only or one DEV write), scope check, EXPLAIN | regenerate ×2 → BLOCKED |
| `diagnose_failure` | Senior engineer doing root-cause analysis | evidence bundle, artifact under repair, drift report, forbidden hypotheses | `RepairProposal` | hypothesis novelty, repairable class, patch scope, SQL validation | second proposal → BLOCKED |
| `generate_documentation` | Technical writer for data products | design, profiles, lineage, validation report | markdown docs | referenced ids exist; size | skip docs, flag |
| `summarize_for_human` | Explainer for engineer/business/approver | persisted state refs | markdown | references only persisted ids | Det template summary |

Context assembly rule: every reasoning capability receives **summaries and ids** by
default; raw artifacts are included only when the assembler explicitly allow-lists them
(e.g., failing SQL for diagnosis). Untrusted text (comments, sample values, error messages)
is wrapped in delimiters and labelled as data.

## 4. Evaluation of candidate specialists

For each candidate from the brief: is a capability alone insufficient?

| Candidate | Verdict | Reasoning |
|---|---|---|
| **Discovery Agent** | **Not retained** | Enumeration is deterministic. It completes a phase run, then a new planning boundary creates explicit sorted description tasks and one selection reasoning step; no runtime DAG insertion. |
| **Data Architect Agent** | **Not retained as agent; retained as capability + Det engine** | The material decision (architecture class) must be a rule table for auditability. The LLM contributes entity mapping and design detail inside the class. That is one capability with a strong validator, not an autonomous agent. |
| **SQL Agent** | **Not retained** | SQL generation is per-unit; validation is deterministic (classify, compile, explain). Iteration is owned by the orchestrator's regenerate/repair loops. |
| **Pipeline Engineering Agent** | **Not retained** | dbt project assembly is templated; ordering comes from the design. No autonomy needed. |
| **Quality Agent** | **Not retained** | Quality is *entirely* deterministic in V1. The only LLM contribution (business assertions) is a small output of `propose_model_design`. |
| **Optimization Agent** | **Not retained (V1)** | V1 only collects metrics and emits recommendations from Det rules (e.g., spilled bytes > 0 → clustering hint). A reasoning capability `propose_optimizations` may be added in V2 with the same contract discipline. |
| **Deployment Agent** | **Not retained** | Delivery is a fixed deterministic chain with a human gate. Autonomy is the opposite of what is wanted. |
| **Monitoring Agent** | **Not retained (V1)** | Monitors are definitions checked deterministically. Incident diagnosis (V3) would reuse `diagnose_failure`. |
| **Analyst Agent** | **Out of scope** | Product extension, not part of the data engineering control plane. |

**Conclusion:** zero specialist agents in V1. Nine reasoning capabilities. One orchestrator.

## 5. When a specialist would be justified

Add a specialist reasoning *component* (still not autonomous) only when **all** hold:

1. It needs a multi-step reasoning loop that cannot be expressed as orchestrator-owned
   regenerate/repair iterations (e.g., interactive exploration with intermediate tool results).
2. It needs a distinct tool subset and permission scope that should be isolated from the
   planner (e.g., production incident triage with read-only production identity).
3. Its output can still be validated deterministically before any effect.
4. Its cost can be bounded by explicit step and token budgets.

If accepted, it is implemented as a **sub-workflow** (its own phase template and tasks),
not as a free-running agent, so the same state machine, policy and audit apply.

## 6. Orchestrator responsibilities (Det)

- Drive transitions per `docs/STATE_MODEL.md` §3.
- Decide planner vs. template per phase (§4.5 there).
- Own every loop: clarification rounds, replans, regeneration, repairs, retries — each with a persisted counter.
- Resolve `$from` placeholders in task inputs from prior task outputs.
- Evaluate phase exit criteria from persisted outputs, never from LLM text.
- Emit audit events and workflow events.

## 7. Planner responsibilities (LLM, constrained)

- Sees: requirement, phase, prior phase *summaries*, catalogue (ids, purposes, permissions, input fields), connectors (ids, kinds, capabilities, status), constraints.
- Does not see: secrets, connector configuration, raw data, prompts of other capabilities.
- May: choose capabilities and connectors, set inputs, set dependencies, propose rationale.
- May not: invent capabilities, exceed granted permissions, create cross-phase dependencies, exceed `max_tasks`, lower validators, change timeouts upward.

## 8. LLM Gateway responsibilities (Det)

- Prompt templates as versioned files (`src/aide/prompts/<capability>/<version>.md`), rendered with a strict template engine (no arbitrary code); template id and version recorded on every model call.
- Structured output via JSON schema derived from the Pydantic output model; parse → validate → return object or `OUTPUT_INVALID`.
- Redaction pass on inputs (secret patterns, sensitive column masks), token budget check, per-workflow cost accounting.
- Provider adapter selection by config; deterministic fake provider (`replay` mode from recorded fixtures) for tests and offline demo.
- Model, temperature, max tokens, timeout configurable per capability.

## 9. Prompt-injection posture

- Metadata, comments, sample values, error messages, dbt logs and PR text are **data**.
- Reasoning outputs are proposals. Nothing an LLM emits executes without `classify_sql`,
  schema validation, policy and (where applicable) approval.
- Reasoning capabilities have `READ` permission and no connector; they physically cannot
  act.
- Suspected injection patterns in untrusted text (imperative phrases aimed at "the
  assistant", role-switch attempts) raise a `SUSPECTED_INJECTION` audit event and mark the
  source asset for human review; they do not stop the workflow by themselves.
