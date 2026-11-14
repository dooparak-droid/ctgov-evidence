"""Pydantic schema. Every extracted value carries the path it was read from."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Sourced(BaseModel, Generic[T]):
    """A value plus the location in the registry record it came from.

    A missing field is stored as ``value=None`` with the path that was looked up.
    """

    value: T | None = None
    source: str


class Outcome(BaseModel):
    measure: str | None = None
    time_frame: str | None = None


class Trial(BaseModel):
    nct_id: str
    title: Sourced[str]
    sponsor: Sourced[str]
    sponsor_class: Sourced[str]
    study_type: Sourced[str]
    phase: Sourced[list[str]]
    status: Sourced[str]
    enrollment: Sourced[int]
    enrollment_type: Sourced[str]
    start_date: Sourced[str]
    primary_completion_date: Sourced[str]
    completion_date: Sourced[str]
    allocation: Sourced[str]
    masking: Sourced[str]
    conditions: Sourced[list[str]]
    interventions: Sourced[list[str]]
    primary_outcomes: Sourced[list[Outcome]]
    has_results: Sourced[bool]


class Query(BaseModel):
    """What was asked of the registry. Either a search or a list of NCT IDs."""

    condition: str | None = None
    intervention: str | None = None
    phase: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    nct_ids: list[str] = Field(default_factory=list)
    max_studies: int = 200


class CountedItem(BaseModel):
    name: str
    n_trials: int
    nct_ids: list[str]


class EnrollmentGroup(BaseModel):
    n_trials: int = 0
    total: int = 0


class Summary(BaseModel):
    n_trials: int
    by_phase: dict[str, int]
    by_status: dict[str, int]
    by_study_type: dict[str, int]
    enrollment: dict[str, EnrollmentGroup]
    n_enrollment_missing: int
    sponsors: list[CountedItem]
    primary_outcomes: list[CountedItem]
    n_results_posted: int
    n_results_not_posted: int
    n_results_unknown: int
    results_posted_nct_ids: list[str]


class Evidence(BaseModel):
    query: Query
    retrieved_at: datetime
    total_found: int | None = None
    truncated: bool = False
    not_found: list[str] = Field(default_factory=list)
    trials: list[Trial]
    summary: Summary
