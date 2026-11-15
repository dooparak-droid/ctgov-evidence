"""Deterministic aggregates and output files. No LLM is involved here."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .gap import GAP_FILE_COLUMNS, gap_markdown, gap_rows, results_gap
from .labels import NOT_REPORTED, PHASE_LABELS, PHASE_ORDER, phase_label
from .models import CountedItem, EnrollmentGroup, Evidence, Summary, Trial


def _phase_sort_key(label: str) -> tuple[int, str]:
    reverse = {v: k for k, v in PHASE_LABELS.items()}
    first = label.split(" / ")[0]
    if label == NOT_REPORTED:
        return (99, label)
    code = reverse.get(first, "")
    index = PHASE_ORDER.index(code) if code in PHASE_ORDER else 98
    return (index * 10 + label.count("/"), label)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _ranked(groups: dict[str, tuple[str, list[str]]]) -> list[CountedItem]:
    items = [
        CountedItem(name=name, n_trials=len(ids), nct_ids=sorted(ids))
        for name, ids in groups.values()
    ]
    return sorted(items, key=lambda i: (-i.n_trials, i.name.casefold()))


def summarise(trials: list[Trial], as_of: date | None = None) -> Summary:
    by_phase: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    enrollment: dict[str, EnrollmentGroup] = {}
    n_missing_enrollment = 0
    sponsors: dict[str, tuple[str, list[str]]] = {}
    outcomes: dict[str, tuple[str, list[str]]] = {}
    posted: list[str] = []
    n_not_posted = n_unknown = 0

    for t in trials:
        by_phase[phase_label(t.phase.value)] += 1
        by_status[t.status.value or NOT_REPORTED] += 1
        by_type[t.study_type.value or NOT_REPORTED] += 1

        if t.enrollment.value is None:
            n_missing_enrollment += 1
        else:
            kind = t.enrollment_type.value or "UNSPECIFIED"
            group = enrollment.setdefault(kind, EnrollmentGroup())
            group.n_trials += 1
            group.total += t.enrollment.value

        if t.sponsor.value:
            sponsors.setdefault(_normalise(t.sponsor.value), (t.sponsor.value, []))[1].append(
                t.nct_id
            )

        seen_measures: set[str] = set()
        for o in t.primary_outcomes.value or []:
            if not o.measure:
                continue
            key = _normalise(o.measure)
            if key in seen_measures:
                continue
            seen_measures.add(key)
            outcomes.setdefault(key, (o.measure.strip(), []))[1].append(t.nct_id)

        if t.has_results.value is True:
            posted.append(t.nct_id)
        elif t.has_results.value is False:
            n_not_posted += 1
        else:
            n_unknown += 1

    return Summary(
        n_trials=len(trials),
        by_phase=dict(sorted(by_phase.items(), key=lambda kv: _phase_sort_key(kv[0]))),
        by_status=dict(sorted(by_status.items(), key=lambda kv: (-kv[1], kv[0]))),
        by_study_type=dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        enrollment=dict(sorted(enrollment.items())),
        n_enrollment_missing=n_missing_enrollment,
        sponsors=_ranked(sponsors),
        primary_outcomes=_ranked(outcomes),
        n_results_posted=len(posted),
        n_results_not_posted=n_not_posted,
        n_results_unknown=n_unknown,
        results_posted_nct_ids=sorted(posted),
        results_gap=results_gap(trials, as_of or date.today()),
    )


# ---------------------------------------------------------------- tables

TABLE_COLUMNS = [
    "nct_id",
    "title",
    "sponsor",
    "phase",
    "status",
    "enrollment",
    "enrollment_type",
    "start_date",
    "primary_completion_date",
    "completion_date",
    "design",
    "primary_outcome",
    "results_posted",
]


def _design(t: Trial) -> str:
    parts = [p for p in (t.study_type.value, t.allocation.value, t.masking.value) if p]
    return "; ".join(parts)


def _primary_outcome(t: Trial) -> str:
    measures = [o.measure for o in (t.primary_outcomes.value or []) if o.measure]
    if not measures:
        return ""
    extra = f" (+{len(measures) - 1} more)" if len(measures) > 1 else ""
    return measures[0] + extra


def table_rows(trials: list[Trial]) -> list[dict[str, str]]:
    rows = []
    for t in trials:
        results = t.has_results.value
        rows.append(
            {
                "nct_id": t.nct_id,
                "title": t.title.value or "",
                "sponsor": t.sponsor.value or "",
                "phase": phase_label(t.phase.value),
                "status": t.status.value or "",
                "enrollment": "" if t.enrollment.value is None else str(t.enrollment.value),
                "enrollment_type": t.enrollment_type.value or "",
                "start_date": t.start_date.value or "",
                "primary_completion_date": t.primary_completion_date.value or "",
                "completion_date": t.completion_date.value or "",
                "design": _design(t),
                "primary_outcome": _primary_outcome(t),
                "results_posted": "" if results is None else ("yes" if results else "no"),
            }
        )
    return rows


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def table_markdown(rows: list[dict[str, str]]) -> str:
    header = "| " + " | ".join(TABLE_COLUMNS) + " |"
    rule = "|" + "|".join("---" for _ in TABLE_COLUMNS) + "|"
    body = ["| " + " | ".join(_md_cell(r[c]) for c in TABLE_COLUMNS) + " |" for r in rows]
    return "\n".join([header, rule, *body]) + "\n"


def _describe_query(ev: Evidence) -> str:
    q = ev.query
    if q.nct_ids:
        return f"{len(q.nct_ids)} NCT ID(s) supplied"
    parts = []
    if q.condition:
        parts.append(f'condition "{q.condition}"')
    if q.intervention:
        parts.append(f'intervention "{q.intervention}"')
    if q.phase:
        parts.append("phase " + ", ".join(q.phase))
    if q.status:
        parts.append("status " + ", ".join(q.status))
    return "; ".join(parts)


def summary_markdown(ev: Evidence, top_outcomes: int = 10, top_sponsors: int = 10) -> str:
    s = ev.summary
    lines = ["# Evidence summary", ""]
    lines.append(f"Query: {_describe_query(ev)}.")
    if ev.total_found is not None and not ev.query.nct_ids:
        lines.append(
            f"The registry reported {ev.total_found} matching studies; {s.n_trials} were retrieved."
        )
    if ev.truncated:
        lines.append(
            f"Retrieval stopped at the limit of {ev.query.max_studies} studies, so this summary "
            "does not cover every match."
        )
    if ev.not_found:
        lines.append("Not found in the registry: " + ", ".join(ev.not_found) + ".")
    lines.append("")

    lines += ["## Trials by phase", "", "| Phase | Trials |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s.by_phase.items()]
    lines += ["", "## Trials by status", "", "| Status | Trials |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s.by_status.items()]
    lines += ["", "## Trials by study type", "", "| Study type | Trials |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s.by_study_type.items()]

    lines += ["", "## Enrolment", "", "| Count type | Trials | Participants |", "|---|---|---|"]
    for kind, grp in s.enrollment.items():
        lines.append(f"| {kind.capitalize()} | {grp.n_trials} | {grp.total} |")
    lines.append("")
    lines.append(
        f"Trials with no enrolment count: {s.n_enrollment_missing}. "
        "Actual and estimated counts are kept separate and are not added together."
    )

    shown = min(top_sponsors, len(s.sponsors))
    lines += [
        "",
        f"## Lead sponsors (top {shown} of {len(s.sponsors)})",
        "",
        "| Sponsor | Trials |",
        "|---|---|",
    ]
    lines += [f"| {_md_cell(i.name)} | {i.n_trials} |" for i in s.sponsors[:top_sponsors]]

    n_out = len(s.primary_outcomes)
    shown = min(top_outcomes, n_out)
    lines += [
        "",
        f"## Primary outcome measures (top {shown} of {n_out} distinct)",
        "",
        "| Measure | Trials |",
        "|---|---|",
    ]
    lines += [f"| {_md_cell(i.name)} | {i.n_trials} |" for i in s.primary_outcomes[:top_outcomes]]

    lines += ["", "## Posted results", ""]
    lines.append(
        f"{s.n_results_posted} of {s.n_trials} trials have results posted in the registry"
        f" ({s.n_results_not_posted} do not; {s.n_results_unknown} not recorded)."
    )
    if s.results_posted_nct_ids:
        lines.append("")
        lines.append("Trials with posted results: " + ", ".join(s.results_posted_nct_ids) + ".")
    lines += ["", gap_markdown(s.results_gap).rstrip()]
    return "\n".join(lines) + "\n"


def write_outputs(ev: Evidence, out_dir: str | Path) -> dict[str, Path]:
    """Write trials, evidence table, summary and results-gap files to ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = table_rows(ev.trials)
    paths = {
        "trials": out / "trials.json",
        "table_csv": out / "evidence_table.csv",
        "table_md": out / "evidence_table.md",
        "summary_md": out / "summary.md",
        "summary_json": out / "summary.json",
        "gap_csv": out / "results_gap.csv",
        "gap_md": out / "results_gap.md",
    }
    trials_doc = {
        "meta": {
            "retrieved_at": ev.retrieved_at.isoformat(),
            "query": ev.query.model_dump(),
            "total_found": ev.total_found,
            "truncated": ev.truncated,
            "not_found": ev.not_found,
            "n_trials": len(ev.trials),
        },
        "trials": [t.model_dump() for t in ev.trials],
    }
    paths["trials"].write_text(json.dumps(trials_doc, indent=2, ensure_ascii=False) + "\n")
    with paths["table_csv"].open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    paths["table_md"].write_text(table_markdown(rows))
    paths["summary_md"].write_text(summary_markdown(ev))
    paths["summary_json"].write_text(
        json.dumps(ev.summary.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    )
    with paths["gap_csv"].open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=GAP_FILE_COLUMNS)
        writer.writeheader()
        writer.writerows(gap_rows(ev.summary.results_gap))
    paths["gap_md"].write_text(gap_markdown(ev.summary.results_gap, heading="#", max_rows=None))
    return paths
