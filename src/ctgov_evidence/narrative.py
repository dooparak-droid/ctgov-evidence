"""Optional LLM paragraph written from structured trials only (never raw registry JSON).

Two providers are supported. Gemini is called over plain HTTPS with ``httpx``, so it needs no
extra package. Anthropic needs the ``narrative`` extra. The verifier in ``verify.py`` works on
the returned text and does not depend on which provider wrote it.
"""

from __future__ import annotations

import json
import os
import time

import httpx

from .models import Evidence
from .summarise import phase_label

DEFAULT_MODELS = {
    "gemini": os.environ.get("CTGOV_EVIDENCE_GEMINI_MODEL", "gemini-3.5-flash"),
    "anthropic": os.environ.get("CTGOV_EVIDENCE_MODEL", "claude-sonnet-5-5"),
}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PROVIDERS = ("gemini", "anthropic")
FALLBACK_GEMINI_MODEL = "gemini-3.1-flash-lite"
FALLBACK_AFTER = 2  # failed attempts on the primary model before switching
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5

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
    """No API key, or an optional package is not installed."""


class NarrativeError(RuntimeError):
    """The provider returned an error or an empty response."""


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


def _gemini_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def detect_provider() -> str | None:
    """Gemini first (free tier), then Anthropic. None if no key is set."""
    if _gemini_key():
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def _call_gemini(
    payload: str,
    model: str,
    api_key: str,
    http_client: httpx.Client | None = None,
    fallback: str | None = None,
) -> str:
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": payload}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    client = http_client or httpx.Client(timeout=60.0)
    response = None
    try:
        for attempt in range(MAX_ATTEMPTS):
            try:
                # The key travels in a header, never in the URL, so it cannot appear in errors.
                use = fallback if fallback and attempt >= FALLBACK_AFTER else model
                response = client.post(
                    GEMINI_URL.format(model=use),
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise NarrativeError(
                        f"Could not reach the Gemini API ({type(exc).__name__})"
                    ) from exc
            else:
                if response.status_code not in RETRY_STATUS:
                    break
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 * 2**attempt)
    finally:
        if http_client is None:
            client.close()
    assert response is not None
    if response.status_code != 200:
        try:
            detail = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = response.text[:200]
        raise NarrativeError(f"Gemini API returned HTTP {response.status_code}: {detail}")
    data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
        raise NarrativeError(f"Gemini returned no text ({reason})") from exc
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise NarrativeError("Gemini returned an empty response")
    return text


def _call_anthropic(payload: str, model: str) -> str:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise NarrativeUnavailable(
            "The anthropic package is not installed; run pip install 'ctgov-evidence[narrative]'"
        ) from exc
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": payload}],
    )
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text").strip()


def generate_narrative(
    evidence: Evidence,
    *,
    provider: str | None = None,
    model: str | None = None,
    http_client: httpx.Client | None = None,
    api_key: str | None = None,
) -> str:
    """Return a cited paragraph. ``provider`` is 'gemini', 'anthropic' or None for auto.

    ``api_key`` is used for Gemini only. Without it the key is read from the environment.
    """
    if provider not in (None, "auto", *PROVIDERS):
        raise ValueError(f"Unknown provider {provider!r}; use gemini or anthropic")
    if provider in (None, "auto"):
        chosen = "gemini" if api_key else detect_provider()
    else:
        chosen = provider
    if chosen is None:
        raise NarrativeUnavailable("no GEMINI_API_KEY or ANTHROPIC_API_KEY is set")
    payload = json.dumps(
        {"n_trials": len(evidence.trials), "trials": compact_trials(evidence)},
        ensure_ascii=False,
    )
    fallback = FALLBACK_GEMINI_MODEL if chosen == "gemini" and model is None else None
    model = model or DEFAULT_MODELS[chosen]
    if fallback == model:
        fallback = None
    if chosen == "gemini":
        key = api_key or _gemini_key()
        if not key:
            raise NarrativeUnavailable("GEMINI_API_KEY is not set")
        return _call_gemini(payload, model, key, http_client, fallback)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NarrativeUnavailable("ANTHROPIC_API_KEY is not set")
    return _call_anthropic(payload, model)
