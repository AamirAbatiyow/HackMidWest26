"""Deterministic checks: bank change (account takeover), duplicates/splits, trust scoring."""

from .bank_change import detect_bank_change
from .dup_split import Candidate, detect_dup_split
from .scoring import ScoreInputs, ScoreResult, score

__all__ = ["Candidate", "ScoreInputs", "ScoreResult", "detect_bank_change", "detect_dup_split", "score"]
