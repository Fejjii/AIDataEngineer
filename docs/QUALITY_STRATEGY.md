# Quality Strategy

**Task:** DE 001 · **Status:** ACCEPTED

Generated transformations are validated **objectively** by deterministic code. No LLM
participates in deciding whether data is correct. The Quality Engine produces a
`ValidationReport` whose every entry has a check id, target, expectation, observation,
status and failure class. The Interview MVP path is `docs/INTERVIEW_DEMO.md`; this file is
the broader V1 check catalogue.

---

## 1. Layers of validation

| Layer | When | Mechanism | Cost |
|---|---|---|---|
| L0 Static | GENERATION | `classify_sql`, ref/source resolution, YAML ↔ compiled column existence, naming conventions, forbidden Jinja | free |
| L1 Compile / Explain | GENERATION | `compile_transformation`, `validate_query` (EXPLAIN) | cheap |
| L2 Schema conformance | VALIDATION | describe created objects; compare to `ModelDesign` columns/types/grain | cheap |
| L3 dbt tests | EXECUTION/VALIDATION | generic + custom tests from `schema.yml` | warehouse |
| L4 Quality Engine checks | VALIDATION | reconciliation, row counts, freshness, distribution | warehouse |
| L5 Business assertions | VALIDATION | human-confirmed assertions compiled to SQL tests | warehouse |

A phase advances only when all applicable layers pass or every failure is routed to
REPAIR with a failure class.

---

## 2. Check catalogue

Each check has a deterministic generator (produces SQL or a comparison from artifacts),
a severity (`ERROR` blocks, `WARN` reported), and a default failure class.

| Check id | Scope | Expectation | Implementation | Severity | Failure class |
|---|---|---|---|---|---|
| `not_null` | column | null ratio = 0 for keys and required columns; ≤ threshold for others (threshold from design; default 0) | dbt `not_null` / SQL | ERROR | DATA_QUALITY |
| `unique` | column set | uniqueness ratio = 1.0 on declared grain and surrogate keys | dbt `unique` / `unique_combination_of_columns` | ERROR | DATA_QUALITY |
| `accepted_values` | column | values ⊆ declared set (from profile top values confirmed by design, e.g. currency codes, statuses) | dbt `accepted_values` | ERROR | DATA_QUALITY |
| `type_conformance` | column | actual type matches design type | describe vs design | ERROR | TYPE_MISMATCH |
| `schema_conformance` | model | column set = design column set (no missing; extras WARN) | describe vs design | ERROR/WARN | SCHEMA_MISMATCH |
| `schema_drift_source` | source asset | current describe = snapshot at discovery | `detect_schema_drift` | ERROR (removed/type change) / WARN (added) | SCHEMA_MISMATCH |
| `relationship` | FK column | inclusion ratio = 1.0 to parent key (or ≥ threshold with orphan handling documented) | dbt `relationships` | ERROR | DATA_QUALITY |
| `freshness` | source / model | `max(loaded_at)` within SLA (default 1 day) | SQL | ERROR (source) / WARN (model) | DATA_QUALITY |
| `completeness_rowcount` | staging vs source | `count(stg) = count(source)` (or documented filter ratio) | SQL pair | ERROR | DATA_QUALITY |
| `completeness_keys` | dim vs fact | every fact FK has a dim row (post-SCD2: for the fact date) | SQL | ERROR | DATA_QUALITY |
| `reconciliation_sum` | fact vs source | `sum(measure)` fact = sum source (after documented dedup/filters), tolerance 0.0 % default, configurable | SQL pair | ERROR | DATA_QUALITY |
| `reconciliation_cross_domain` | facts | e.g., paid ≤ invoiced per invoice; reported ratio | SQL | WARN (reported) | DATA_QUALITY |
| `scd2_integrity` | SCD2 dim | no overlapping intervals per natural key; exactly one `is_current` per key; `valid_from < valid_to` | SQL | ERROR | DATA_QUALITY |
| `incremental_idempotency` | incremental model | re-running with same watermark yields 0 changed rows | run twice in DEV (opt-in for evaluation) | ERROR | DATA_QUALITY |
| `dedup_effectiveness` | intermediate | duplicate groups after dedup rule = 0 on grain | SQL | ERROR | DATA_QUALITY |
| `distribution_shift` | column | null ratio / distinct ratio / mean within ±k·σ of profile (k=3) or ±20 % | profile vs post-run profile | WARN | DATA_QUALITY |
| `business_assertion` | model | human-confirmed SQL predicate returns 0 violations | dbt singular test | ERROR | DATA_QUALITY |
| `row_count_nonzero` | model | count > 0 (unless design allows empty) | SQL | ERROR | DATA_QUALITY |
| `pii_masking` | mart | columns tagged PII are masked/hashed per policy | describe + SQL sample | ERROR | UNSAFE_OPERATION |

---

## 3. Test generation rules (from `ModelDesign`)

| Design element | Generated tests |
|---|---|
| Surrogate key | `unique`, `not_null` |
| Declared grain | `unique_combination_of_columns` |
| Natural key(s) | `not_null`; `unique` only after dedup layer |
| Foreign key to dimension | `relationships` |
| SCD2 dimension | `scd2_integrity`, `unique(natural_key, valid_from)` |
| Column with `accepted_values` in design | `accepted_values` |
| Measure columns | `not_null` (or documented nullable), `reconciliation_sum` against source |
| Source table | `freshness`, `schema_drift_source`, `completeness_rowcount` for its staging model |
| Incremental model | `incremental_idempotency` (evaluation mode) |
| Business assertions proposed by LLM | generated as singular tests **only after** human confirmation in the design review or PR; until then rendered as `WARN` |

---

## 4. Handling untrusted inputs to quality

- Accepted-value sets come from **profiles** (observed values) intersected with design;
  the LLM may propose but cannot add unobserved values without a flag.
- Thresholds live in configuration and design artifacts, never in prompts.
- Failing-row samples are capped (20 rows) and masked before persistence or LLM exposure.

---

## 5. Repair interaction

When a check fails:

1. The failure is classified (`DATA_QUALITY`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`).
2. `inspect_failure` collects: check definition, observed value, failing-row sample, upstream lineage of the failing column, relevant profiles, drift report.
3. `diagnose_failure` proposes a patch to the model or its direct upstream in the same phase.
4. Only the patched model and its descendants are rebuilt and re-tested.
5. The **check that failed must pass** and **no previously passing check may regress**;
   otherwise the repair is rejected (counts toward the budget).

A repair may never *weaken* a check (delete a test, raise a threshold, add `WHERE 1=0`).
Det validator: the set of tests after repair ⊇ set before, thresholds unchanged unless
the human changed them.

---

## 6. Deterministic re-profiling after build

After a successful build, marts and dims are profiled with the same profiler used for
sources. This yields: post-run distributions for `distribution_shift`, documentation
statistics, and the baseline for future `check_monitor`.

---

## 7. Reporting

`ValidationReport` structure:

```json
{"report_id":"…","workflow_id":"…","attempt":2,
 "summary":{"total":58,"passed":58,"failed":0,"warned":2},
 "checks":[{"check_id":"reconciliation_sum","target":"fct_payment.amount","expectation":"= 4,182,113.20 (stg_payments dedup)","observed":"4,182,113.20","status":"PASS","severity":"ERROR","failure_class":null,"evidence_ref":"…"}],
 "regressions":[]}
```

The UI renders it as a checklist; the PR body includes the summary table; the evaluation
harness reads it for data-quality pass rate.
