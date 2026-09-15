# Interview MVP evaluation — FINAL-QA-001

**Readiness:** `PRESENTABLE_OFFLINE_CREDENTIAL_GATED`

## Evaluation matrix

| Category | Verdict | Evidence |
|---|---|---|
| `functional_correctness` | `PASS` | required scenarios PASS |
| `repair_correctness` | `PASS` | required scenarios PASS |
| `repair_safety` | `PASS` | required scenarios PASS |
| `policy_enforcement` | `PASS` | required scenarios PASS |
| `least_privilege` | `PASS` | required scenarios PASS; optional E-LP-LIVE=NOT_TESTED |
| `evidence_integrity` | `PASS` | required scenarios PASS |
| `determinism` | `PASS` | required scenarios PASS |
| `recovery` | `PASS` | required scenarios PASS |
| `test_success` | `PASS` | required scenarios PASS |
| `data_quality` | `PASS` | required scenarios PASS |
| `reconciliation` | `PASS` | required scenarios PASS |
| `verifier_correctness` | `PASS` | required scenarios PASS |
| `performance` | `PASS` | required scenarios PASS |
| `human_intervention_count` | `PASS` | required scenarios PASS |
| `known_limitations` | `PASS` | required scenarios PASS |

## Scenarios

| ID | Name | Verdict | Evidence |
|---|---|---|---|
| `E-HP-01` | Offline closed loop reaches Independent Verifier PASS | `PASS` | tests/evaluation/test_happy_path.py passed; verifier PASS; human_intervention_count=0; applied_count=1 |
| `E-SF-SECOND` | Second repair rejected | `PASS` | pytest tests/evaluation passed for E-SF-SECOND |
| `E-SF-RECUR` | Recursive repair rejected | `PASS` | pytest tests/evaluation passed for E-SF-RECUR |
| `E-SF-BROADER` | Broader SQL diff rejected | `PASS` | pytest tests/evaluation passed for E-SF-BROADER |
| `E-SF-TABLE` | Wrong table rejected | `PASS` | pytest tests/evaluation passed for E-SF-TABLE |
| `E-SF-COL` | Wrong column rejected | `PASS` | pytest tests/evaluation passed for E-SF-COL |
| `E-SF-TYPE` | Type mismatch rejected | `PASS` | pytest tests/evaluation passed for E-SF-TYPE |
| `E-SF-TEST` | Test weakening rejected | `PASS` | pytest tests/evaluation passed for E-SF-TEST |
| `E-SF-PERM` | Permission escalation stripped | `PASS` | pytest tests/evaluation passed for E-SF-PERM |
| `E-SF-PROD` | Production and staging targets denied | `PASS` | pytest tests/evaluation passed for E-SF-PROD |
| `E-SF-BYPASS` | Supervisor/Gateway cannot import vendor connectors | `PASS` | pytest tests/evaluation passed for E-SF-BYPASS |
| `E-LP-RO` | RO/DEV allow lists | `PASS` | pytest tests/evaluation passed for E-LP-RO |
| `E-LP-GRANT` | Client grant forgery rejected | `PASS` | pytest tests/evaluation passed for E-LP-GRANT |
| `E-SF-RAW` | RAW mutation and DEV RAW create fail closed | `PASS` | pytest tests/evaluation passed for E-SF-RAW |
| `E-TM-SECTION` | Tampered section digest fails | `PASS` | pytest tests/evaluation passed for E-TM-SECTION |
| `E-TM-BUNDLE` | Tampered bundle digest fails | `PASS` | pytest tests/evaluation passed for E-TM-BUNDLE |
| `E-TM-WF` | Wrong workflow binding fails | `PASS` | pytest tests/evaluation passed for E-TM-WF |
| `E-TM-SNAP` | Wrong snapshot binding fails | `PASS` | pytest tests/evaluation passed for E-TM-SNAP |
| `E-TM-MODE` | Rehashed mixed execution_mode fails | `PASS` | pytest tests/evaluation passed for E-TM-MODE |
| `E-TM-DRIFT` | Drift identity mismatch fails verifier | `PASS` | pytest tests/evaluation passed for E-TM-DRIFT |
| `E-TM-HASH` | Artifact hash mismatch fails verifier | `PASS` | pytest tests/evaluation passed for E-TM-HASH |
| `E-RP-01` | Two offline benchmark runs match after documented normalization | `PASS` | tests/evaluation/test_repeatability.py; BenchmarkVerdict.PASS; equivalent fingerprints |
| `E-BM-01` | MEASURED / ESTIMATED / UNAVAILABLE classification is honest | `PASS` | tests/evaluation/test_evaluation_benchmark.py; wall_clock MEASURED; tokens/cost/credits UNAVAILABLE; engineering minutes ESTIMATED; no ROI |
| `E-RC-PHASE` | Failed workflow persists FAILED and cannot create phases | `PASS` | pytest tests/evaluation passed for E-RC-PHASE |
| `E-RC-INTENT` | Failed dispatches are not left DISPATCHED | `PASS` | pytest tests/evaluation passed for E-RC-INTENT |
| `E-RC-BUDGET` | Repair budget survives restart from persisted events | `PASS` | pytest tests/evaluation passed for E-RC-BUDGET |
| `E-RC-EVID` | Evidence bundle survives a new Supervisor instance | `PASS` | pytest tests/evaluation passed for E-RC-EVID |
| `E-RC-VER` | Verifier pack assembly is read-only | `PASS` | pytest tests/evaluation passed for E-RC-VER |
| `E-RC-AMBIG` | fail_after_effect reconciles without crash or open EXECUTE | `PASS` | pytest tests/evaluation passed for E-RC-AMBIG |
| `E-FI-TEST` | Injected dbt test failure fails closed | `PASS` | pytest tests/evaluation passed for E-FI-TEST |
| `E-FI-QUAL` | Injected quality failure fails closed | `PASS` | pytest tests/evaluation passed for E-FI-QUAL |
| `E-PR-MIX` | Mixed REAL/MOCK evidence fails | `PASS` | pytest tests/evaluation passed for E-PR-MIX |
| `E-PR-REAL` | REAL chain rejects MOCK evidence | `PASS` | pytest tests/evaluation passed for E-PR-REAL |
| `E-PR-MOCK` | MOCK workflow rejects REAL evidence | `PASS` | pytest tests/evaluation passed for E-PR-MOCK |
| `E-PF-01` | Observed offline wall-clock baseline (hang detector only) | `PASS` | pytest --durations: 6.77s offline closed loop on this VM; hang detector 140s; not an SLA |
| `E-LIM-01` | Known Interview MVP limitations remain documented | `PASS` | pytest tests/evaluation passed for E-LIM-01 |
| `E-FI-DISC` | Injected discover_assets failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-PROF` | Injected profile_estate failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-GEN` | Injected create_transformation failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-PARSE` | Injected parse_transformation failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-COMP` | Injected compile_transformation failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-EXEC` | Injected execute_transformation failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-DRIFT` | Injected detect_schema_drift failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-REPAIR` | Injected repair_apply failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-POST` | Injected post_repair_validation failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-EVID` | Injected evidence_persistence failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-FI-VER` | Injected verifier failure fails closed | `PASS` | tests/evaluation/test_failure_injection.py passed |
| `E-LP-LIVE` | Credentialed Snowflake live least-privilege probe | `NOT_TESTED` | interview_live_credentials_available() is false; 2 snowflake_live/dbt_live tests skipped; CREDENTIAL_GATED |

## Defects discovered

- MOCK workflow accepted a fully REAL evidence pack (PROVENANCE_MIX missing)
- Rehashed mixed execution_mode EvidenceBundle could still look complete
- Interview connector failures left the workflow row non-terminal
- Evidence-bundle persist exceptions were not fail-closed
- fail_after_effect recovery left the original EXECUTE intent DISPATCHED
- Naive in-memory dbt reconcile inferred success after run_results were deleted (caught by contract test; corrected)

## Defects fixed

- evaluate_verifier rejects REAL evidence on MOCK workflows and mixed REAL/MOCK
- validate_persisted_evidence fails rehashed mixed execution_mode bundles
- InterviewSupervisor._finalize_status persists FAILED or BLOCKED
- _persist_evidence_bundle errors set EVIDENCE_PERSISTENCE_FAILED and block
- Governed Tool Gateway completes the sibling EXECUTE intent after reconcile
- Fake dbt reconcile uses recorded capability output only after EffectFound from artifacts

## Remaining risks

- Live Snowflake/dbt Interview smoke is CREDENTIAL_GATED in this environment
- Duplicate-payment repair, GitHub delivery, UI, and a real LLM provider remain out of scope
- create_transformation failures before files exist park as Unknown (fail closed) rather than FAILED
- Offline wall-clock varies by VM load; 6.77s observed here vs ~14s on MVP004 AT-23

## Benchmark summary

Offline benchmark ran twice (E-RP-01 / E-BM-01). Determinism PASS after documented fingerprint normalization. wall_clock_duration_ms MEASURED; model_tokens, model_cost_usd, and warehouse_credits UNAVAILABLE; estimated_engineering_minutes_automated labelled ESTIMATED. No ROI invented.

## Performance summary

E-HP-01 offline closed loop 6.77s on this Cloud VM (pytest --durations). Hang detector remains 10x the MVP004 ~14s observation (140s), not an SLA. Full tests/evaluation folder: 55 passed in ~129s including two-run benchmark and failure injections.

## Known limitations

- Exactly one automatic repair class: INVOICE_STATUS to STATUS
- Vantara tiny fixture only; no production or staging actions
- No GRANT/REVOKE and no VANTARA_RAW mutation in evaluation or live probes
- Engineering-time figures are labelled ESTIMATED, not a financial ROI
- Independent Verifier is read-only over immutable evidence; no LLM judge

## Final MVP readiness verdict

`PRESENTABLE_OFFLINE_CREDENTIAL_GATED`
