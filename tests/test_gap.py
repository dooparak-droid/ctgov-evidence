import copy
import csv
from datetime import date

import pytest

from ctgov_evidence.extract import extract_trial
from ctgov_evidence.gap import add_months, parse_registry_date, results_gap
from ctgov_evidence.models import Evidence, Query
from ctgov_evidence.summarise import summarise, write_outputs

AS_OF = date(2026, 11, 14)


def all_trials(raw):
    return [extract_trial(raw[k]) for k in sorted(raw)]


def variant(raw, nct="NCT03723655", **changes):
    """A copy of a real record with selected fields changed, returned as a Trial."""
    rec = copy.deepcopy(raw[nct])
    p = rec["protocolSection"]
    if "phases" in changes:
        p["designModule"]["phases"] = changes["phases"]
    if "primary" in changes:
        p["statusModule"]["primaryCompletionDateStruct"]["date"] = changes["primary"]
    if "status" in changes:
        p["statusModule"]["overallStatus"] = changes["status"]
    if "drug" in changes:
        if changes["drug"] is None:
            p["oversightModule"].pop("isFdaRegulatedDrug", None)
            p["oversightModule"].pop("isFdaRegulatedDevice", None)
        else:
            p["oversightModule"]["isFdaRegulatedDrug"] = changes["drug"]
    if "has_results" in changes:
        rec["hasResults"] = changes["has_results"]
    return extract_trial(rec)


def test_helpers():
    assert parse_registry_date("2025-06") == date(2025, 6, 30)
    assert parse_registry_date("2025-06-02") == date(2025, 6, 2)
    assert parse_registry_date("junk") is None and parse_registry_date(None) is None
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2025, 11, 9), 12) == date(2026, 11, 9)


def test_counts_on_real_fixtures_match_hand_calculation(raw):
    """Dates for the four finished interventional trials were checked by hand.

    NCT03496168 reported 4 days before its deadline, NCT04349072 exactly on it, NCT05174416
    about 16.6 months after primary completion, and NCT03723655 is not due until 2027-01-16.
    """
    gap = results_gap(all_trials(raw), AS_OF)
    assert gap.n_finished_interventional == 4
    assert gap.n_results_posted == 3
    assert gap.n_reported_within_deadline == 2
    assert gap.n_reported_late == 1
    assert gap.median_months_to_first_submission == pytest.approx(12.0, abs=0.1)
    assert gap.n_not_yet_due == 1
    assert gap.n_overdue_no_results == 0
    assert gap.n_not_interventional == 3
    assert gap.n_not_finished == 1


def test_overdue_trial_is_flagged_as_likely_applicable(raw):
    t = variant(raw)  # Phase 2/3, FDA-regulated drug, primary completion 2026-01-16
    gap = results_gap([t], date(2027, 3, 1))
    assert gap.n_overdue_no_results == 1
    item = gap.groups["likely_applicable"][0]
    assert item.nct_id == "NCT03723655"
    assert item.months_since_primary_completion == pytest.approx(13.4, abs=0.1)
    assert item.phase == "Phase 2 / Phase 3"


def test_deadline_day_is_not_overdue(raw):
    t = variant(raw)  # due 2027-01-16
    assert results_gap([t], date(2027, 1, 16)).n_overdue_no_results == 0
    assert results_gap([t], date(2027, 1, 16)).n_not_yet_due == 1
    assert results_gap([t], date(2027, 1, 17)).n_overdue_no_results == 1


def test_month_only_date_uses_end_of_month(raw):
    t = variant(raw, primary="2025-06")  # due 2026-06-30
    assert results_gap([t], date(2026, 6, 30)).n_overdue_no_results == 0
    assert results_gap([t], date(2026, 7, 1)).n_overdue_no_results == 1


def test_phase_one_is_probably_exempt(raw):
    t = variant(raw, phases=["PHASE1"], primary="2023-01-10")
    group = next(iter(k for k, v in results_gap([t], AS_OF).groups.items() if v))
    assert group == "probably_exempt"


def test_trial_marked_not_fda_regulated_is_probably_not_covered(raw):
    t = variant(raw, primary="2023-01-10", drug=False)  # fixture also has device flag False
    groups = results_gap([t], AS_OF).groups
    assert len(groups["probably_not_covered"]) == 1 and not groups["likely_applicable"]


def test_trial_with_no_flags_is_cannot_tell(raw):
    t = variant(raw, primary="2023-01-10", drug=None)
    groups = results_gap([t], AS_OF).groups
    assert len(groups["cannot_tell"]) == 1 and not groups["probably_not_covered"]


def test_long_groups_are_trimmed_in_summary_but_complete_in_csv(raw):
    from ctgov_evidence.gap import gap_markdown, gap_rows

    trials = [variant(raw, primary="2023-01-10") for _ in range(20)]
    gap = results_gap(trials, AS_OF)
    short = gap_markdown(gap)
    assert "5 more are listed in results_gap.csv." in short
    assert short.count("| NCT03723655 |") == 15
    assert len(gap_rows(gap)) == 20
    assert gap_markdown(gap, max_rows=None).count("| NCT03723655 |") == 20


def test_terminated_counts_and_recruiting_does_not(raw):
    done = variant(raw, primary="2023-01-10", status="TERMINATED")
    active = variant(raw, primary="2023-01-10", status="RECRUITING")
    gap = results_gap([done, active], AS_OF)
    assert gap.n_overdue_no_results == 1 and gap.n_not_finished == 1


def test_posted_results_never_appear_as_a_gap(raw):
    t = variant(raw, primary="2023-01-10", has_results=True)
    assert results_gap([t], AS_OF).n_overdue_no_results == 0


def test_outputs_include_gap_files(raw, tmp_path):
    ts = [variant(raw, primary="2023-01-10"), *all_trials(raw)[:1]]
    ev = Evidence(
        query=Query(condition="x"),
        retrieved_at="2026-11-14T00:00:00Z",
        trials=ts,
        summary=summarise(ts, as_of=AS_OF),
    )
    paths = write_outputs(ev, tmp_path)
    with paths["gap_csv"].open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["nct_id"] == "NCT03723655" and rows[0]["group"] == "likely_applicable"
    assert "Results gap check" in paths["summary_md"].read_text()
    assert "2026-11-14" in paths["summary_json"].read_text()
