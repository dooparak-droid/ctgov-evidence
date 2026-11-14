import json

import httpx
import pytest

from conftest import load, make_transport
from ctgov_evidence import cli, pipeline
from ctgov_evidence.client import CTGovClient
from ctgov_evidence.models import Query
from ctgov_evidence.narrative import (
    NarrativeError,
    NarrativeUnavailable,
    detect_provider,
    generate_narrative,
)


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
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    code = cli.main(["fetch", "NCT04349072", "--out", str(tmp_path), "--narrative"])
    assert code == 0
    assert "Narrative skipped" in capsys.readouterr().err
    assert not (tmp_path / "narrative.md").exists()


def test_cli_narrative_verified_with_stub(raw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CTGovClient", lambda: mock_client(raw))
    monkeypatch.setattr(
        cli,
        "generate_narrative",
        lambda ev, provider=None, model=None: (
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
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    with pytest.raises(NarrativeUnavailable):
        generate_narrative(ev)


def test_cli_search_needs_a_term(capsys):
    with pytest.raises(SystemExit):
        cli.main(["search"])


def _gemini_ok(text="NCT04349072 enrolled 112 participants [NCT04349072]."):
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return httpx.MockTransport(lambda r: httpx.Response(200, json=body))


def test_gemini_provider_sends_key_in_header_not_url(raw, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test-key-not-real")
    seen = []

    def handler(request):
        seen.append(request)
        body = {"candidates": [{"content": {"parts": [{"text": "A sentence [NCT04349072]."}]}}]}
        return httpx.Response(200, json=body)

    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    text = generate_narrative(
        ev, provider="gemini", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert text == "A sentence [NCT04349072]."
    assert seen[0].headers["x-goog-api-key"] == "AQ.test-key-not-real"
    assert "AQ." not in str(seen[0].url)
    sent = json.loads(seen[0].content)
    assert "NCT04349072" in sent["contents"][0]["parts"][0]["text"]
    assert "protocolSection" not in sent["contents"][0]["parts"][0]["text"]


def test_gemini_http_error_does_not_leak_key(raw, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.secret-value")
    monkeypatch.setattr("ctgov_evidence.narrative.time.sleep", lambda s: None)
    transport = httpx.MockTransport(
        lambda r: httpx.Response(429, json={"error": {"message": "Quota exceeded"}})
    )
    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    with pytest.raises(NarrativeError) as info:
        generate_narrative(ev, provider="gemini", http_client=httpx.Client(transport=transport))
    assert "429" in str(info.value) and "secret-value" not in str(info.value)


def test_gemini_empty_response_is_an_error(raw, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.x")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []}))
    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    with pytest.raises(NarrativeError):
        generate_narrative(ev, provider="gemini", http_client=httpx.Client(transport=transport))


def test_provider_auto_detection(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert detect_provider() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert detect_provider() == "anthropic"
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    assert detect_provider() == "gemini"


def test_cli_skips_when_provider_errors(raw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CTGovClient", lambda: mock_client(raw))

    def boom(ev, provider=None, model=None):
        raise NarrativeError("Gemini API returned HTTP 429: Quota exceeded")

    monkeypatch.setattr(cli, "generate_narrative", boom)
    code = cli.main(["fetch", "NCT04349072", "--out", str(tmp_path), "--narrative"])
    assert code == 0
    assert "Quota exceeded" in capsys.readouterr().err
    assert (tmp_path / "trials.json").exists()


def test_gemini_retries_on_overload_then_succeeds(raw, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.x")
    monkeypatch.setattr("ctgov_evidence.narrative.time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        body = {"candidates": [{"content": {"parts": [{"text": "Fine [NCT04349072]."}]}}]}
        return httpx.Response(200, json=body)

    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert generate_narrative(ev, provider="gemini", http_client=client) == "Fine [NCT04349072]."
    assert calls["n"] == 3


def test_gemini_falls_back_to_lighter_model_after_repeated_overload(raw, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.x")
    monkeypatch.setattr("ctgov_evidence.narrative.time.sleep", lambda s: None)
    models = []

    def handler(request):
        models.append(request.url.path.split("/")[-1].split(":")[0])
        if len(models) <= 2:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        body = {"candidates": [{"content": {"parts": [{"text": "Fine [NCT04349072]."}]}}]}
        return httpx.Response(200, json=body)

    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    generate_narrative(ev, provider="gemini", http_client=client)
    assert models[:2] == ["gemini-3.5-flash"] * 2
    assert models[2] == "gemini-3.1-flash-lite"


def test_explicit_model_is_never_swapped(raw, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.x")
    monkeypatch.setattr("ctgov_evidence.narrative.time.sleep", lambda s: None)
    models = []

    def handler(request):
        models.append(request.url.path.split("/")[-1].split(":")[0])
        if len(models) <= 3:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        body = {"candidates": [{"content": {"parts": [{"text": "Fine [NCT04349072]."}]}}]}
        return httpx.Response(200, json=body)

    ev = pipeline.build_evidence(Query(nct_ids=["NCT04349072"]), client=mock_client(raw))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    generate_narrative(ev, provider="gemini", model="gemini-3.8-flash", http_client=client)
    assert set(models) == {"gemini-3.8-flash"}
