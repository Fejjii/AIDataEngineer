# Interview MVP evaluation

Independent Testing, Debugging and Evaluation for the accepted Interview MVP
(`FINAL-QA-001`).

This is the implemented evaluation evidence. It is **not** a V1 `aide eval` command
and **not** scenario `S04_combined` (two repairs). The recruiter proof is one
customer-revenue schema-drift loop.

- Scorecard contracts: `aide.domain.evaluation` and `aide.app.evaluation`
- Adversarial scenarios: `tests/evaluation/`
- Deterministic report: [`FINAL_QA_001.md`](FINAL_QA_001.md)
- Deployed acceptance: [`LIVE_ACCEPTANCE_001.md`](LIVE_ACCEPTANCE_001.md)
- Credentialed Snowflake/dbt validation: [`SNOWFLAKE_LIVE_001.md`](SNOWFLAKE_LIVE_001.md) (`REMEDIATED`; historical failure retained, PR 31 live smoke PASS)
- Interview scenarios: [`DEMO_SCENARIOS_001.md`](DEMO_SCENARIOS_001.md)
- Recruiter commands: `uv run aide interview demo` and `uv run aide interview benchmark`
- Broader V1 design (not the Interview CLI): [`docs/EVALUATION_STRATEGY.md`](../EVALUATION_STRATEGY.md)

**Proves:** Independent Verifier `PASS` on the offline closed loop, one allow-listed
repair, fail-closed safety/tamper/provenance, labelled MEASURED/ESTIMATED/UNAVAILABLE
metrics, and two-run determinism after documented identifier normalization.

**Does not prove:** financial ROI, LLM token cost, Snowflake credits, or deferred V1 scenarios (GitHub PR, duplicate payments, UI).

PASS, FAIL, and NOT_TESTED are produced by pytest and scorecard aggregation.
There is no LLM judge.
