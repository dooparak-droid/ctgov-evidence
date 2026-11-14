# ctgov-evidence

ctgov-evidence turns ClinicalTrials.gov records into a structured evidence summary in which every value points back to the field it came from. An optional LLM-written paragraph is checked sentence by sentence against those records, and sentences that cannot be supported are marked or removed.

This is the same idea as codelist-rag, which checks every code an LLM proposes against SNOMED-CT before accepting it.

## What it does

Input is a search (condition and/or intervention, with optional phase and status filters) or a list of NCT IDs. Output is written to a folder:

| File | Contents |
|---|---|
| `trials.json` | One normalised record per trial. Each field is stored as `{value, source}`, where `source` is the path in the original record, for example `NCT04349072:protocolSection.designModule.enrollmentInfo.count`. A `meta` block holds the query and retrieval time. |
| `evidence_table.csv` / `.md` | One row per trial: NCT ID, title, sponsor, phase, status, enrolment and its type, start and completion dates, design, first primary outcome, results posted. |
| `summary.md` / `summary.json` | Counts by phase, status and study type; enrolment totals; lead sponsors; primary outcome measures; trials with posted results. Computed in code, not by an LLM. |
| `narrative.md` | Only with `--narrative`. A short paragraph written by an LLM, with a verification line. |

Fields that are missing in the registry stay `None` and keep their source path. Nothing is guessed or filled in.

## Install

Python 3.11 or later.

```
pip install -e .                # core: search, extraction, summary, CLI
pip install -e ".[narrative]"   # adds the Anthropic SDK for --narrative
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

Searches stop at `--max-studies` (default 200). If the registry has more matches, the output says so.

### Narrative and verification

`--narrative` sends the structured trials (values only, not the raw registry JSON) to a Claude model and asks for one paragraph in which every sentence ends with the NCT IDs it is about. The key is read from `ANTHROPIC_API_KEY`. Without it, the step is skipped and everything else runs normally. The model can be set with `--model` or `CTGOV_EVIDENCE_MODEL`.

`verify.py` then checks each sentence against the trials it cites:

- The sentence must cite at least one NCT ID that is in the retrieved set.
- Every number must be explainable from the cited trials: an enrolment figure, the sum of enrolments, the number of cited trials, a count of cited trials sharing a status, phase or sponsor, a year in a date, or a time-frame figure next to a time unit. The size of the whole retrieved set is also accepted.
- Phases and statuses named in the sentence must belong to a cited trial.
- Sponsor and intervention names that appear in the retrieved set must belong to a cited trial. Organisation-like names that appear nowhere in the retrieved records are flagged.
- A claim about posted results must agree with `hasResults` for every cited trial.

Failed sentences are tagged `[unverified]`, or dropped with `--drop-unverified`. The output reports `n verified / n total`, and `narrative_verification.json` lists the reason for each failure. The test suite includes a sentence with a deliberately wrong enrolment figure.

### MCP server

`ctgov-evidence-mcp` runs a stdio MCP server with two tools, `search_trials` (compact rows) and `build_evidence` (full records with source paths, and the summary). To use it from Claude Code:

```
claude mcp add ctgov-evidence -- ctgov-evidence-mcp
```

### Streamlit viewer

`streamlit run src/ctgov_evidence/app.py` opens a form over the same pipeline. It is a convenience viewer and is not needed for anything else.

## Example

`examples/hcm_mavacamten/` holds the output for condition "hypertrophic cardiomyopathy", intervention "mavacamten" (44 trials at the time of retrieval, 16 October 2026). To reproduce it:

```
pip install -e .
ctgov-evidence search --condition "hypertrophic cardiomyopathy" --intervention mavacamten --out out/
```

The registry changes over time, so counts will drift from the committed files.

## How it is built

```
src/ctgov_evidence/
  client.py     API v2 calls, paging, retries, throttling
  models.py     pydantic schema (Sourced[T], Trial, Summary, Evidence)
  extract.py    raw JSON to Trial
  summarise.py  deterministic aggregates and output files
  narrative.py  optional LLM paragraph
  verify.py     checks narrative sentences against Trials
  cli.py        command line
  mcp_server.py MCP tools
```

Tests run offline against saved real API responses in `tests/fixtures/`, and the suite refuses network connections. CI runs `ruff` and `pytest`.

## Limitations

- Registry data only. The tool summarises what trials registered and posted, not published efficacy results.
- Enrolment is often an estimate for ongoing trials. Actual and estimated figures are kept separate and never added together.
- A trial registered under two phases (for example Phase 2 and Phase 3) is counted in its own "Phase 2 / Phase 3" row, so the phase counts add up to the number of trials.
- Search relevance is ClinicalTrials.gov's own. A search can return trials that mention the intervention only in passing, and can miss trials that use a different drug name.
- Primary outcome measures are free text, so the same endpoint worded differently is counted as two measures. Only whitespace and letter case are normalised.
- The verifier checks facts against registry fields. It does not judge interpretation or clinical meaning, and it can only check the claim types listed above. A sentence that makes a claim of another kind, such as a causal statement, is not caught by the numbers and names it contains.
- The verifier is conservative. A correct sentence that cites more or fewer trials than it is about can be flagged.

## Licence

MIT.
