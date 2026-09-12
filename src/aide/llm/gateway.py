"""Thin LLM gateway. DE 002C uses replay only."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from aide.llm.replay import replay_structured


class LlmGateway:
    def complete(
        self,
        capability_id: str,
        schema: type[BaseModel],
        *,
        prompt_values: Mapping[str, object],
        extra: Mapping[str, Any] | None = None,
    ) -> BaseModel:
        return replay_structured(
            capability_id,
            schema,
            prompt_values=prompt_values,
            extra=extra,
        )
