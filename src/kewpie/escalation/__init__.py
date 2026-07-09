"""Signal-driven escalation ladder: cheap HTTP -> impersonation -> browser."""
from __future__ import annotations

from .fetcher import Fetcher
from .ladder import EscalatingFetcher
from .policy import PerHostPolicyStore
from .tiers import BrowserTier, CheapHttpTier, ImpersonateTier

__all__ = [
    "EscalatingFetcher", "Fetcher", "PerHostPolicyStore",
    "CheapHttpTier", "ImpersonateTier", "BrowserTier",
]
