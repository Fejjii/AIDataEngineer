"""Pytest 9 rejects nested pytest_plugins; evaluation conftest must re-export fixtures."""

from __future__ import annotations

from pathlib import Path


def test_evaluation_conftest_does_not_declare_pytest_plugins() -> None:
    text = Path("tests/evaluation/conftest.py").read_text(encoding="utf-8")
    assert "pytest_plugins" not in text
    assert "migrated_database as migrated_database" in text
    assert "database_engine as database_engine" in text
    assert "session_factory as session_factory" in text
