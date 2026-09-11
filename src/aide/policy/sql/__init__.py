"""SQL safety classifier kernel."""

from aide.policy.sql.classifier import classify_sql
from aide.policy.sql.dialects import DialectId, registered_dialects

__all__ = ["DialectId", "classify_sql", "registered_dialects"]
