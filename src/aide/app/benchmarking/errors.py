"""Errors for the synthetic Interview demo HTTP surface."""


class DemoBusyError(Exception):
    """Raised when a synthetic demo is already running on this process."""


__all__ = ["DemoBusyError"]
