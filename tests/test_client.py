import httpx
import pytest

from conftest import load, make_transport
from ctgov_evidence.client import (
    CTGovClient,
    NotFoundError,
    RegistryError,
    build_search_params,
    normalise_phase,
)


def fast_client(transport, **kw):
    return CTGovClient(transport=transport, min_interval=0, backoff=0, **kw)


def paged():
    """Two real search pages. The mock hands out 'page1' as the token for page 2."""
    p1, p2 = load("search_page1.json"), load("search_page2.json")
    p1["nextPageToken"] = "page1"
    p2.pop("nextPageToken", None)
    return [p1, p2]


def test_search_follows_paging_token():
    transport = make_transport(search_pages=paged())
    with fast_client(transport) as c:
        result = c.search(condition="hypertrophic cardiomyopathy", intervention="mavacamten")
    assert len(result.studies) == 6
    assert result.total_count == 44
    assert not result.truncated
    assert len(transport.requests) == 2
    assert transport.requests[1].url.params["pageToken"] == "page1"
    assert "countTotal" not in transport.requests[1].url.params


def test_search_respects_max_studies_and_flags_truncation():
    transport = make_transport(search_pages=paged())
    with fast_client(transport) as c:
        result = c.search(condition="x", max_studies=4)
    assert len(result.studies) == 4
    assert result.truncated


def test_search_requires_a_term():
    with fast_client(make_transport()) as c, pytest.raises(ValueError):
        c.search()


def test_get_study_and_not_found(raw):
    transport = make_transport(studies={"NCT04349072": raw["NCT04349072"]})
    with fast_client(transport) as c:
        assert c.get_study("nct04349072")["hasResults"] is True
        with pytest.raises(NotFoundError):
            c.get_study("NCT00000001")
        with pytest.raises(ValueError):
            c.get_study("12345")


def test_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"studies": [], "totalCount": 0})

    with fast_client(httpx.MockTransport(handler)) as c:
        assert c.search(condition="x").studies == []
    assert calls["n"] == 3


def test_gives_up_after_retries():
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    with fast_client(transport, max_retries=2) as c, pytest.raises(RegistryError):
        c.search(condition="x")


def test_search_params():
    params = build_search_params("obesity", "semaglutide", ["3", "phase 2"], ["completed"], 50)
    assert params["query.cond"] == "obesity"
    assert params["query.intr"] == "semaglutide"
    assert params["filter.advanced"] == "AREA[Phase](PHASE3 OR PHASE2)"
    assert params["filter.overallStatus"] == "COMPLETED"
    assert params["pageSize"] == "50"
    with pytest.raises(ValueError):
        normalise_phase("7")
