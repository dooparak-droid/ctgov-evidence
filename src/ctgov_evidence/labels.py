"""Display labels shared by the summary, the gap check and the verifier."""

PHASE_ORDER = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"]
PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "Not applicable",
}
NOT_REPORTED = "Not reported"


def phase_label(phases: list[str] | None) -> str:
    """One label per trial, so counts by phase sum to the number of trials."""
    if not phases:
        return NOT_REPORTED
    ordered = sorted(phases, key=lambda p: PHASE_ORDER.index(p) if p in PHASE_ORDER else 99)
    return " / ".join(PHASE_LABELS.get(p, p) for p in ordered)
