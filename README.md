# JobFit Agent

A six agent system that ingests live UK job postings, extracts the requirements
behind each one, scores them against a CV, forecasts skill demand, and emails a
ranked weekly shortlist automatically.

[![CI](https://github.com/eo-datascience/JobFit-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/eo-datascience/JobFit-Agent/actions/workflows/ci.yml)

## Status

| Agent | Phase | Status |
|---|---|---|
| 1. Ingestion | 1 | Built |
| 2. Skill extraction | 2 | Built |
| 3. Fit scoring | 3 | Not started |
| 4. Demand forecast | 4 | Not started |
| 5. Weekly digest | 5 | Not started |
| 6. Outcome monitor | 6 | Not started |

## Why two job sources

Reed and Adzuna are not used for redundancy. They do different jobs.

Reed is the only one of the two that can supply a complete job description,
which the extraction agent needs in order to parse requirements at all. Its
search endpoint returns only a snippet, so the full text is fetched separately
from its detail endpoint, one request per posting. Adzuna returns excerpts with
no detail endpoint, but exposes salary histograms and regional trend data that
Reed does not, which the forecasting agent needs. Adzuna salaries are frequently modelled rather than employer
stated, so postings carry a `salary_is_predicted` flag and scoring weights a
stated range above an inferred one.

Where the same role appears on both, the record carrying the full description
wins. This is asserted directly in the test suite rather than assumed.

## How extraction stays grounded

Skill detection is deterministic. Every skill is matched literally against the
posting text from a curated taxonomy, and the matched span is kept as evidence,
so a skill cannot be reported unless it genuinely appears. Named entity
recognition was considered and rejected, because general purpose NER models are
not trained on technical skill vocabulary and tag company names as skills.

The language model is reserved for judgements that need one, such as seniority
and whether a requirement is essential rather than desirable. Everything it
returns is checked against the source afterwards, and any skill it claims that
does not appear in the posting is dropped rather than trusted. A failed or
malformed model response leaves the deterministic extraction intact and sets a
rejection flag, so a broken API call never costs a posting.

Keyword search returns roles that merely mention the search terms. An "AI
Creative Director" matched a search for "data scientist" because its text was
saturated with the word AI, yet named no technical tooling at all. A relevance
gate now classifies each posting as in domain or out of domain, using the title
first and the extracted skills as a fallback. Out of domain postings stay in the
database, because the forecasting agent benefits from a wider view of the
market, but they never reach fit scoring or the weekly digest and never cost a
model call.

Postings carry a confidence tier. Reed postings with a full description are
extracted at full confidence. Adzuna excerpts are extracted on a reduced basis
and marked partial, which tells the scoring agent that a missing skill proves
nothing rather than counting against the role.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill in your keys
```

Keys are free and issue instantly from developer.adzuna.com and
reed.co.uk/developers/jobseeker.

## Running

```bash
python run_ingestion.py --dry-run               # fetch and report, write nothing
python run_ingestion.py --dry-run --no-details  # same, but skip Reed detail calls
python run_ingestion.py                         # fetch, deduplicate and persist
python run_extraction.py                        # extract requirements, no API cost
python run_extraction.py --use-model            # also call Claude on full postings
pytest                               # run the suite
ruff check .                         # lint
```

## Notes on quotas

Adzuna's free tier is roughly 1,000 calls a month, about 33 a day. Its calls
are batched for trend data rather than polled per posting, and Reed carries the
per posting detail.
