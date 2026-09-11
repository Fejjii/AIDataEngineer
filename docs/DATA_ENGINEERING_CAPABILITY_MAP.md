# Data Engineering Capability Map

**Task:** DE 001 · **Status:** ACCEPTED

A taxonomy of the modern Data Engineering lifecycle as the platform sees it. Each row is a
*business-level* capability; the typed system capabilities that implement it are in
`docs/CAPABILITY_MODEL.md`.

## Legend

| Column | Values |
|---|---|
| Automation potential | **VH** very high · **H** high · **M** medium · **L** low · **N** none (human) |
| Human involvement | **None** · **Review** (via PR/report) · **Approve** (explicit gate) · **Decide** (human owns the decision) |
| Risk | **L / M / H / C** (critical) — blast radius if wrong |
| Det / LLM | **Det** deterministic code · **LLM** reasoning · **Det+LLM** LLM proposes, Det validates/enforces |
| MVP | **Core** in MVP · **Partial** · **Stub** (contract exists, fake only) · **No** |
| Future | Target phase: **V2** (post-MVP connectors) · **V3** (enterprise showcase) · **—** never automated |

---

## 1. Source connectivity and ingestion

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Register / test connection to a source | H | Approve (new live source) | M | Det | Connector `health`, secrets boundary | Core (Snowflake, PostgreSQL, dbt, GitHub) | V2 more connectors |
| Database ingestion (batch extract → RAW) | H | Review | M | Det+LLM (mapping) | `discover_assets`, `create_dataset`, `execute_transformation` | Partial (synthetic loader script, not agent-driven) | V2 agent-driven |
| API ingestion | M | Review | M | Det+LLM | API connector, schema inference | No | V2 |
| File ingestion (CSV/Parquet/JSON) | H | Review | L | Det+LLM (schema inference) | Object storage connector, `create_dataset` | No | V2 |
| Object storage (S3 / Azure Blob / GCS) listing & loading | H | Review | M | Det | Storage connector | No | V2 |
| Batch pipelines (scheduled full/incremental loads) | H | Review | M | Det | Orchestration connector or platform tasks | Partial (dbt build only) | V2 (Airflow) |
| CDC (log-based change capture) | M | Approve | H | Det | CDC platform connector | No | V3 |
| Streaming ingestion | L | Approve | H | Det | Streaming connector | No | V3 |

## 2. Discovery and understanding

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Metadata discovery (databases, schemas, tables, files) | VH | None | L | Det | `discover_assets` | Core | — |
| Schema discovery (columns, types, constraints, comments) | VH | None | L | Det | `describe_asset` | Core | — |
| Relevance selection (which assets matter for a requirement) | H | Review | M | Det+LLM | `select_relevant_assets` (subset-validated) | Core | — |
| Profiling (nulls, distinct, ranges, top-k, distributions) | VH | None | L | Det | `profile_dataset` | Core | — |
| Sampling (bounded, masked) | VH | None | M (privacy) | Det | `sample_dataset` | Core | — |
| Key inference (candidate PKs) | H | Review | M | Det (uniqueness) + LLM (naming hints) | `profile_dataset` | Core | — |
| Relationship inference (candidate FKs, join paths) | H | Review | M | Det (inclusion dependencies) + LLM | `profile_dataset`, `execute_query` | Core | — |
| Business semantics understanding (what is a "customer") | M | Decide when ambiguous | H | LLM | `interpret_requirement`, clarification | Core (with clarification gate) | — |
| Schema mapping (source → target) | H | Review | M | Det+LLM | `propose_model_design` | Core | — |

## 3. Transformation development

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Data cleaning rules (trim, case, null handling, standardization) | VH | Review | L | Det+LLM | `generate_transformation`, SQL safety | Core | — |
| Deduplication logic | H | Review (identity rule) | M | Det+LLM | profiles, `generate_transformation` | Core | — |
| Data transformation (joins, derivations, aggregations) | VH | Review | M | Det+LLM | `generate_transformation`, `validate_query` | Core | — |
| SQL development | VH | Review | M | Det+LLM | `validate_query`, `execute_query` | Core | — |
| dbt development (models, YAML, tests, docs, dependency-aware) | H | Review | M | Det+LLM | dbt connector, `create_transformation` | Core | — |
| Python development (transformations, utilities) | H | Review | M | Det+LLM | Python generation + sandboxed test run | Stub | V2 |
| Spark processing | M | Review | M | Det+LLM | Spark platform connector | No | V3 |
| Incremental processing (strategy, keys, watermarks) | H | Review | M | Det (rule table) + LLM | `propose_model_design` | Core | — |
| Late-arriving data handling | H | Review | M | Det+LLM | design rules | Core (demo scenario) | — |

## 4. Data modelling

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Layered warehouse design (staging / intermediate / marts) | H | Review | M | Det rule table | `propose_model_design` | Core | — |
| Medallion mapping (bronze/silver/gold) | H | Review | L | Det | same | Core (naming option) | — |
| Dimensional modelling (star) | H | Review / Approve when flagged | M | Det rule table + LLM entity mapping | same | Core | — |
| Facts (grain, additive measures) | H | Review | M | Det (grain check vs profiles) + LLM | same | Core | — |
| Dimensions (conformed, surrogate keys) | H | Review | M | Det+LLM | same | Core | — |
| Slowly changing dimensions (type 1/2) | H | Decide history policy if unclear | M | Det rule + LLM | dbt snapshots / SCD macros | Core (SCD2 on customer, plan) | — |
| Snowflake schema (normalized dimensions) | M | Approve | M | Det rule | same | Stub (rule exists) | V2 |
| Data marts | H | Review | L | Det+LLM | same | Core (one mart) | — |
| Data Vault (hubs, links, satellites) | M | Approve | H | Det rule (detect) + LLM | same + Vault templates | Partial (recommend only) | V2 |

## 5. Quality, testing, reconciliation

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Test generation (uniqueness, not-null, accepted values, relationships) | VH | Review | L | Det (from design) + LLM (business assertions) | `create_transformation` (tests) | Core | — |
| Test execution | VH | None | L | Det | `run_tests` | Core | — |
| Schema drift detection | VH | None | M | Det | `describe_asset` diff vs snapshot | Core | — |
| Freshness checks | VH | None | L | Det | `execute_query` | Core | — |
| Reconciliation (source vs target totals, counts) | VH | Review | M | Det | Quality Engine | Core | — |
| Distribution shift detection | H | Review | M | Det (stat tests) | profiles over time | Partial | V2 |
| Business assertion tests | M | Decide | M | LLM proposes, human confirms | tests | Core (with review) | — |

## 6. Orchestration and operations

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Orchestration (run pipeline in order) | VH | None | M | Det | `run_pipeline`, dbt DAG | Core (dbt) | V2 Airflow |
| Scheduling | H | Approve (production schedule) | M | Det | orchestration connector | No | V2 |
| Dependency management | VH | None | L | Det | dbt manifest | Core | — |
| Failure detection | VH | None | L | Det | run results, connector errors | Core | — |
| Failure classification | VH | None | M | Det (LLM suggestion for UNKNOWN only) | Failure Classifier | Core | — |
| Failure diagnosis (root cause) | H | Review | M | Det evidence + LLM | `diagnose_failure` | Core | — |
| Repair (bounded) | H | Informed; approve if not in repairable class | H | LLM proposes, Det bounds/validates | Repair Engine | Core | — |
| Incident diagnosis (production) | M | Decide | H | Det+LLM | monitors, logs | No | V3 |

## 7. Optimization and cost

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Execution metrics collection | VH | None | L | Det | `get_execution_metrics` | Core | — |
| Cost metrics collection | VH | None | L | Det | `get_cost_metrics` | Core | — |
| Query optimization (rewrite, clustering, pruning) | M | Review | M | Det (explain plans) + LLM | `validate_query` (explain), metrics | Partial (recommendations) | V2 actions |
| Warehouse optimization (sizing, auto-suspend, clustering keys) | M | Approve (cost impact) | H | Det+LLM | Snowflake admin capabilities | No | V2 |
| Cost optimization (materialization strategy, incremental) | H | Review | M | Det rule table | design rules | Core (materialization choice) | — |

## 8. Documentation, lineage, governance

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Model and column documentation | VH | Review | L | LLM (from design + profiles), Det structure | `generate_documentation` | Core | — |
| Run summaries / PR descriptions | VH | Review | L | LLM | same | Core | — |
| Lineage (model-level) | VH | None | L | Det | dbt manifest | Core | — |
| Lineage (column-level) | H | None | L | Det (SQL parsing) | sqlglot | Core (best effort) | — |
| Governance (classification, retention, access policies) | L | Decide | C | Det (classification hints) | catalog connector | Partial (PII column tagging heuristics) | V3 |
| Catalog publication | H | Review | L | Det | catalog connector | No | V3 |

## 9. Delivery

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Git workflow (branch, commit, push) | VH | Review | M | Det | `prepare_git_change` | Core | — |
| Pull request preparation | VH | Review + merge | M | Det + LLM (description) | `prepare_pull_request` | Core | — |
| CI / CD (pipeline definitions, checks) | H | Review | M | Det | GitHub Actions templates | Partial (dbt CI template in PR) | V2 |
| Deployment (staging) | H | Approve operation subject | H | Det | `deploy_staging` | Stub (gated, staging-like target) | V2 |
| Deployment (production) | M | Approve operation subject | C | Det | `deploy_production` (disabled V1) | No | V3 |
| Rollback | M | Approve operation subject | C | Det | platform-specific compensation/rollback capability | No | V3 |

## 10. Monitoring

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Pipeline health monitoring | H | Informed | M | Det | `monitor` | Stub (register definitions) | V2 |
| Freshness monitoring | H | Informed | L | Det | `monitor` | Stub | V2 |
| Data quality monitoring | H | Informed | M | Det | `monitor`, `run_tests` | Stub | V2 |
| Cost and performance monitoring | H | Informed | M | Det | `get_cost_metrics` | Partial (per-workflow) | V2 |
| Anomaly detection | M | Review | M | Det (stat) | metrics history | No | V3 |

## 11. Analytics enablement

| Capability | Automation | Human | Risk | Det/LLM | Required tools | MVP | Future |
|---|---|---|---|---|---|---|---|
| Expose data products to BI (grants, views) | H | Approve | M | Det | `create_dataset`, `deploy_staging` | Partial (mart created in DEV) | V2 |
| Semantic layer (metrics definitions) | M | Decide (metric semantics) | M | Det+LLM | dbt semantic layer / BI connector | No | V2 |
| BI integration (Power BI, Tableau, Looker) | M | Approve | M | Det | BI connectors | No | V3 |
| Natural language analysis over trusted data | H | Review | M | Det+LLM | `execute_query` (READ) | No (product extension) | V3 |

---

## 12. Cross-cutting rules derived from this map

1. Anything classified **Det** must be implemented without an LLM in the execution path.
2. Anything **Det+LLM** must have a deterministic validator that can reject the LLM output
   and a defined fallback (replan, clarification, or block).
3. Anything with Human = **Approve** maps to an `APPROVAL_REQUIRED` policy outcome; the
   permission model in `docs/PERMISSION_MODEL.md` encodes it.
4. Anything with Risk **C** is either disabled in V1 or approval-gated with no automation
   of the decision.
5. MVP **Core** rows define the acceptance scope in `docs/MVP_SCOPE.md` §4.
