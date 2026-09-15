"""Interview MVP evaluation scenario catalog. Deterministic IDs only."""

from __future__ import annotations

from aide.domain.evaluation import EvaluationCategory

# Required offline scenarios per scorecard category. Live-only IDs are optional.
CATEGORY_REQUIRED: dict[EvaluationCategory, tuple[str, ...]] = {
    EvaluationCategory.FUNCTIONAL_CORRECTNESS: ("E-HP-01",),
    EvaluationCategory.REPAIR_CORRECTNESS: ("E-HP-01",),
    EvaluationCategory.REPAIR_SAFETY: (
        "E-SF-SECOND",
        "E-SF-RECUR",
        "E-SF-BROADER",
        "E-SF-TABLE",
        "E-SF-COL",
        "E-SF-TYPE",
        "E-SF-TEST",
    ),
    EvaluationCategory.POLICY_ENFORCEMENT: ("E-SF-PERM", "E-SF-PROD", "E-SF-BYPASS"),
    EvaluationCategory.LEAST_PRIVILEGE: ("E-LP-RO", "E-LP-GRANT", "E-SF-RAW"),
    EvaluationCategory.EVIDENCE_INTEGRITY: (
        "E-TM-SECTION",
        "E-TM-BUNDLE",
        "E-TM-WF",
        "E-TM-SNAP",
        "E-TM-MODE",
        "E-TM-DRIFT",
        "E-TM-HASH",
    ),
    EvaluationCategory.DETERMINISM: ("E-RP-01", "E-BM-01"),
    EvaluationCategory.RECOVERY: (
        "E-RC-PHASE",
        "E-RC-INTENT",
        "E-RC-BUDGET",
        "E-RC-EVID",
        "E-RC-VER",
        "E-RC-AMBIG",
    ),
    EvaluationCategory.TEST_SUCCESS: ("E-HP-01", "E-FI-TEST"),
    EvaluationCategory.DATA_QUALITY: ("E-HP-01", "E-FI-QUAL"),
    EvaluationCategory.RECONCILIATION: ("E-HP-01",),
    EvaluationCategory.VERIFIER_CORRECTNESS: ("E-HP-01", "E-PR-MIX", "E-PR-REAL", "E-PR-MOCK"),
    EvaluationCategory.PERFORMANCE: ("E-PF-01",),
    EvaluationCategory.HUMAN_INTERVENTION_COUNT: ("E-HP-01",),
    EvaluationCategory.KNOWN_LIMITATIONS: ("E-LIM-01",),
}

CATEGORY_OPTIONAL: dict[EvaluationCategory, tuple[str, ...]] = {
    EvaluationCategory.LEAST_PRIVILEGE: ("E-LP-LIVE",),
}

FAILURE_INJECTION_STAGES: tuple[tuple[str, str], ...] = (
    ("E-FI-DISC", "discover_assets"),
    ("E-FI-PROF", "profile_estate"),
    ("E-FI-GEN", "create_transformation"),
    ("E-FI-PARSE", "parse_transformation"),
    ("E-FI-COMP", "compile_transformation"),
    ("E-FI-EXEC", "execute_transformation"),
    ("E-FI-TEST", "run_tests"),
    ("E-FI-QUAL", "validate_interview_quality"),
    ("E-FI-DRIFT", "detect_schema_drift"),
    ("E-FI-REPAIR", "repair_apply"),
    ("E-FI-POST", "post_repair_validation"),
    ("E-FI-EVID", "evidence_persistence"),
    ("E-FI-VER", "verifier"),
)


__all__ = ["CATEGORY_OPTIONAL", "CATEGORY_REQUIRED", "FAILURE_INJECTION_STAGES"]
