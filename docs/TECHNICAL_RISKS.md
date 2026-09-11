# Technical Risks

**Task:** DE 001 · **Status:** PROPOSED

Register of risks to the architecture and MVP, with likelihood (L/M/H), impact (L/M/H/C),
mitigation designed into V1, residual risk, and the owner/task where the mitigation lands.

| # | Risk | L | I | Mitigation in design | Residual / detection | Lands in |
|---|---|---|---|---|---|---|
| R1 | **LLM output quality**: generated SQL/dbt frequently invalid or semantically wrong | H | H | Templates for structure; per-unit generation with metadata + profiles; compile + EXPLAIN before execution; deterministic quality checks; bounded regeneration and repair; evaluation harness tracks SQL success and first-attempt success | Semantic errors not caught by tests (wrong join logic producing plausible numbers) → reconciliation checks and human PR review; metric visible in evaluation | DE 007, DE 008, DE 014 |
| R2 | **SQL safety classifier gaps** (sqlglot misparse, dialect quirks, obfuscated destructive statements) | M | C | Fail closed on parse errors; deny multi-statement/dynamic SQL; identity cannot write outside DEV; namespace rule; property-based tests (hypothesis) over statement grammar; corpus of adversarial SQL in tests | A parseable-but-misclassified statement; mitigated by identity + namespace layers; add vendor `EXPLAIN` classification cross-check | DE 002, DE 010 |
| R3 | **Prompt injection via metadata/data** | M | H | Untrusted-text delimiting; no tools for reasoning capabilities; all effects gated by Det policy; injection heuristics → audit; S09 scenario | LLM produces misleading design text; caught by human PR review; cannot cause effects | DE 006, DE 010, DE 014 |
| R4 | **Snowflake cost runaway** (profiling large tables, repeated rebuilds) | M | M | Budgets on profiling (row/byte/time), X-Small warehouse with auto-suspend, statement timeouts, per-workflow cost cap → COST approval, query tagging for attribution | Account-usage lag hides spend for minutes; estimated cost from duration used meanwhile | DE 004, DE 010, DE 013 |
| R5 | **LLM cost runaway** (loops, large contexts) | M | M | Per-workflow cap enforced in gateway; summaries not raw artifacts in context; explicit counters for replans/repairs/retries; no recursion | Cap set too low blocks legit runs → approval path | DE 002, DE 013 |
| R6 | **Repair loop oscillation / same fix repeated** | M | M | Hypothesis hash novelty; max 2/task, 4/workflow; tests-not-weakened validator; escalation to BLOCKED with evidence | Two distinct wrong hypotheses waste budget; acceptable | DE 009 |
| R7 | **dbt / adapter / Python version incompatibility** | M | M | Pin Python 3.12; lock file; subprocess isolation; CI runs fake dbt contract tests and `dbt --version`; re-verify at DE 002 | Upgrade friction later | DE 002, DE 007 |
| R8 | **State corruption under concurrency / duplicate side effects after crash** | L | H | Single writer per workflow via optimistic version; SKIP LOCKED claims; leases; operation identity (`idempotency_key`) stable across attempts and propagated into external systems; attempt intent persisted before effect; `reconcile` before any re-execution; immutable artifacts; transition table with tests | Non-idempotent `deploy` with unreconcilable outcome → `AMBIGUOUS_OUTCOME`, parked for human, never auto-repeated | DE 002, DE 003, DE 017 |
| R9 | **Resumability gaps** (orphaned working copies, half-written project files) | M | M | Working copy per workflow rebuilt from artifacts (artifacts are truth, files are cache); reaper on startup | Disk usage; cleanup command | DE 007 |
| R10 | **Fake connectors diverge from real behaviour** (DuckDB ≠ Snowflake) | H | M | Contract tests run against both; transpilation via sqlglot; recorded real error fixtures for mappers; live E4 before demos; MOCK watermark in UI | Some Snowflake-only functions unsupported in fake → generation conventions avoid them or fake marks unsupported | DE 004, DE 007 |
| R11 | **Planner produces invalid or wasteful DAGs** | M | M | Deterministic templates for most phases; strict plan validation; `max_tasks`; replan limit | Suboptimal but valid plans; evaluation tracks task counts | DE 002, DE 005 |
| R12 | **Modelling rule table too rigid or wrong for edge cases** | M | M | Rules are data with ids; unknown signals → clarification not guess; approval for material classes; rationale shown | Human overrides needed → design approval path; rule evolution via ADR | DE 006 |
| R13 | **Metadata/profiling privacy leakage** (PII in samples reaching LLM or artifacts) | M | H | Column masking heuristics; sample caps; redaction filter; retention limits; secret/PII scan tests over offline run outputs | Heuristics miss a PII column → mitigated by synthetic data in V1; real data needs classification config | DE 005, DE 010 |
| R14 | **Secret leakage** in logs, prompts, artifacts, PRs | L | C | `SecretRef` indirection; `SecretStr`; redaction processors; gitleaks pre-commit + CI + pre-commit-to-PR scan; leakage scan test | Novel secret formats → entropy heuristic | DE 002, DE 011, DE 016 |
| R15 | **GitHub token over-privilege or protected branch push** | L | H | Fine-grained token with minimal scopes; R14 policy rule; never force-push; branch pattern `aide/*` | Misconfigured repo protection → documented setup check in `aide connectors check` | DE 011 |
| R16 | **Demo brittleness** (live LLM variance, cold warehouse, network) | H | M | Offline mode with replay as primary demo path; live mode rehearsed with E4; warehouse pre-warm command; recorded backup video | Live demo still risky → present offline + show live PR/Snowflake objects | DE 017 |
| R17 | **Scope creep** (connectors, UI, agents) | H | M | MVP boundary doc; capability map MVP column; tasks with expected/forbidden files; architecture baseline with ADR-gated breaking changes (DE-ADR-026) | — | governance |
| R18 | **Over-reliance on PostgreSQL as queue** at scale | L | L | Documented trigger to move to Temporal/queue; task tables designed for portability | — | ADR |
| R19 | **Evaluation not credible** (self-graded, non-deterministic) | M | M | Deterministic offline scenarios with replay; explicit metric definitions; baseline versioned; no LLM judge | Time-saved is an estimate → labelled | DE 014 |
| R20 | **Column-level lineage incomplete** (complex SQL, macros) | M | L | Model-level lineage from manifest is authoritative; column-level best-effort with coverage %, shown | — | DE 012 |
| R21 | **Approval bypass by artifact mutation** | L | C | Approvals bound to hashes; recheck at execution; immutable artifacts | — | DE 010 |
| R22 | **Local-only knowledge** (bootstrap sources private) blocks Cloud agents | M | M | Architecture fully expressed in tracked `docs/`; Cloud tasks reference tracked docs only | — | DE 001 |
| R23 | **Frontier review disagrees with architecture after implementation started** | M | H | Independent review gate before DE 002; DE 002 limited to skeleton + slice | Rework of slice; contained | DE 001 gate |
| R24 | **Time**: MVP effort exceeds 3–5 weeks | H | M | Vertical slices; fakes first; UI last; parallel lanes only after skeleton stable | Cut V1 partials (monitoring stub, staging deploy) first | plan |

## Property tests required (security-critical code)

| Component | Property |
|---|---|
| SQL classifier | ∀ generated statements from a destructive grammar → `is_destructive ∨ parse_ok=False`; ∀ SELECT-only grammar → `is_read_only`; idempotent normalization |
| Policy engine | monotonic: adding grants never turns ALLOW into DENY; removing grants never turns DENY into ALLOW; DENY rules dominate |
| State machine | every state reachable; every non-terminal state has an exit; no transition outside the table |
| Repair loop | attempts ≤ budgets under any sequence of proposal outcomes; hypothesis hashes unique per task |
| Redaction | ∀ fixture secrets → not present in output; idempotent |
| Approval binding | any artifact change ⇒ approval invalid |
