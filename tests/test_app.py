from pathlib import Path

import pytest

from conftest import load, make_transport

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from ctgov_evidence import narrative, pipeline  # noqa: E402
from ctgov_evidence.client import CTGovClient  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "src" / "ctgov_evidence" / "app.py")


@pytest.fixture
def app(monkeypatch):
    page = load("search_page1.json")
    page.pop("nextPageToken", None)
    monkeypatch.setattr(
        pipeline,
        "CTGovClient",
        lambda: CTGovClient(transport=make_transport(search_pages=[page]), min_interval=0),
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import streamlit as st

    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def test_loads_with_prompt_before_search(app):
    assert not app.exception
    assert any("press Search" in i.value for i in app.info)


def test_search_shows_metrics_tables_and_sources(app):
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert [m.label for m in app.metric][:2] == ["Trials", "With posted results"]
    assert app.metric[0].value == "3"
    assert len(app.dataframe) >= 2
    sources = app.dataframe[-1].value["source"].tolist()
    assert all(
        src.startswith("NCT") and "protocolSection" in src or ":hasResults" in src
        for src in sources
    )


def test_search_without_terms_shows_error(app):
    app.sidebar.text_input[0].set_value("").run()
    app.sidebar.text_input[1].set_value("").run()
    app.sidebar.button[0].click().run()
    assert any("condition" in e.value.lower() for e in app.sidebar.error)


def test_narrative_without_key_explains(app):
    app.sidebar.button[0].click().run()
    assert any("No Gemini key" in i.value for i in app.info)


def test_narrative_with_own_key_marks_failures(app, monkeypatch):
    def fake(ev, provider=None, model=None, http_client=None, api_key=None):
        assert api_key == "AQ.visitor"
        first = ev.trials[0].nct_id
        return f"{first} is a trial [{first}]. {first} enrolled 999999 participants [{first}]."

    monkeypatch.setattr(narrative, "generate_narrative", fake)
    app.sidebar.button[0].click().run()
    app.text_input[0].set_value("AQ.visitor").run()
    next(b for b in app.button if b.label == "Write and verify narrative").click().run()
    assert not app.exception
    assert any("1 verified / 2 sentences" in s.value for s in app.subheader)
    assert len(app.error) == 1 and "[unverified]" in app.error[0].value
