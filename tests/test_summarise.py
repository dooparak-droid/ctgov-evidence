import csv

from ctgov_evidence.extract import extract_trial
from ctgov_evidence.models import Evidence, Query
from ctgov_evidence.summarise import phase_label, summarise, table_rows, write_outputs


def trials(raw):
    return [extract_trial(raw[k]) for k in sorted(raw)]


def test_phase_label():
    assert phase_label(["PHASE3", "PHASE2"]) == "Phase 2 / Phase 3"
    assert phase_label(["NA"]) == "Not applicable"
    assert phase_label(None) == "Not reported"


def test_totals_match_hand_counts(raw):
    """Counts below were tallied by hand from the eight saved records."""
    s = summarise(trials(raw))
    assert s.n_trials == 8
    assert s.by_phase == {
        "Phase 2": 1,
        "Phase 2 / Phase 3": 1,
        "Phase 3": 2,
        "Not applicable": 1,
        "Not reported": 3,
    }
    assert sum(s.by_phase.values()) == s.n_trials
    assert s.by_status == {"COMPLETED": 6, "NOT_YET_RECRUITING": 1, "RECRUITING": 1}
    assert s.enrollment["ACTUAL"].total == 905
    assert s.enrollment["ACTUAL"].n_trials == 6
    assert s.enrollment["ESTIMATED"].total == 174
    assert s.enrollment["ESTIMATED"].n_trials == 2
    assert s.n_enrollment_missing == 0
    assert s.n_results_posted == 3
    assert s.n_results_not_posted == 5
    assert s.results_posted_nct_ids == ["NCT03496168", "NCT04349072", "NCT05174416"]
    bms = next(i for i in s.sponsors if i.name == "Bristol-Myers Squibb")
    assert bms.n_trials == 4
    assert len(s.sponsors) == 5
    assert s.by_study_type == {"INTERVENTIONAL": 5, "OBSERVATIONAL": 3}


def test_actual_and_estimated_not_merged(raw):
    s = summarise(trials(raw))
    assert set(s.enrollment) == {"ACTUAL", "ESTIMATED"}


def test_outputs_written(raw, tmp_path):
    ts = trials(raw)
    ev = Evidence(
        query=Query(condition="hcm"),
        retrieved_at="2026-10-16T00:00:00Z",
        total_found=8,
        trials=ts,
        summary=summarise(ts),
    )
    paths = write_outputs(ev, tmp_path / "out")
    assert all(p.exists() for p in paths.values())
    with paths["table_csv"].open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 8
    row = next(r for r in rows if r["nct_id"] == "NCT04349072")
    assert row["enrollment"] == "112"
    assert row["results_posted"] == "yes"
    assert "Phase 3" in row["phase"]
    md = paths["summary_md"].read_text()
    assert "3 of 8 trials have results posted" in md
    assert "NCT04349072" in paths["trials"].read_text()


def test_table_rows_blank_when_missing(raw):
    row = next(r for r in table_rows(trials(raw)) if r["nct_id"] == "NCT07716826")
    assert row["phase"] == "Not reported"
    assert row["design"] == "OBSERVATIONAL"
