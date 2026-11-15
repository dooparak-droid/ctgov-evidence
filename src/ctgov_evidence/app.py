"""Optional Streamlit viewer. Run with: streamlit run src/ctgov_evidence/app.py

A Gemini key is read from ``st.secrets["GEMINI_API_KEY"]`` or the environment. Visitors can
also paste their own key. The shared key is limited to a few narratives per session.
"""

from __future__ import annotations

import os

import streamlit as st

from ctgov_evidence import Evidence, Query, build_evidence
from ctgov_evidence.client import RegistryError
from ctgov_evidence.gap import GROUP_LABELS, gap_rows
from ctgov_evidence.narrative import NarrativeError, NarrativeUnavailable, generate_narrative
from ctgov_evidence.summarise import phase_label, summary_markdown, table_rows
from ctgov_evidence.verify import verify_narrative

SHARED_KEY_LIMIT = 3
PHASES = ["1", "2", "3", "4", "early1", "na"]
STATUSES = [
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
    "SUSPENDED",
]


KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def find_shared_key() -> tuple[str | None, str]:
    """Look for a Gemini key in Streamlit secrets, then the environment.

    Returns the key (or None) and a plain-language note on where it came from or what was
    seen instead. The note never contains the key itself.
    """
    secret_names: list[str] = []
    try:
        secret_names = [str(k) for k in st.secrets.keys()]
        for name in KEY_NAMES:
            value = st.secrets.get(name)
            if value:
                return str(value), f"Streamlit secrets ({name})"
    except Exception:  # no secrets configured
        pass
    for name in KEY_NAMES:
        if os.environ.get(name):
            return os.environ[name], f"environment ({name})"
    seen = ", ".join(secret_names) if secret_names else "none"
    return None, f"No key found. Secret names the app can see: {seen}. Expected GEMINI_API_KEY."


@st.cache_data(ttl=3600, show_spinner=False)
def run_query(query_json: str) -> str:
    """Cached by query text. Returns JSON because parametrised pydantic models do not pickle."""
    evidence = build_evidence(Query.model_validate_json(query_json))
    return evidence.model_dump_json()


def trial_fields(trial) -> list[dict]:
    rows = []
    for name, field in trial:
        if hasattr(field, "source"):
            rows.append({"field": name, "value": str(field.value), "source": field.source})
    return rows


st.set_page_config(page_title="ctgov-evidence", layout="wide")
st.title("ClinicalTrials.gov evidence summary")
st.caption(
    "Every value below links to the field in the registry record it was read from. "
    "Data comes from the ClinicalTrials.gov API v2."
)

with st.sidebar:
    st.header("Search")
    condition = st.text_input("Condition", "hypertrophic cardiomyopathy")
    intervention = st.text_input("Intervention", "mavacamten")
    phases = st.multiselect("Phase", PHASES)
    statuses = st.multiselect("Status", STATUSES)
    max_studies = st.number_input("Max studies", 1, 500, 100)
    run = st.button("Search", type="primary")

if run:
    if not (condition or intervention):
        st.sidebar.error("Enter a condition, an intervention, or both.")
    else:
        query = Query(
            condition=condition or None,
            intervention=intervention or None,
            phase=phases,
            status=statuses,
            max_studies=int(max_studies),
        )
        try:
            with st.spinner("Fetching from ClinicalTrials.gov"):
                st.session_state["evidence_json"] = run_query(query.model_dump_json())
            st.session_state.pop("narrative", None)
        except (RegistryError, ValueError) as exc:
            st.error(f"The registry request failed. {exc}")

if "evidence_json" not in st.session_state:
    st.info("Choose a search in the sidebar and press Search.")
    st.stop()

ev = Evidence.model_validate_json(st.session_state["evidence_json"])
s = ev.summary

if not ev.trials:
    st.warning("No trials matched this search.")
    st.stop()

if ev.truncated:
    st.warning(
        f"The registry has {ev.total_found} matches. Only the first {len(ev.trials)} are shown."
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric("Trials", s.n_trials)
c2.metric("With posted results", s.n_results_posted)
c3.metric("Lead sponsors", len(s.sponsors))
actual = s.enrollment.get("ACTUAL")
c4.metric("Participants (actual counts)", f"{actual.total:,}" if actual else "0")

tab_summary, tab_table, tab_gap, tab_trial, tab_narr = st.tabs(
    ["Summary", "Evidence table", "Results gap", "Trial detail", "Narrative"]
)

with tab_summary:
    st.markdown(summary_markdown(ev))

with tab_table:
    st.dataframe(table_rows(ev.trials), width="stretch")

with tab_gap:
    gap = s.results_gap
    st.write(
        f"Finished interventional trials checked against the {gap.deadline_months}-month "
        f"results deadline, as of {gap.as_of.isoformat()}. The registry does not say which "
        "trials are legally covered, so a trial listed here has no results posted where they "
        "would normally be expected. Results may still exist in a journal."
    )
    g1, g2, g3 = st.columns(3)
    g1.metric("Finished interventional", gap.n_finished_interventional)
    g2.metric("Results posted", gap.n_results_posted)
    g3.metric("Past deadline, none posted", gap.n_overdue_no_results)
    rows = gap_rows(gap)
    if rows:
        group_names = {k: v.split(" (")[0] for k, v in GROUP_LABELS.items()}
        for row in rows:
            row["group"] = group_names[row["group"]]
        st.dataframe(rows, width="stretch")
    else:
        st.success("No finished trial in this set is past its deadline without results.")

with tab_trial:
    labels = {t.nct_id: f"{t.nct_id}  {(t.title.value or '')[:80]}" for t in ev.trials}
    chosen = st.selectbox("Trial", list(labels), format_func=labels.get)
    trial = next(t for t in ev.trials if t.nct_id == chosen)
    st.write(f"Phase label: {phase_label(trial.phase.value)}")
    st.dataframe(trial_fields(trial), width="stretch")
    st.caption("The source column is the path inside the original registry record.")

with tab_narr:
    st.write(
        "An LLM writes a short paragraph from the structured trials only. Each sentence is then "
        "checked against the records it cites, and sentences that cannot be supported are marked."
    )
    shared, shared_note = find_shared_key()
    if shared:
        st.caption(
            f"A shared Gemini key is configured ({shared_note}), so you do not need to enter "
            f"one. It is limited to {SHARED_KEY_LIMIT} narratives per session."
        )
    else:
        st.caption(shared_note)
    with st.expander("Use your own Gemini key instead (optional, not stored)"):
        own_key = st.text_input("Your Gemini API key", type="password")
    used = st.session_state.get("narratives_used", 0)
    key = own_key or shared
    limited = not own_key
    if not key:
        st.info("No Gemini key is available. Paste one above to generate a narrative.")
    elif limited and used >= SHARED_KEY_LIMIT:
        st.info(
            f"The shared key is limited to {SHARED_KEY_LIMIT} narratives per session. "
            "Paste your own key to continue."
        )
    elif st.button("Write and verify narrative"):
        try:
            with st.spinner("Writing and checking"):
                text = generate_narrative(ev, provider="gemini", api_key=key)
            if limited:
                st.session_state["narratives_used"] = used + 1
            st.session_state["narrative"] = verify_narrative(text, ev.trials)
        except (NarrativeError, NarrativeUnavailable) as exc:
            st.error(f"The narrative could not be generated. {exc}")

    report = st.session_state.get("narrative")
    if report is not None:
        st.subheader(f"{report.n_verified} verified / {report.n_total} sentences")
        for sentence in report.sentences:
            if sentence.ok:
                st.success(sentence.text)
            else:
                st.error(f"{sentence.text}  [unverified]")
                for reason in sentence.reasons:
                    st.caption(f"Reason: {reason}")
