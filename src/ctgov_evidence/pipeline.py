"""``build_evidence``: query in, ``Evidence`` out."""

from __future__ import annotations

from datetime import UTC, datetime

from .client import CTGovClient, NotFoundError
from .extract import extract_trial
from .models import Evidence, Query
from .summarise import summarise


def build_evidence(query: Query, *, client: CTGovClient | None = None) -> Evidence:
    """Fetch the records named or matched by ``query`` and build the evidence object.

    Pass ``client`` to reuse a configured (or mocked) client. Otherwise one is created
    and closed here.
    """
    owns_client = client is None
    client = client or CTGovClient()
    try:
        raws: list[dict] = []
        not_found: list[str] = []
        total_found: int | None = None
        truncated = False
        if query.nct_ids:
            seen: set[str] = set()
            for nct in query.nct_ids:
                nct = nct.strip().upper()
                if nct in seen:
                    continue
                seen.add(nct)
                try:
                    raws.append(client.get_study(nct))
                except NotFoundError:
                    not_found.append(nct)
            total_found = len(raws)
        else:
            result = client.search(
                condition=query.condition,
                intervention=query.intervention,
                phases=query.phase,
                statuses=query.status,
                max_studies=query.max_studies,
            )
            raws = result.studies
            total_found = result.total_count
            truncated = result.truncated
    finally:
        if owns_client:
            client.close()

    trials = [extract_trial(r) for r in raws]
    retrieved_at = datetime.now(UTC)
    return Evidence(
        query=query,
        retrieved_at=retrieved_at,
        total_found=total_found,
        truncated=truncated,
        not_found=not_found,
        trials=trials,
        summary=summarise(trials, as_of=retrieved_at.date()),
    )
