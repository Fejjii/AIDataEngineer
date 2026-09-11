# Data Modelling Strategy

**Task:** DE 001 · **Status:** ACCEPTED

The **architecture class** of a data product is chosen by a deterministic rule table from
objective signals. The LLM designs *inside* that class. It never picks the class.

---

## 1. Signals

All signals are computed by deterministic code from persisted artifacts. Unknown signals
are `UNKNOWN`, never guessed.

| Signal | Source | Domain |
|---|---|---|
| `deliverable_type` | `RequirementSpec` | ANALYTICAL_DATA_PRODUCT, PIPELINE, MODEL_CHANGE, QUALITY_SUITE, INVESTIGATION |
| `history_requirements` | `RequirementSpec` (+ clarification) | NONE, CURRENT_ONLY, FULL_HISTORY, UNKNOWN |
| `auditability` | `RequirementSpec.constraints` (regulatory / audit keywords), org policy config | LOW, HIGH, UNKNOWN |
| `source_count` | `AssetSelection` | int |
| `source_system_count` | distinct schemas/connectors in selection | int |
| `source_structure` | `describe_asset` | NORMALIZED_3NF, DENORMALIZED_EXTRACT, EVENT_LOG, MIXED |
| `volume_class` | max profiled `row_count` | S (<1M), M (1M–50M), L (50M–1B), XL (>1B) |
| `velocity` | `RequirementSpec.freshness_requirement`, source `LOADED_AT` cadence | BATCH_DAILY, INTRA_DAY, NEAR_REAL_TIME |
| `change_frequency` | profiles: ratio of `UPDATED_AT` > `CREATED_AT`, presence of `VALID_FROM/TO` | LOW, MEDIUM, HIGH |
| `entity_history_in_source` | `VALID_FROM/VALID_TO` or versioned rows detected | bool |
| `query_patterns` | `RequirementSpec.consumers` + metrics | AGGREGATE_BI, DRILL_DOWN, OPERATIONAL_LOOKUP, ML_FEATURES, UNKNOWN |
| `downstream_consumers` | `RequirementSpec.consumers` | BI, ANALYSTS_SQL, ML, APPLICATION, UNKNOWN |
| `latency_requirement` | `RequirementSpec.freshness_requirement` | DAILY, HOURLY, MINUTES |
| `platform_capabilities` | connector spec | supports MERGE, CLUSTERING, TIME_TRAVEL, STREAMS/TASKS, DYNAMIC_TABLES |
| `cost_sensitivity` | org config / requirement constraints | LOW, MEDIUM, HIGH |
| `key_quality` | profiles: candidate key uniqueness, duplicate groups | CLEAN, DUPLICATES_PRESENT, NO_NATURAL_KEY |
| `identifier_alignment` | `RelationshipCandidates` inclusion ratios across systems | ALIGNED (≥0.99), PARTIAL (0.9–0.99), MISALIGNED (<0.9) |

---

## 2. Decision rules

Rules are evaluated in order within each decision; the first match wins; every decision
records the rule id that fired. Output: `ArchitectureDecision`.

### 2.1 Layering

| Rule | Condition | Decision |
|---|---|---|
| L1 | `deliverable_type ∈ {ANALYTICAL_DATA_PRODUCT, PIPELINE}` | `STAGING_INTERMEDIATE_MARTS` (staging = 1:1 cleaned sources; intermediate = business logic, dedup, joins; marts = presentation) |
| L2 | `deliverable_type = MODEL_CHANGE` | reuse existing project layering (detected from manifest) |
| L3 | `deliverable_type = QUALITY_SUITE` | no new layers; tests only |
| L4 | `deliverable_type = INVESTIGATION` | ephemeral queries only; no models |
| Naming | `org.naming_convention = MEDALLION` | map staging→bronze, intermediate→silver, marts→gold (naming only; same structure) |

### 2.2 Integration layer (Data Vault)

| Rule | Condition | Decision |
|---|---|---|
| V1 | `auditability = HIGH` ∧ `source_system_count ≥ 3` ∧ `history_requirements = FULL_HISTORY` ∧ `change_frequency ≥ MEDIUM` | `RAW_VAULT_RECOMMENDED` → **approval required**; V1 generates star schema only and records the recommendation |
| V2 | `source_system_count ≥ 5` ∧ `identifier_alignment = MISALIGNED` | `RAW_VAULT_RECOMMENDED` (same handling) |
| V3 | otherwise | `NO_VAULT` |

Reason for approval: Vault materially increases model count and cost; it is a material
architecture decision the human owns.

### 2.3 Presentation model

| Rule | Condition | Decision |
|---|---|---|
| P1 | `query_patterns ∈ {AGGREGATE_BI, DRILL_DOWN}` ∨ `downstream_consumers = BI` | `STAR_SCHEMA` |
| P2 | `downstream_consumers = ML` ∧ `query_patterns = ML_FEATURES` | `WIDE_FEATURE_TABLE` (V2; V1 emits star + one wide mart) |
| P3 | `downstream_consumers = APPLICATION` ∧ `query_patterns = OPERATIONAL_LOOKUP` | `NORMALIZED_SERVING` (V2) |
| P4 | dimension has > 3 hierarchical levels with independent change rates ∧ `volume_class ≥ L` ∧ `cost_sensitivity = HIGH` | `SNOWFLAKE_SCHEMA` for that dimension → approval required |
| P5 | `UNKNOWN` consumers | `STAR_SCHEMA` + open question to human (non-blocking) |

### 2.4 Facts

For each candidate fact (an entity with measures and a natural event/transaction grain):

| Rule | Condition | Decision |
|---|---|---|
| F1 | transaction-level rows with additive measures | `TRANSACTION_FACT` at source grain |
| F2 | metric requires periodic balance (MRR, balances) | additionally `PERIODIC_SNAPSHOT_FACT` (daily/monthly) |
| F3 | process with milestones (order→invoice→payment) | `ACCUMULATING_SNAPSHOT_FACT` (V2; V1 records recommendation) |
| F4 | `key_quality = DUPLICATES_PRESENT` for the grain | mandatory `dedup_rule` in intermediate layer; fact grain test remains `unique` |
| Grain proof | grain columns must be a profiled candidate key (uniqueness ≥ 0.999) **after** dedup rule; otherwise design invalid | Det validator |

### 2.5 Dimensions and history

| Rule | Condition | Decision |
|---|---|---|
| D1 | `history_requirements = FULL_HISTORY` ∧ (`change_frequency ≥ MEDIUM` ∨ `entity_history_in_source`) | `SCD2` (valid_from, valid_to, is_current, surrogate key) |
| D2 | `history_requirements = FULL_HISTORY` ∧ `change_frequency = LOW` | `SCD2` (cheap; still required) |
| D3 | `history_requirements = CURRENT_ONLY` | `SCD1` |
| D4 | `history_requirements = UNKNOWN` | blocking clarification question (rule fires in RECEIVED via Det ambiguity rule) |
| D5 | attribute set with high change + low analytical value (e.g., contact phone) | `SCD1` on those attributes within an SCD2 dimension (hybrid, documented) |
| D6 | `entity_history_in_source = true` | build SCD2 from source validity intervals; **do not** snapshot |
| D7 | `entity_history_in_source = false` ∧ SCD2 required | dbt snapshot (`timestamp` strategy on `UPDATED_AT` if reliable, else `check` on tracked columns) |
| D8 | date dimension | always `STATIC` generated `dim_date` |
| Conformance | same business entity across sources → one conformed dimension with crosswalk; `identifier_alignment = MISALIGNED` → survivorship rule required from human if not derivable | Det + clarification |

### 2.6 Materialization and incrementality

| Rule | Condition | Decision |
|---|---|---|
| M1 | staging models | `view` (S/M volume) or `table` (L/XL) |
| M2 | intermediate | `ephemeral` if referenced once and S volume; else `table` |
| M3 | facts with `volume_class ≥ M` ∧ reliable `LOADED_AT`/`UPDATED_AT` watermark ∧ platform supports MERGE | `incremental` with `merge` on grain, watermark lookback = 3 days (late-arriving allowance) |
| M4 | facts with `volume_class = S` | `table` (full refresh; simpler, cheaper to reason about) |
| M5 | no reliable watermark | `table` + recommendation to add source watermark |
| M6 | marts | `table`; `dynamic table`/incremental only if `latency_requirement ≤ HOURLY` and platform supports |
| M7 | `cost_sensitivity = HIGH` ∧ `volume_class ≥ L` | clustering key recommendation on fact date column (recommendation only in V1) |

### 2.7 Approval flags

`approval_required = true` when any of: V1/V2 fired, P4 fired, estimated model count > 40,
or estimated warehouse cost class ≥ `L`. Otherwise the design is reviewed via PR only.

---

## 3. Output: `ArchitectureDecision`

```json
{
  "layering": "STAGING_INTERMEDIATE_MARTS",
  "naming": "DBT_DEFAULT",
  "integration_layer": {"decision": "NO_VAULT", "rule": "V3", "recommendation": null},
  "presentation": {"decision": "STAR_SCHEMA", "rule": "P1"},
  "facts": [{"entity": "invoice_line", "kind": "TRANSACTION_FACT", "grain": ["invoice_line_id"], "materialization": "incremental", "rule": ["F1","M3"]}],
  "dimensions": [{"entity": "customer", "history": "SCD2", "source_history": false, "strategy": "snapshot_timestamp", "rule": ["D1","D7"]}],
  "signals": {"...": "..."},
  "approval_required": false,
  "open_questions": []
}
```

Every rule id is stable and documented so the UI can render *"Star schema chosen because
P1: consumers = BI"*.

---

## 4. What the LLM does inside the class (`propose_model_design`)

- Map business entities in the requirement to source assets and columns.
- Name models per convention (`stg_<source>__<entity>`, `int_<entity>_<verb>`, `dim_`, `fct_`, `mart_`).
- Propose column-level expressions (standardization, type casts, currency normalization).
- Propose the dedup/survivorship rule when profiles show duplicates and the human has not
  specified one (flagged as assumption; shown in PR).
- Propose SCD2 tracked columns.
- Propose business assertion tests (flagged for human confirmation).

Deterministic validators then check the design against profiles and metadata
(`docs/TOOL_CONTRACTS.md` §32). A design that fails validation is regenerated with the
violations; two failures → `BLOCKED` with the violations shown.

---

## 5. Data Vault position

V1 **detects** when a Raw Vault would be justified (rules V1/V2) and **recommends** it
with rationale, but generates a star schema. Reasons: Vault generation roughly triples
model count, needs organisational hashing/ business-key conventions the human must own,
and the demo does not require it. Vault templates (hub/link/satellite) are a V2 generator
extension that plugs into the same `ModelDesignUnit.kind` enum.

---

## 6. Worked decision for the demo

Signals: `ANALYTICAL_DATA_PRODUCT`, `FULL_HISTORY`, `auditability = LOW`, 4 sources across
4 schemas (one system: the RAW warehouse), `volume_class = M`, `consumers = BI`,
`latency = DAILY`, `key_quality = DUPLICATES_PRESENT` (accounts, payments),
`identifier_alignment = PARTIAL` (crosswalk 0.962), `entity_history_in_source = true` for
plans, `false` for customers.

Fired: L1, V3, P1, F1 (+F2 for MRR snapshot mart), F4 (dedup rules), D1+D7 (customer
SCD2 via snapshot), D1+D6 (plan SCD2 from source intervals), D8, M1 (views), M2, M3
(incremental facts), M6. `approval_required = false`.
