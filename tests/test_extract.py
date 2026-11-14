import pytest

from ctgov_evidence.extract import ExtractionError, extract_trial


def test_complete_record_with_results(raw):
    t = extract_trial(raw["NCT04349072"])
    assert t.nct_id == "NCT04349072"
    assert t.sponsor.value == "Bristol-Myers Squibb"
    assert t.phase.value == ["PHASE3"]
    assert t.status.value == "COMPLETED"
    assert t.enrollment.value == 112
    assert t.enrollment_type.value == "ACTUAL"
    assert t.has_results.value is True
    assert t.allocation.value
    assert t.masking.value
    assert t.interventions.value and "Mavacamten" in t.interventions.value
    assert t.primary_outcomes.value[0].time_frame == "Week 16"


def test_source_paths_resolve_in_raw_record(raw):
    """Every source path must point at a real location whenever a value was extracted."""
    rec = raw["NCT04349072"]
    t = extract_trial(rec)
    for name in type(t).model_fields:
        field = getattr(t, name)
        if not hasattr(field, "source"):
            continue
        nct, path = field.source.split(":", 1)
        assert nct == t.nct_id
        node = rec
        for key in path.split("."):
            assert isinstance(node, dict) and key in node, f"{field.source} does not resolve"
            node = node[key]


def test_missing_fields_stay_none_with_source(raw):
    t = extract_trial(raw["NCT07716826"])
    assert t.interventions.value is None
    assert t.interventions.source == (
        "NCT07716826:protocolSection.armsInterventionsModule.interventions"
    )
    assert t.phase.value is None
    assert t.allocation.value is None
    assert t.masking.value is None
    assert t.enrollment.value == 150
    assert t.enrollment_type.value == "ESTIMATED"
    assert t.has_results.value is False


def test_multiple_phases(raw):
    t = extract_trial(raw["NCT03723655"])
    assert t.phase.value == ["PHASE2", "PHASE3"]


def test_many_outcomes_kept(raw):
    t = extract_trial(raw["NCT03496168"])
    assert len(t.primary_outcomes.value) == 20


def test_record_without_nct_id_is_rejected():
    with pytest.raises(ExtractionError):
        extract_trial({"protocolSection": {}})


def test_empty_record_values_do_not_invent_data():
    rec = {"protocolSection": {"identificationModule": {"nctId": "NCT00000002"}}}
    t = extract_trial(rec)
    assert t.title.value is None
    assert t.enrollment.value is None
    assert t.has_results.value is None
