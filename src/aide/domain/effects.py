"""Invocation effect semantics.

These describe invocation safety. They are not permission to blind-retry.
"""

from __future__ import annotations

from enum import Enum


class EffectSemantics(str, Enum):
    SIDE_EFFECT_FREE = "SIDE_EFFECT_FREE"
    EXTERNALLY_DEDUPLICATED = "EXTERNALLY_DEDUPLICATED"
    PROVEN_CONVERGENT = "PROVEN_CONVERGENT"
    NON_IDEMPOTENT = "NON_IDEMPOTENT"

    @property
    def is_side_effecting(self) -> bool:
        return self is not EffectSemantics.SIDE_EFFECT_FREE
