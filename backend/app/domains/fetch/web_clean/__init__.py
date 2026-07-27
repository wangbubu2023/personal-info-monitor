"""Explainable, template-aware web article cleaning pipeline."""

from .contracts import CleanCandidate, CleanInput, CleanResult, CleanTrace, TemplateSpec
from .extractors import WebDocumentExtractor

__all__ = [
    "CleanCandidate",
    "CleanInput",
    "CleanResult",
    "CleanTrace",
    "TemplateSpec",
    "WebDocumentExtractor",
]
