from __future__ import annotations

import pytest
from pydantic import ValidationError

from aide.capabilities.io import ExecuteQueryOutput
from aide.connectors.base.reconcile import EffectFound
from aide.quality.checks import validate_query_result


def test_ambiguous_success_cannot_pass_without_validated_output() -> None:
    found = EffectFound(output={"not": "a query result"}, external_ref="q")
    with pytest.raises(ValidationError):
        ExecuteQueryOutput.model_validate(found.output)
    with pytest.raises(ValidationError):
        validate_query_result(
            ExecuteQueryOutput.model_validate(found.output),
            expected_columns=(),
        )
