"""Errors that distinguish missing evidence from terminal patent verdicts."""

from __future__ import annotations


class EvidenceFailure(RuntimeError):
    """Raised when a score cannot be supported by retrieved evidence."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}
