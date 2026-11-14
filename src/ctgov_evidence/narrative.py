"""Optional LLM paragraph written from structured trials only (never raw registry JSON)."""

from __future__ import annotations

import json
import os

from .models import Evidence
from .summarise import phase_label

DEFAULT_MODEL = os.environ.get("CTGOV_EVIDENCE_MODEL", "claude-sonnet-5-5")

SYSTEM_PROMPT = """You write short evidence summaries from structured clinical trial records.

Rules:
- Use only the facts in the JSON you are given. Do not add outside knowledge, efficacy
  claims, or interpretation.
- Write one paragraph of 4 to 8 sentences.
- Every sentence must end with a citation in square brackets listing the NCT IDs it is
  about, for example [NCT01234567] or [NCT01234567, NCT07654321].
- Cite exactly the trials a sentence is about. If a sentence gives a count, cite exactly
  the trials counted.
- Quote numbers, phases, statuses and sponsor names exactly as they appear in the records.
- If a value is null, say it is not reported. Do not estimate it.
"""


class NarrativeUnavailable(RuntimeError):
    """No API key, or the optional ``anthropic`` package is not installed."""


def compact_trials(evidence: Evidence, max_outcomes: int = 3) -> list[dict]:
    """Values only, no source paths, trimmed so a 100-trial set stays small."""
    out = []
    for t in evidence.trials:
        outcomes = [o.measure for o in (t.primary_outcomes.value or []) if o.measure]
        out.append(
            {
                "nct_id": t.nct_id,
                "title": t.title.value,
                "sponsor": t.sponsor.value,
                "phase": phase_label(t.phase.value),
                "status": t.status.value,
                "enrollment": t.enrollment.value,
                "enrollment_type": t.enrollment_type.value,
                "start_date": t.start_date.value,
                "primary_completion_date": t.primary_completion_date.value,
                "design": [
                    x for x in (t.study_type.value, t.allocation.value, t.masking.value) if x
                ],
                "interventions": t.interventions.value,
                "primary_outcomes": outcomes[:max_outcomes],
                "results_posted": t.has_results.value,
            }
        )
    return out


def generate_narrative(evidence: Evidence, *, model: str | None = None) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NarrativeUnavailable("ANTHROPIC_API_KEY is not set")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise NarrativeUnavailable(
            "The anthropic package is not installed; run pip install 'ctgov-evidence[narrative]'"
        ) from exc

    payload = {"n_trials": len(evidence.trials), "trials": compact_trials(evidence)}
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text").strip()
