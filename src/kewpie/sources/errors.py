"""Typed errors for source adapters.

The collect pipeline catches these per source and keeps going: one
mis-configured or rate-limited source must never abort a whole run.
"""
from __future__ import annotations


class SourceError(Exception):
    """Base class for all source-adapter errors."""


class ConfigError(SourceError):
    """Missing/invalid configuration (e.g. required field absent)."""


class AuthError(SourceError):
    """Missing or invalid credentials (401/403, or a 200-with-error body)."""


class RateLimitError(SourceError):
    """Rate limited (429). Carries an optional Retry-After hint (seconds)."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class QuotaError(SourceError):
    """Daily/monthly quota exhausted; back off until reset, do not hot-retry."""


class NotFoundError(SourceError):
    """Endpoint not found / DNS failure (404 or connection error)."""


class TransientError(SourceError):
    """Temporary server-side failure (5xx / timeout); safe to retry later."""
