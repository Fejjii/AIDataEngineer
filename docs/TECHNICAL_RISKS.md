# Technical Risks

**Task:** DE 001 · **Status:** PROPOSED

Register of risks to the architecture and MVP, with likelihood (L/M/H), impact (L/M/H/C),
mitigation designed into V1, residual risk, and the owner/task where the mitigation lands.

| # | Risk | L | I | Mitigation in design | Residual / detection | Lands in |
|---|---|---|---|---|---|---|
| R1 | **LLM output quality**: generated SQL/dbt frequently invalid or semantically wrong | H | H | Templates for structure; per-unit generation with metadata + profiles; compile + EXPLAIN before execution; deterministic quality checks; bounded regeneration and repair; evaluation harness tracks SQL success and first-attempt success | Semantic errors not caught by tests (wrong join logic producing plausible numbers) → reconciliation checks and human PR review; metric visible in evaluation | DE 007, DE 008, DE 014 |
| R2 | **SQL safety classifier gaps** (dialect quirks, unsafe functions/constructs) | M | C | Snowflake parse/render/reparse equivalence; function/table-function allow-list; deny external/UDF/stage/URL/session/unknown nodes; canonical scope checks; all read capabilities use RO identity; adversarial properties | Safe-list omissions may reject valid SQL (fail closed) | DE 002A, DE 002C, DE 005 |
| R3 | **Prompt injection via metadata/data** | M | H | Untrusted-text delimiting; no tools for reasoning capabilities; all effects gated by Det policy; injection heuristics → audit; S09 scenario | LLM produces misleading design text; caught by human PR review; cannot cause effects | DE 006, DE 010, DE 014 |
| R4 | **Snowflake cost runaway** | M | M | Estimated preflight budgets, statement/query limits, X-Small auto-suspend, canonical tags; explicit budget-increase subject | No hard per-workflow credit cap without isolated warehouse/resource monitor; UI labels estimates | DE 002A, DE 005, DE 014 |
| R5 | **LLM cost runaway** | M | M | Atomic worst-case reservation and settlement under locked versioned ledger; bounded loops; explicit new-cap/delta approval | Reservation can be conservative and park legitimate work | DE 002A, DE 014 |
| R6 | **Repair loop oscillation / same fix repeated** | M | M | Hypothesis hash novelty; max 2/task, 4/workflow; tests-not-weakened validator; escalation to BLOCKED with evidence | Two distinct wrong hypotheses waste budget; acceptable | DE 009 |
| R7 | **dbt / adapter / Python version incompatibility** | M | M | Pin Python 3.12; lock file; subprocess isolation; CI runs fake dbt contract tests and `dbt --version`; re-verify at DE 002 | Upgrade friction later | DE 002, DE 007 |
| R8 | **State corruption, stale workers, duplicate effects** | L | C | Phase-run advisory-lock serialization; immutable materialized operation identity; SKIP LOCKED + renewable lease + monotonic fencing epoch; owner/epoch finalization; atomic recovery ownership; reconcile every ambiguous side effect; bounded `InProgress`; late-result rejection | Unresolved external outcome parks with explicit effect-result-unknown/compensation paths | DE 002B, DE 002C, DE 017 |
| R9 | **Resumability gaps** (orphaned working copies, half-written project files) | M | M | Working copy per workflow rebuilt from artifacts (artifacts are truth, files are cache); reaper on startup | Disk usage; cleanup command | DE 007 |
| R10 | **Fake connectors diverge or MOCK evidence escapes** | H | H | Immutable transitive REAL/MOCK provenance; policy denies real Git/deploy from MOCK ancestry; recreate-and-validate promotion; parity contract tests | Fakes still cannot prove real vendor behaviour | DE 002A, DE 005, DE 008 |
| R11 | **Planner produces invalid, duplicate or unbounded DAGs** | M | M | Structural validation independent of health; immutable phase runs/templates; new planning boundary for fan-out; unique phase/local ids; `max_tasks`; serialized acceptance | Suboptimal but valid plans remain possible | DE 002A, DE 002B |
| R12 | **Modelling rule table too rigid or wrong for edge cases** | M | M | Rules are data with ids; unknown signals → clarification not guess; approval for material classes; rationale shown | Human overrides needed → design approval path; rule evolution via ADR | DE 006 |
| R13 | **Metadata/profiling privacy leakage** (PII in samples reaching LLM or artifacts) | M | H | Column masking heuristics; sample caps; redaction filter; retention limits; secret/PII scan tests over offline run outputs | Heuristics miss a PII column → mitigated by synthetic data in V1; real data needs classification config | DE 005, DE 010 |
| R14 | **Secret leakage** in logs, prompts, artifacts, PRs | L | C | Scoped non-enumerable resolver views only for connector/LLM provider adapters; `SecretRef`/`SecretStr`; redaction and scans | Novel secret formats → entropy heuristic | DE 002A, DE 011 |
| R15 | **GitHub token over-privilege or protected branch push** | L | H | Fine-grained token with minimal scopes; R14 policy rule; never force-push; branch pattern `aide/*` | Misconfigured repo protection → documented setup check in `aide connectors check` | DE 011 |
| R16 | **Demo brittleness** (live LLM variance, cold warehouse, network) | H | M | Offline mode with replay as primary demo path; live mode rehearsed with E4; warehouse pre-warm command; recorded backup video | Live demo still risky → present offline + show live PR/Snowflake objects | DE 017 |
| R17 | **Scope creep** (connectors, UI, agents) | H | M | MVP boundary doc; capability map MVP column; tasks with expected/forbidden files; architecture baseline with ADR-gated breaking changes (DE-ADR-026) | — | governance |
| R18 | **Over-reliance on PostgreSQL as queue** at scale | L | L | Documented trigger to move to Temporal/queue; task tables designed for portability | — | ADR |
| R19 | **Evaluation not credible** (self-graded, non-deterministic) | M | M | Deterministic offline scenarios with replay; explicit metric definitions; baseline versioned; no LLM judge | Time-saved is an estimate → labelled | DE 014 |
| R20 | **Column-level lineage incomplete** (complex SQL, macros) | M | L | Model-level lineage from manifest is authoritative; column-level best-effort with coverage %, shown | — | DE 012 |
| R21 | **Approval reused for wrong operation/design/budget** | L | C | Typed subjects; operation key + resolved-input/artifact/provenance/connector/target/external-state binding; explicit budget caps; all-subject aggregation; recheck before attempt | V1 single human holds operator+approver roles; production disabled | DE 002A, DE 011 |
| R22 | **Local-only knowledge** (bootstrap sources private) blocks Cloud agents | M | M | Architecture fully expressed in tracked `docs/`; Cloud tasks reference tracked docs only | — | DE 001 |
| R23 | **Independent review disagrees after implementation starts** | M | H | DE 001R2A focused verification and operator acceptance before DE 002A; sequential contract/recovery/slice gates | Rework remains contained to the earliest red gate | DE 001 gate |
| R24 | **Time**: MVP effort exceeds 3–5 weeks | H | M | Vertical slices; fakes first; UI last; parallel lanes only after skeleton stable | Cut V1 partials (monitoring stub, staging deploy) first | plan |
| R25 | **Caller forges actor or workflow grants** | L | C | Local opaque sessions produce trusted `PrincipalRef`; roles/effective grants are server-derived; CSRF on mutations; clients request but never set grants | Single local account is not enterprise IAM; intentionally MVP-only | DE 002A |
| R26 | **In-flight work silently changes contract after upgrade** | M | H | Phase contract snapshot; connector advertises supported versions; payload schema versions persisted; unsupported old work parks | Old handler retention is operationally required while work drains | DE 002A, DE 002B |
| R27 | **Cancellation hides a running external effect** | M | H | Intent/shutdown states stop claims, fence results, cancel cooperatively and reconcile; terminal only after quiescence or explicit unresolved parking | Some providers cannot cancel; unresolved effect remains visible | DE 002B |
| R28 | **Audit and state diverge on crash** | L | H | Same PostgreSQL transaction for mutation/event; locked unique sequence; runtime audit role insert-only; integrity claim explicitly non-cryptographic | Privileged DB operator can alter storage | DE 002B |

## Property tests required (security-critical code)

| Component | Property |
|---|---|
| SQL classifier | ∀ generated statements from a destructive grammar → `is_destructive ∨ parse_ok=False`; ∀ SELECT-only grammar → `is_read_only`; idempotent normalization |
| Policy engine | all applicable denials persisted; rule-order permutation invariant; SECURITY severity dominates without masking lower reasons; approvals evaluated only with empty denial set |
| State machine | every state reachable; every non-terminal state has an exit; cancellation cannot become terminal with active/unparked effects; no transition outside table |
| Repair loop | attempts ≤ budgets under any sequence of proposal outcomes; hypothesis hashes unique per task |
| Redaction | ∀ fixture secrets → not present in output; idempotent |
| Approval binding | any operation/input/artifact/provenance/connector/target/external-state change invalidates operation approval; all mandatory subjects required |
| Scheduler | stale owner/epoch finalization updates zero rows; phase advance unique under competing coordinators; every dependency outcome reduces |
