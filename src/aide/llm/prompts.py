"""Versioned Jinja2 prompt loader."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template


def prompt_root() -> Path:
    return Path(str(resources.files("aide"))) / "prompts"


@lru_cache(maxsize=32)
def load_prompt(capability_id: str, version: int = 1) -> Template:
    path = prompt_root() / capability_id / f"v{version}.md.j2"
    if not path.is_file():
        raise FileNotFoundError(f"prompt artifact missing: {path}")
    env = Environment(undefined=StrictUndefined, autoescape=False)
    return env.from_string(path.read_text(encoding="utf-8"))


def render_prompt(capability_id: str, version: int = 1, **values: object) -> str:
    return load_prompt(capability_id, version).render(**values)
