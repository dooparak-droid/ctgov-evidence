"""Command line interface: ``ctgov-evidence search ...`` and ``ctgov-evidence fetch ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import RegistryError
from .models import Evidence, Query
from .narrative import NarrativeUnavailable, generate_narrative
from .pipeline import build_evidence
from .summarise import write_outputs
from .verify import verify_narrative


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", default="ctgov_output", help="output folder (default: ctgov_output)")
    p.add_argument(
        "--narrative",
        action="store_true",
        help="also write an LLM paragraph and verify it (needs ANTHROPIC_API_KEY)",
    )
    p.add_argument("--model", default=None, help="model for --narrative")
    p.add_argument(
        "--drop-unverified",
        action="store_true",
        help="remove unverified sentences instead of marking them",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctgov-evidence",
        description="Structured, source-traced evidence summaries from ClinicalTrials.gov.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="search by condition and/or intervention")
    s.add_argument("--condition")
    s.add_argument("--intervention")
    s.add_argument(
        "--phase", action="append", default=[], help="1, 2, 3, 4, early1 or na; repeat for several"
    )
    s.add_argument(
        "--status",
        action="append",
        default=[],
        help="e.g. COMPLETED, RECRUITING; repeat for several",
    )
    s.add_argument("--max-studies", type=int, default=200)
    _common(s)

    f = sub.add_parser("fetch", help="fetch specific trials by NCT ID")
    f.add_argument("nct_ids", nargs="+", metavar="NCT_ID")
    _common(f)
    return parser


def _query_from_args(args: argparse.Namespace) -> Query:
    if args.command == "fetch":
        return Query(nct_ids=args.nct_ids)
    if not (args.condition or args.intervention):
        raise SystemExit("error: search needs --condition, --intervention, or both")
    return Query(
        condition=args.condition,
        intervention=args.intervention,
        phase=args.phase,
        status=args.status,
        max_studies=args.max_studies,
    )


def _run_narrative(ev: Evidence, out: Path, model: str | None, drop: bool) -> None:
    try:
        text = generate_narrative(ev, model=model)
    except NarrativeUnavailable as exc:
        print(f"Narrative skipped: {exc}.", file=sys.stderr)
        return
    report = verify_narrative(text, ev.trials)
    final = report.render("remove" if drop else "mark")
    (out / "narrative.md").write_text(
        "# Narrative summary\n\n"
        f"{final}\n\n"
        f"Verification: {report.n_verified} verified / {report.n_total} total sentences.\n"
    )
    (out / "narrative_verification.json").write_text(
        json.dumps(
            [
                {"text": s.text, "cited": s.cited, "verified": s.ok, "reasons": s.reasons}
                for s in report.sentences
            ],
            indent=2,
        )
        + "\n"
    )
    print(f"Narrative: {report.n_verified} verified / {report.n_total} total sentences.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = _query_from_args(args)
    try:
        ev = build_evidence(query)
    except (RegistryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    paths = write_outputs(ev, args.out)
    out = Path(args.out)
    print(
        f"Retrieved {len(ev.trials)} trials"
        + (f" of {ev.total_found} matching" if ev.total_found is not None else "")
        + "."
    )
    if ev.truncated:
        print(
            f"Warning: stopped at --max-studies {query.max_studies}; results are partial.",
            file=sys.stderr,
        )
    if ev.not_found:
        print("Not found: " + ", ".join(ev.not_found), file=sys.stderr)
    for p in paths.values():
        print(f"  wrote {p}")
    if args.narrative:
        _run_narrative(ev, out, args.model, args.drop_unverified)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
