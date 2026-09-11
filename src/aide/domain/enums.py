"""Shared domain enumerations."""

from __future__ import annotations

from enum import Enum


class TargetEnv(str, Enum):
    DEV = "DEV"
    STAGING = "STAGING"
    PROD = "PROD"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalRule(str, Enum):
    NEVER = "NEVER"
    IF_POLICY_FLAGS = "IF_POLICY_FLAGS"
    ALWAYS = "ALWAYS"
    DISABLED = "DISABLED"
