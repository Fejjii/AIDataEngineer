from __future__ import annotations

import pkgutil
from collections.abc import Iterator

import aide


def _walk_modules() -> Iterator[str]:
    prefix = aide.__name__ + "."
    for module in pkgutil.walk_packages(aide.__path__, prefix):
        yield module.name


def test_import_every_module() -> None:
    imported: list[str] = []
    for name in _walk_modules():
        __import__(name)
        imported.append(name)
    assert imported
    assert any(name.startswith("aide.domain") for name in imported)
    assert any(name.startswith("aide.policy") for name in imported)
    assert any(name.startswith("aide.connectors.base") for name in imported)
