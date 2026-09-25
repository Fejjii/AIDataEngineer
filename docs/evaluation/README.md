# Interview MVP evaluation

Index of evaluation evidence for the accepted Interview MVP. This is **not** a V1
`aide eval` command and **not** scenario `S04_combined` (two repairs). The recruiter
proof is one customer-revenue schema-drift loop.

| Document | What it records |
|---|---|
| [`FINAL_QA_001.md`](FINAL_QA_001.md) | FINAL QA offline scorecard |
| [`LIVE_ACCEPTANCE_001.md`](LIVE_ACCEPTANCE_001.md) | LIVE ACCEPTANCE of the Railway synthetic demo |
| [`FRONTIER_HOLISTIC_CHALLENGE_002.md`](FRONTIER_HOLISTIC_CHALLENGE_002.md) | Frontier holistic challenge and the documentation closure that follows it |
| [`DEMO_SCENARIOS_001.md`](DEMO_SCENARIOS_001.md) | Interview conversation scenarios |
| [`SHOWCASE_SMOKE_001.md`](SHOWCASE_SMOKE_001.md) | Recruiter console smoke and runbook |
| [`../EVALUATION_STRATEGY.md`](../EVALUATION_STRATEGY.md) | V1 evaluation design and the historical manual-minutes baseline |

- Scorecard contracts: `aide.domain.evaluation` and `aide.app.evaluation`
- Adversarial scenarios: `tests/evaluation/`
- Recruiter commands: `uv run aide interview demo` and `uv run aide interview benchmark`

**FINAL QA** proves the offline closed loop: Independent Verifier `PASS`, one
allow-listed repair, fail-closed safety/tamper/provenance, labelled
MEASURED/ESTIMATED/UNAVAILABLE metrics, and two-run determinism after documented
identifier normalization.

**LIVE ACCEPTANCE** proves the Railway synthetic HTTP demo, health, token gate on
`POST /v1/interview/demo`, and restart persistence. Those runs report
`live_smoke=NOT_RUN`. They do not exercise Snowflake.

**Credentialed live Snowflake and dbt** proof is the accepted evidence on
[PR 31](https://github.com/Fejjii/AIDataEngineer/pull/31) and
[PR 32](https://github.com/Fejjii/AIDataEngineer/pull/32). PR 31 is merged. Its run
report records the grant-metadata least-privilege probe, governed Snowflake RO/DEV
dispatch, and real dbt on a credentialed host
([`LIVE_PROFILING_EFFICIENCY_002`](../agent/runs/LIVE_PROFILING_EFFICIENCY_002/LIVE_PROFILING_EFFICIENCY_002-SESSION-20260922T145337Z.md)).
PR 32 is the closed acceptance audit that records live Snowflake, live dbt, the
governed Interview path, and `aide interview live-smoke` PASSED. The Frontier review
treats that pair as the live least-privilege proof. It does not include RAW drift or
the Independent Verifier.

**Does not prove:** financial ROI, LLM token cost, Snowflake credits, live RAW drift,
the Independent Verifier on the live path, or deferred V1 scenarios (GitHub PR,
duplicate payments, UI).

PASS, FAIL, and NOT_TESTED are produced by pytest and scorecard aggregation.
There is no LLM judge.
