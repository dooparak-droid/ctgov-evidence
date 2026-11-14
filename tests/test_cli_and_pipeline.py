import json

import pytest

from conftest import load, make_transport
from ctgov_evidence import cli, pipeline
from ctgov_evidence.client import CTGovClient
from ctgov_evidence.models import Query
from ctgov_evidence.narrative import NarrativeUnavailable, generate_narrative


def mock_client(raw):
    page = load("search_page1.json")
    page.pop("nextPageToken", None)
    return CTGovClient(
        transport=make_transport(search_pages=[page], studies=raw), min_interval=0, backoff=0
    )


def test_build_evidence_by_ids_reports_missing(raw):
    ev = pipeline.build_evidence(
        Query(nct_ids=["NCT04349072", "NCT00000001", "nct04349072"]), client=mock_client(raw)
    )
    assert [t.nct_id for t in ev.trials] == ["NCT04349072"]
    assert ev.not_found == ["NCT00000001"]
    assert ev.summary.n_trials == 1


def test_build_evidence_search(raw):
    ev = pipeline.build_evidence(Query(condition="x"), client=mock_client(raw))
    assert len(ev.trials) == 3
    assert ev.total_found == 44


def test_cli_search_writes_outputs(raw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CTGovClient", lambda: mock_client(raw))
    out = tmp_path / "o"
    code = cli.main(["search", "--condition", "hcm", "--out", str(out)])
    assert code == 0
    assert (out / "trials.json").exists()
    meta = json.loads((out / "trials.json").read_text())["meta"]
    assert meta["n_trials"] == 3
    assert "Retrieved 3 trials of 44" in capsys.readouterr().out


def test_cli_narrative_skipped_without_key(raw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CTGovClient", lambda: mock_client(raw))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = cli.main(["fetch", "NCT04349072", "--out", str(tmp_path), "--narrative"])
    assert code == 0
    assert "Narrative skipped" in capsys.readouterr().err
    assert not (tmp_path / "narrative.md").exists()


def test_cli_narrative_verified_with_stub(raw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CTGovClient", lambda: mock_client(raw))
    monkeypatch.setattr(
        cli,
        "generate_narrative",
        lambda ev, model=None: (
            "NCT04349072 enrolled 112 participants [NCT04349072]. "
            "NCT04349072 enrolled 400 participants [NCT04349072]."
        ),
    )
    cli.main(["fetch", "NCT04349072", "--out", str(tmp_path), "--narrative"])
    text = (tmp_path / "narrative.md").read_text()
    assert "[unverified]" in text
    assert "1 verified / 2 total" in text


def test_generate_narrative_requires_key(raw, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    with pytest.raises(NarrativeUnavailable):
        generate_narrative(ev)


def test_cli_search_needs_a_term(capsys):
    with pytest.raises(SystemExit):
        cli.main(["search"])
