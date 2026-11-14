import pytest

from conftest import load, make_transport

pytest.importorskip("mcp")

from ctgov_evidence import mcp_server, pipeline  # noqa: E402
from ctgov_evidence.client import CTGovClient  # noqa: E402


def test_tools_return_data(monkeypatch):
    page = load("search_page1.json")
    page.pop("nextPageToken", None)
    monkeypatch.setattr(
        pipeline,
        "CTGovClient",
        lambda: CTGovClient(transport=make_transport(search_pages=[page]), min_interval=0),
    )
    rows = mcp_server.search_trials(condition="hcm")
    assert rows["returned"] == 3 and rows["trials"][0]["nct_id"]
    full = mcp_server.build_evidence(condition="hcm")
    assert full["summary"]["n_trials"] == 3
    assert full["trials"][0]["enrollment"]["source"].startswith("NCT")


def test_server_registers_both_tools():
    server = mcp_server.make_server()
    assert server is not None
