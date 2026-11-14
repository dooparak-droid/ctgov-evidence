import pytest

from ctgov_evidence.extract import extract_trial
from ctgov_evidence.verify import split_sentences, verify_narrative, verify_sentence


@pytest.fixture
def trials(raw):
    return [extract_trial(raw[k]) for k in sorted(raw)]


def test_correct_sentence_passes(trials):
    s = (
        "NCT04349072 is a completed Phase 3 trial sponsored by Bristol-Myers Squibb "
        "that enrolled 112 participants [NCT04349072]."
    )
    r = verify_sentence(s, trials)
    assert r.ok, r.reasons


def test_wrong_enrollment_is_caught(trials):
    s = "NCT04349072 enrolled 500 participants [NCT04349072]."
    r = verify_sentence(s, trials)
    assert not r.ok
    assert any("number 500" in x for x in r.reasons)


def test_wrong_phase_is_caught(trials):
    r = verify_sentence("This was a Phase 2 trial [NCT04349072].", trials)
    assert not r.ok
    assert any("phase 2" in x for x in r.reasons)


def test_wrong_status_is_caught(trials):
    r = verify_sentence("The trial is still recruiting [NCT04349072].", trials)
    assert not r.ok


def test_misattributed_sponsor_is_caught(trials):
    r = verify_sentence("The sponsor was LianBio LLC [NCT04349072].", trials)
    assert not r.ok
    assert any("LianBio" in x for x in r.reasons)


def test_invented_organisation_is_caught(trials):
    r = verify_sentence("It was run by Acme Therapeutics Inc [NCT04349072].", trials)
    assert not r.ok


def test_missing_or_unknown_citation_fails(trials):
    assert not verify_sentence("Mavacamten trials were completed.", trials).ok
    r = verify_sentence("A trial completed [NCT99999999].", trials)
    assert not r.ok


def test_count_claims(trials):
    good = verify_sentence(
        "Three trials have posted results [NCT03496168, NCT04349072, NCT05174416].", trials
    )
    assert good.ok, good.reasons
    bad = verify_sentence(
        "Seven trials have posted results [NCT03496168, NCT04349072, NCT05174416].", trials
    )
    assert not bad.ok


def test_results_contradiction(trials):
    r = verify_sentence("NCT07077005 has posted results [NCT07077005].", trials)
    assert not r.ok


def test_enrolment_sum_supported(trials):
    r = verify_sentence(
        "Together they enrolled 426 participants [NCT04349072, NCT03723655].", trials
    )
    assert r.ok, r.reasons


def test_report_counts_and_render(trials):
    text = (
        "NCT04349072 enrolled 112 participants [NCT04349072]. "
        "NCT04349072 enrolled 999 participants [NCT04349072]."
    )
    rep = verify_narrative(text, trials)
    assert (rep.n_verified, rep.n_total) == (1, 2)
    assert rep.render("mark").endswith("[unverified]")
    assert "999" not in rep.render("remove")


def test_split_sentences_keeps_decimals():
    text = "The mean was 1.5 units [NCT01234567]. Next one [NCT01234567]."
    assert len(split_sentences(text)) == 2


def test_case_insensitive_intervention_and_set_size(trials):
    ok = verify_sentence("Of the 8 trials, NCT04349072 tested mavacamten [NCT04349072].", trials)
    assert ok.ok, ok.reasons
