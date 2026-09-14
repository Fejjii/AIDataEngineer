from __future__ import annotations

from aide.domain.repair import (
    MAX_APPLIED_REPAIRS_PER_TASK,
    MAX_APPLIED_REPAIRS_PER_WORKFLOW,
    MAX_POST_REPAIR_REVALIDATIONS,
    MAX_RECURSIVE_REPAIRS,
    MAX_REPAIR_PROPOSALS,
)
from aide.repair.budget import (
    application_exhausted,
    proposals_exhausted,
    recursive_forbidden,
    revalidation_exhausted,
)


def test_interview_mvp_repair_limits() -> None:
    assert MAX_REPAIR_PROPOSALS == 2
    assert MAX_APPLIED_REPAIRS_PER_TASK == 1
    assert MAX_APPLIED_REPAIRS_PER_WORKFLOW == 1
    assert MAX_POST_REPAIR_REVALIDATIONS == 1
    assert MAX_RECURSIVE_REPAIRS == 0
    assert not proposals_exhausted(1)
    assert proposals_exhausted(2)
    assert not application_exhausted(0)
    assert application_exhausted(1)
    assert not revalidation_exhausted(0)
    assert revalidation_exhausted(1)
    assert recursive_forbidden(False)
    assert recursive_forbidden(True)
