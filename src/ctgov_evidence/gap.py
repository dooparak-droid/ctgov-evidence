"""Results gap check: finished interventional trials with no results posted after the deadline.

US law (FDAAA 801) generally expects the sponsors of "applicable clinical trials" to submit
summary results within 12 months of the primary completion date. The registry does not say
whether a given trial is legally covered, so flagged trials are sorted by how likely that is.
A flag means "no results posted where they would normally be expected", not a finding of
non-compliance. Results may exist in a journal, and sponsors can certify a delay.
"""

from __future__ import annotations

import calendar
from datetime import date

from .labels import phase_label
from .models import GapItem, ResultsGap, Trial

DEADLINE_MONTHS = 12
FINISHED = {"COMPLETED", "TERMINATED"}
GROUP_ORDER = ["likely_applicable", "cannot_tell", "probably_not_covered", "probably_exempt"]
GROUP_LABELS = {
    "likely_applicable": "Likely applicable (marked FDA-regulated, not Phase 1 only)",
    "cannot_tell": "Cannot tell (no FDA-regulation flag recorded, usually an older record)",
    "probably_not_covered": "Probably not covered (the registry marks it not FDA-regulated)",
    "probably_exempt": "Probably exempt (Phase 1 only)",
}
DAYS_PER_MONTH = 30.4375
GAP_FILE_COLUMNS = [
    "group",
    "nct_id",
    "title",
    "sponsor",
    "phase",
    "status",
    "primary_completion_date",
    "months_since_primary_completion",
    "reason",
]


def parse_registry_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD or YYYY-MM. A month-only date is taken as the end of that month."""
    if not value:
        return None
    try:
        parts = [int(p) for p in value.split("-")]
        if len(parts) == 3:
            return date(*parts)
        if len(parts) == 2:
            return date(parts[0], parts[1], calendar.monthrange(parts[0], parts[1])[1])
    except (ValueError, TypeError):
        return None
    return None


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _months_between(start: date, end: date) -> float:
    return round((end - start).days / DAYS_PER_MONTH, 1)


def classify(trial: Trial) -> tuple[str, str]:
    phases = set(trial.phase.value or [])
    flags = [trial.fda_regulated_drug.value, trial.fda_regulated_device.value]
    if phases == {"PHASE1"}:
        return "probably_exempt", "Phase 1 trials are generally outside the reporting requirement"
    if True in flags:
        return "likely_applicable", "Marked FDA-regulated and not Phase 1 only"
    if False in flags:
        return "probably_not_covered", "The registry marks this trial as not FDA-regulated"
    return "cannot_tell", "The registry records no FDA-regulation flag for this trial"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def results_gap(trials: list[Trial], as_of: date) -> ResultsGap:
    gap = ResultsGap(as_of=as_of, deadline_months=DEADLINE_MONTHS)
    lags: list[float] = []
    groups: dict[str, list[GapItem]] = {g: [] for g in GROUP_ORDER}

    for t in trials:
        if t.study_type.value != "INTERVENTIONAL":
            gap.n_not_interventional += 1
            continue
        if t.status.value not in FINISHED:
            gap.n_not_finished += 1
            continue
        primary = parse_registry_date(t.primary_completion_date.value)
        if primary is None:
            gap.n_no_primary_completion_date += 1
            continue
        gap.n_finished_interventional += 1
        due = add_months(primary, DEADLINE_MONTHS)

        if t.has_results.value is True:
            gap.n_results_posted += 1
            submitted = parse_registry_date(t.results_first_submitted.value)
            if submitted is not None:
                lags.append(_months_between(primary, submitted))
                if submitted <= due:
                    gap.n_reported_within_deadline += 1
                else:
                    gap.n_reported_late += 1
            continue

        if as_of <= due:
            gap.n_not_yet_due += 1
            continue

        group, reason = classify(t)
        groups[group].append(
            GapItem(
                nct_id=t.nct_id,
                title=t.title.value,
                sponsor=t.sponsor.value,
                phase=phase_label(t.phase.value),
                status=t.status.value,
                primary_completion_date=t.primary_completion_date.value,
                months_since_primary_completion=_months_between(primary, as_of),
                group=group,
                reason=reason,
            )
        )

    gap.groups = {g: items for g, items in groups.items()}
    gap.n_overdue_no_results = sum(len(v) for v in groups.values())
    gap.median_months_to_first_submission = _median(lags)
    return gap


def gap_rows(gap: ResultsGap) -> list[dict[str, str]]:
    rows = []
    for group in GROUP_ORDER:
        for item in gap.groups.get(group, []):
            rows.append(
                {
                    "group": group,
                    "nct_id": item.nct_id,
                    "title": item.title or "",
                    "sponsor": item.sponsor or "",
                    "phase": item.phase,
                    "status": item.status or "",
                    "primary_completion_date": item.primary_completion_date or "",
                    "months_since_primary_completion": str(item.months_since_primary_completion),
                    "reason": item.reason,
                }
            )
    return rows


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def gap_markdown(gap: ResultsGap, heading: str = "##", max_rows: int | None = 15) -> str:
    lines = [f"{heading} Results gap check", ""]
    lines.append(
        f"As of {gap.as_of.isoformat()}. US law generally expects results within "
        f"{gap.deadline_months} months of the primary completion date for applicable trials. "
        "The registry does not say which trials are covered, and a flag below means only that "
        "no results are posted where they would normally be expected."
    )
    lines += [
        "",
        f"- Interventional trials that finished (completed or terminated) with a primary "
        f"completion date: {gap.n_finished_interventional}",
        f"- With results posted: {gap.n_results_posted} "
        f"({gap.n_reported_within_deadline} within the deadline, {gap.n_reported_late} later)",
        "- Median time from primary completion to first results submission: "
        + (
            f"{gap.median_months_to_first_submission} months"
            if gap.median_months_to_first_submission is not None
            else "not available"
        ),
        f"- Not yet due: {gap.n_not_yet_due}",
        f"- Past the deadline with no results posted: {gap.n_overdue_no_results}",
        f"- Not checked: {gap.n_not_interventional} not interventional, "
        f"{gap.n_not_finished} not yet finished, "
        f"{gap.n_no_primary_completion_date} with no primary completion date",
    ]
    for group in GROUP_ORDER:
        items = gap.groups.get(group, [])
        if not items:
            continue
        lines += ["", f"**{GROUP_LABELS[group]}** ({len(items)})", ""]
        lines += [
            "| NCT ID | Sponsor | Phase | Primary completion | Months since |",
            "|---|---|---|---|---|",
        ]
        for i in items[:max_rows]:
            lines.append(
                f"| {i.nct_id} | {_cell(i.sponsor or '')} | {i.phase} | "
                f"{i.primary_completion_date or ''} | {i.months_since_primary_completion} |"
            )
        if max_rows is not None and len(items) > max_rows:
            lines.append("")
            lines.append(f"{len(items) - max_rows} more are listed in results_gap.csv.")
    return "\n".join(lines) + "\n"
