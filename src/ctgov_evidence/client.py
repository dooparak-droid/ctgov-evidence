"""ClinicalTrials.gov API v2 client: search with paging, fetch by ID, retries, throttling."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "https://clinicaltrials.gov/api/v2"
NCT_RE = re.compile(r"^NCT\d{8}$")
PHASE_CODES = {
    "EARLY1": "EARLY_PHASE1",
    "EARLY_PHASE1": "EARLY_PHASE1",
    "1": "PHASE1",
    "2": "PHASE2",
    "3": "PHASE3",
    "4": "PHASE4",
    "PHASE1": "PHASE1",
    "PHASE2": "PHASE2",
    "PHASE3": "PHASE3",
    "PHASE4": "PHASE4",
    "NA": "NA",
}
RETRY_STATUS = {429, 500, 502, 503, 504}


class RegistryError(RuntimeError):
    """The registry returned an error that is not a missing record."""


class NotFoundError(RegistryError):
    """No record exists for the requested NCT ID."""


@dataclass
class SearchResult:
    studies: list[dict[str, Any]] = field(default_factory=list)
    total_count: int | None = None
    truncated: bool = False


def normalise_phase(value: str) -> str:
    key = value.strip().upper().replace(" ", "")
    if key.startswith("PHASE") and key[5:].isdigit():
        key = f"PHASE{key[5:]}"
    try:
        return PHASE_CODES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown phase {value!r}; use 1, 2, 3, 4, early1 or na") from exc


def normalise_status(value: str) -> str:
    return value.strip().upper().replace(" ", "_").replace("-", "_")


def build_search_params(
    condition: str | None,
    intervention: str | None,
    phases: list[str] | None,
    statuses: list[str] | None,
    page_size: int,
) -> dict[str, str]:
    params: dict[str, str] = {"pageSize": str(page_size), "countTotal": "true"}
    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    if statuses:
        params["filter.overallStatus"] = ",".join(normalise_status(s) for s in statuses)
    if phases:
        codes = [normalise_phase(p) for p in phases]
        params["filter.advanced"] = "AREA[Phase](" + " OR ".join(codes) + ")"
    return params


class CTGovClient:
    """Thin wrapper over the v2 API. Pass ``transport`` to substitute a mock in tests."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        min_interval: float = 0.2,
        backoff: float = 1.0,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": "ctgov-evidence/0.1 (+https://github.com)"},
        )
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._backoff = backoff
        self._last_request = 0.0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> CTGovClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code not in RETRY_STATUS:
                    return response
                last_error = RegistryError(f"HTTP {response.status_code} from {path}")
            if attempt < self._max_retries:
                time.sleep(self._backoff * 2**attempt)
        raise RegistryError(f"Request to {path} failed after retries: {last_error}")

    def get_study(self, nct_id: str) -> dict[str, Any]:
        nct_id = nct_id.strip().upper()
        if not NCT_RE.match(nct_id):
            raise ValueError(f"{nct_id!r} is not a valid NCT ID (NCT plus 8 digits)")
        response = self._get(f"/studies/{nct_id}")
        if response.status_code in (400, 404):
            raise NotFoundError(f"No record found for {nct_id}")
        if response.status_code != 200:
            raise RegistryError(f"HTTP {response.status_code} for {nct_id}")
        return response.json()

    def search(
        self,
        *,
        condition: str | None = None,
        intervention: str | None = None,
        phases: list[str] | None = None,
        statuses: list[str] | None = None,
        page_size: int = 100,
        max_studies: int = 200,
    ) -> SearchResult:
        """Return up to ``max_studies`` records, following ``nextPageToken``."""
        if not (condition or intervention):
            raise ValueError("A search needs a condition, an intervention, or both")
        page_size = max(1, min(page_size, 1000, max_studies))
        params = build_search_params(condition, intervention, phases, statuses, page_size)
        result = SearchResult()
        while True:
            response = self._get("/studies", params)
            if response.status_code != 200:
                raise RegistryError(
                    f"HTTP {response.status_code} for search: {response.text[:200]}"
                )
            page = response.json()
            if result.total_count is None:
                result.total_count = page.get("totalCount")
            result.studies.extend(page.get("studies", []))
            token = page.get("nextPageToken")
            if len(result.studies) >= max_studies:
                result.studies = result.studies[:max_studies]
                result.truncated = bool(token) or (
                    result.total_count is not None and result.total_count > max_studies
                )
                break
            if not token:
                break
            params = {**params, "pageToken": token}
            params.pop("countTotal", None)
        return result
