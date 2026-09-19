# JobFit Agent

A six agent system that ingests live UK job postings, extracts the requirements
behind each one, scores them against a CV, forecasts skill demand, and emails a
ranked weekly shortlist automatically.

[![CI](https://github.com/eo-datascience/JobFit-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/eo-datascience/JobFit-Agent/actions/workflows/ci.yml)

## Status

| Agent | Phase | Status |
|---|---|---|
| 1. Ingestion | 1 | Built |
| 2. Skill extraction | 2 | Not started |
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
pytest                               # run the suite
ruff check .                         # lint
```

## Notes on quotas

Adzuna's free tier is roughly 1,000 calls a month, about 33 a day. Its calls
are batched for trend data rather than polled per posting, and Reed carries the
per posting detail.
