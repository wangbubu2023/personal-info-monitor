"""Compatibility shim for the canonical score-domain ranking module."""

from app.domains.score.ranking import RankingService, _jaccard, _tokenize

__all__ = ["RankingService", "_jaccard", "_tokenize"]
