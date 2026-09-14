from __future__ import annotations

from uuid import UUID

import pytest

from aide.capabilities.io import GenerateTransformationInput, TransformationFile
from aide.generation.validate import GeneratedSqlInvalid, validate_generated_files
from aide.generation.vantara import INTERVIEW_REQUIRED_MODELS, generate_vantara_transformation
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.modelling.demo_design import vantara_model_design

WORKFLOW = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _input() -> GenerateTransformationInput:
    return GenerateTransformationInput(workflow_id=WORKFLOW, model_design=vantara_model_design())


def test_interview_required_models_match_modelling_contract() -> None:
    assert INTERVIEW_REQUIRED_MODELS == REQUIRED_DEMO_MODELS


def test_identical_inputs_produce_identical_artifacts() -> None:
    first = generate_vantara_transformation(_input())
    second = generate_vantara_transformation(_input())
    assert first.content_sha256 == second.content_sha256
    assert first.files == second.files
    assert set(REQUIRED_DEMO_MODELS).issubset(set(first.model_names))
    joined = "\n".join(item.content for item in first.files)
    assert "VANTARA_RAW" not in joined
    assert "'***'" in joined
    assert "INVOICE_STATUS" in joined


def test_validation_rejects_leftover_jinja() -> None:
    with pytest.raises(GeneratedSqlInvalid, match="unresolved jinja"):
        validate_generated_files(
            (
                TransformationFile(
                    path="models/staging/bad.sql",
                    content="select {{ var('secret') }} as x\n",
                ),
            )
        )


def test_validation_rejects_invalid_sql() -> None:
    with pytest.raises(GeneratedSqlInvalid, match="invalid SQL"):
        validate_generated_files(
            (
                TransformationFile(
                    path="models/staging/bad.sql",
                    content="SELEC FROM nowhere\n",
                ),
            )
        )
