# ctgov-evidence

ctgov-evidence turns ClinicalTrials.gov records into a structured evidence summary, and every value in it points back to the field it came from. If you ask for an LLM-written paragraph as well, each of its sentences is checked against those records. Sentences that can't be supported are marked or removed.

A live demo is at https://ctgov-evidence-yan7vnzu63pgnrdn3um6bl.streamlit.app/

The idea is the same as in codelist-rag, which checks every code an LLM proposes against SNOMED-CT before accepting it.

## What it does

You give it a search (a condition, an intervention, or both, with optional phase and status filters) or a list of NCT IDs. It writes these files to a folder:

| File | Contents |
|---|---|
| `trials.json` | One normalised record per trial. Each field is stored as `{value, source}`, where `source` is the path in the original record, for example `NCT04349072:protocolSection.designModule.enrollmentInfo.count`. A `meta` block holds the query and the retrieval time. |
| `evidence_table.csv` / `.md` | One row per trial with NCT ID, title, sponsor, phase, status, enrolment and its type, start and completion dates, design, first primary outcome, and whether results are posted. |
| `summary.md` / `summary.json` | Counts by phase, status and study type, enrolment totals, lead sponsors, primary outcome measures, and trials with posted results. These are computed in code with no LLM involved. |
| `results_gap.csv` / `.md` | Finished interventional trials with no results posted more than 12 months after primary completion, grouped by how likely the reporting rule is to apply. Details are under "Results gap check". |
| `narrative.md` | Written only with `--narrative`. A short paragraph from an LLM, with a verification line. |

A field that is missing in the registry stays `None`, and it still records the path that was looked up.

## Install

Python 3.11 or later.

```
pip install -e .                # core: search, extraction, summary, CLI
pip install -e ".[narrative]"   # only needed for the Anthropic provider; Gemini needs nothing extra
pip install -e ".[mcp]"         # adds the MCP server
pip install -e ".[app]"         # adds the Streamlit viewer
pip install -e ".[dev]"         # tests and lint
```

## Use

Command line:

```
ctgov-evidence search --condition "hypertrophic cardiomyopathy" --intervention mavacamten --out out/
ctgov-evidence search --condition obesity --intervention semaglutide --phase 3 --status completed
ctgov-evidence fetch NCT04349072 NCT05174416 --out out/
```

Python:

```python
from ctgov_evidence import Query, build_evidence

ev = build_evidence(Query(condition="hypertrophic cardiomyopathy", intervention="mavacamten"))
ev.summary.by_phase
ev.trials[0].enrollment  # Sourced(value=..., source="NCT...:protocolSection....")
```

Searches stop at `--max-studies` (default 200), and the output says so when the registry has more matches.

### Results gap check

US law (FDAAA 801) generally expects the sponsors of "applicable clinical trials" to submit summary results to ClinicalTrials.gov within 12 months of the primary completion date. The tool lists finished (completed or terminated) interventional trials that are past that point with no results posted, as of the retrieval date.

The registry doesn't say whether a trial is legally covered, so flagged trials fall into four groups:

- Likely applicable: marked as an FDA-regulated drug or device, and not Phase 1 only.
- Probably not covered: marked as not FDA-regulated.
- Cannot tell: no FDA-regulation flag is recorded. In a 300-trial heart failure search, the flags were empty for 203 of the 217 trials that started before 2017 and present for all 83 that started later, so this group is mostly older records.
- Probably exempt: Phase 1 only.

A flag means results are missing where they would normally be expected. It does not show non-compliance. The results may be published in a journal, a sponsor can certify a delay, and the rules have details that registry fields don't capture, such as the exemption for small device feasibility studies. The check doesn't search the literature. For trials that did post results, the tool also reports the median time from primary completion to first submission.

### Narrative and verification

`--narrative` sends the structured trials to an LLM (values only, without the raw registry JSON) and asks for one paragraph in which every sentence ends with the NCT IDs it is about.

Two providers are supported. If `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) is set, Gemini is used. Otherwise Anthropic is used when `ANTHROPIC_API_KEY` is set. You can choose with `--provider gemini|anthropic` and set the model with `--model`. The default Gemini model is `gemini-3.5-flash`, and after two overload errors (HTTP 503) the call switches to `gemini-3.1-flash-lite`. With no key, the narrative step is skipped and everything else runs as normal. The key travels in a request header and is never written to the output files.

`verify.py` checks each sentence against the trials it cites, whichever model wrote it. A sentence passes only if all of these hold:

- It cites at least one NCT ID from the retrieved set.
- A participant count written next to an NCT ID (for example "NCT05719805 with 84 participants") matches that trial's enrolment, and "estimated" or "actual" matches its enrolment type.
- Every other number can be explained from the cited trials. That means an enrolment figure, the sum of enrolments, the number of cited trials, a count of cited trials that share a status, phase or sponsor, a year in a date, or a time-frame figure beside a time unit. The size of the whole retrieved set is also accepted.
- Phases and statuses named in the sentence belong to a cited trial, and so do the words "observational", "interventional" and "randomized".
- Sponsor and intervention names from the retrieved set belong to a cited trial. Organisation-like names that appear nowhere in the retrieved records are flagged.
- A claim about posted results agrees with `hasResults` for every cited trial.

Sentences that fail are tagged `[unverified]`, or dropped with `--drop-unverified`. The run reports `n verified / n total`. `narrative_verification.json` gives the reason for each failure, and `narrative_raw.txt` keeps the model's text before any marking.

The tests use real Gemini output on the example query. One paragraph was checked by hand and passes in full. Another contains an error (an actual enrolment of 2,000 described as an estimate), and the verifier catches it. A third test swaps two enrolment figures in the accurate paragraph and confirms that it then fails.

### MCP server

`ctgov-evidence-mcp` runs a stdio MCP server with two tools, `search_trials` (compact rows) and `build_evidence` (full records with source paths, plus the summary). To add it to Claude Code:

```
claude mcp add ctgov-evidence -- ctgov-evidence-mcp
```

### Streamlit viewer

`streamlit run src/ctgov_evidence/app.py` opens a page over the same pipeline. It has a summary, the evidence table, the results gap, a per-trial view that shows the source path of every value, and the verified narrative. For the narrative, the page reads `GEMINI_API_KEY` from Streamlit secrets or the environment and limits that shared key to three narratives per session. Visitors can paste their own key instead, and it isn't stored. `requirements.txt` supports deployment on Streamlit Community Cloud.

## Example

`examples/hcm_mavacamten/` has the output for condition "hypertrophic cardiomyopathy" and intervention "mavacamten" (44 trials when it was retrieved on 15 November 2026). It also includes a narrative written by Gemini 3.5 Flash in which all 7 sentences verified. To reproduce it:

```
pip install -e .
ctgov-evidence search --condition "hypertrophic cardiomyopathy" --intervention mavacamten --out out/
```

The registry changes over time, so your counts will drift from the committed files.

## How it is built

```
src/ctgov_evidence/
  client.py      API v2 calls, paging, retries, throttling
  models.py      pydantic schema (Sourced[T], Trial, Summary, Evidence)
  extract.py     raw JSON to Trial
  pipeline.py    build_evidence: query in, Evidence out
  summarise.py   deterministic aggregates and output files
  gap.py         results gap check
  labels.py      phase labels shared across modules
  narrative.py   optional LLM paragraph
  verify.py      checks narrative sentences against Trials
  cli.py         command line
  mcp_server.py  MCP tools
  app.py         Streamlit viewer
```

Tests run offline against saved real API responses in `tests/fixtures/`, and the test suite refuses network connections. CI runs `ruff` and `pytest`.

## Limitations

- Registry data only. The tool summarises what trials registered and posted, not published efficacy results.
- Enrolment is often an estimate for ongoing trials. Actual and estimated figures are kept separate and never added together.
- A trial registered under two phases, for example Phase 2 and Phase 3, gets its own "Phase 2 / Phase 3" row, so the phase counts add up to the number of trials.
- Search relevance is ClinicalTrials.gov's own. A search can return trials that mention the intervention only in passing, and it can miss trials that use a different drug name.
- Primary outcome measures are free text, so the same endpoint worded two ways counts as two measures. Only whitespace and letter case are normalised.
- The verifier checks facts against registry fields. It can't judge interpretation or clinical meaning, and it only covers the claim types listed above. A sentence such as "evaluated the efficacy and safety", or a causal statement, passes as long as its numbers and names are supported.
- A claimed range ("from 13 to 251 participants") is checked number by number, not as a minimum and maximum. A sponsor name is checked against the cited trials as a group, not against each trial in a list.
- The verifier is conservative. A correct sentence that cites more or fewer trials than it is about can be flagged.

## Licence

MIT.
