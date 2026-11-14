"""Structured, source-traced evidence summaries from ClinicalTrials.gov."""

from .models import Evidence, Outcome, Query, Sourced, Summary, Trial
from .pipeline import build_evidence

__version__ = "0.1.0"

__all__ = [
    "Evidence",
    "Outcome",
    "Query",
    "Sourced",
    "Summary",
    "Trial",
    "build_evidence",
]
