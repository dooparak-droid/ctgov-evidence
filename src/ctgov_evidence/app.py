"""Optional Streamlit viewer. Run with: streamlit run src/ctgov_evidence/app.py"""

import streamlit as st

from ctgov_evidence import Query, build_evidence
from ctgov_evidence.summarise import summary_markdown, table_rows

st.set_page_config(page_title="ctgov-evidence", layout="wide")
st.title("ClinicalTrials.gov evidence summary")

with st.sidebar:
    condition = st.text_input("Condition", "hypertrophic cardiomyopathy")
    intervention = st.text_input("Intervention", "mavacamten")
    phases = st.multiselect("Phase", ["1", "2", "3", "4", "na"])
    max_studies = st.number_input("Max studies", 1, 1000, 100)
    run = st.button("Search")

if run:
    ev = build_evidence(
        Query(
            condition=condition or None,
            intervention=intervention or None,
            phase=phases,
            max_studies=int(max_studies),
        )
    )
    st.markdown(summary_markdown(ev))
    st.subheader("Evidence table")
    st.dataframe(table_rows(ev.trials), use_container_width=True)
    with st.expander("Source path of each extracted field (first trial)"):
        if ev.trials:
            first = ev.trials[0].model_dump()
            st.json({k: v["source"] for k, v in first.items() if isinstance(v, dict)})
