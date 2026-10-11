"""Deterministic sender identity checks (SPF/DKIM/DMARC, lookalike domains, reply-to)."""

from .auth_results import parse_auth_results
from .check import check_sender
from .lookalike import check_lookalike, homoglyph_normalize, registrable_label

__all__ = [
    "check_lookalike",
    "check_sender",
    "homoglyph_normalize",
    "parse_auth_results",
    "registrable_label",
]
