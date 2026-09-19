"""Tests for Agent 1: Ingestion.

No live API calls. Provider responses are stubbed so the suite is fast,
deterministic and safe to run in CI without secrets.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from agents.ingestion import (
    AdzunaClient,
    Posting,
    ReedClient,
    build_dedup_key,
    clean_text,
    deduplicate,
    run_ingestion,
)
from config import AdzunaConfig, ReedConfig

# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<p>Senior <b>Data</b> Engineer</p>", "Senior Data Engineer"),
        ("Python &amp; SQL required", "Python & SQL required"),
        ("  multiple   spaces\n\tcollapsed  ", "multiple spaces collapsed"),
        (None, ""),
        ("", ""),
    ],
)
def test_clean_text_strips_markup_and_normalises_whitespace(raw, expected):
    assert clean_text(raw) == expected


# ---------------------------------------------------------------------------
# Deduplication key
# ---------------------------------------------------------------------------


def test_dedup_key_is_order_independent():
    """Providers word the same title differently. The key must not care."""
    a = build_dedup_key("Senior Data Engineer", "Acme Ltd", "London")
    b = build_dedup_key("Data Engineer, Senior", "Acme Limited", "London")
    assert a == b


def test_dedup_key_ignores_company_suffixes():
    assert build_dedup_key("Data Analyst", "Bright Group Ltd", "Leeds") == build_dedup_key(
        "Data Analyst", "Bright", "Leeds"
    )


def test_dedup_key_reduces_location_to_first_component():
    """Adzuna reports a fuller location string than Reed for the same role."""
    assert build_dedup_key("Data Scientist", "Acme", "London, South East London") == (
        build_dedup_key("Data Scientist", "Acme", "London")
    )


def test_dedup_key_separates_genuinely_different_roles():
    assert build_dedup_key("Data Engineer", "Acme", "London") != build_dedup_key(
        "Data Scientist", "Acme", "London"
    )


# ---------------------------------------------------------------------------
# Deduplication behaviour
# ---------------------------------------------------------------------------


def _posting(source: str, title: str, full: bool, job_id: str = "1") -> Posting:
    return Posting(
        source=source,
        source_job_id=job_id,
        title=title,
        description="x" * (500 if full else 50),
        has_full_description=full,
        company="Acme Ltd",
        location="London",
    )


def test_duplicate_across_sources_prefers_the_full_description():
    """This is the whole point of using two providers, so it is asserted
    directly rather than assumed."""
    adzuna = _posting("adzuna", "Data Engineer", full=False, job_id="a1")
    reed = _posting("reed", "Data Engineer", full=True, job_id="r1")

    canonical, duplicates = deduplicate([adzuna, reed])

    assert len(canonical) == 1
    assert canonical[0].source == "reed"
    assert [d.source for d in duplicates] == ["adzuna"]


def test_full_description_wins_regardless_of_arrival_order():
    reed = _posting("reed", "Data Engineer", full=True, job_id="r1")
    adzuna = _posting("adzuna", "Data Engineer", full=False, job_id="a1")

    canonical, _ = deduplicate([reed, adzuna])

    assert canonical[0].source == "reed"


def test_distinct_roles_are_both_retained():
    canonical, duplicates = deduplicate(
        [
            _posting("reed", "Data Engineer", full=True, job_id="r1"),
            _posting("reed", "Machine Learning Engineer", full=True, job_id="r2"),
        ]
    )
    assert len(canonical) == 2
    assert duplicates == []


# ---------------------------------------------------------------------------
# Provider parsing
# ---------------------------------------------------------------------------


ADZUNA_RESPONSE = {
    "results": [
        {
            "id": "4213",
            "title": "Data Engineer",
            "description": "Build pipelines using <b>Python</b> and Airflow&hellip;",
            "company": {"display_name": "Acme Ltd"},
            "location": {"display_name": "London, South East London"},
            "category": {"label": "IT Jobs"},
            "contract_time": "full_time",
            "salary_min": 55000,
            "salary_max": 70000,
            "salary_is_predicted": "1",
            "redirect_url": "https://adzuna.example/4213",
            "created": "2026-09-01T09:30:00Z",
        }
    ]
}

REED_SEARCH_RESPONSE = {
    "results": [
        {
            "jobId": 998877,
            "jobTitle": "Data Engineer",
            "jobDescription": "Snippet of the description, truncated by Reed's search endpoint...",
            "employerName": "Acme Limited",
            "locationName": "London",
            "minimumSalary": 55000,
            "maximumSalary": 70000,
            "currency": "GBP",
            "jobUrl": "https://reed.example/998877",
            "date": "01/09/2026",
        }
    ]
}


def _stub_client(payload: dict) -> httpx.Client:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    return httpx.Client(transport=transport)


def test_adzuna_parsing_marks_descriptions_as_partial():
    client = AdzunaClient(
        AdzunaConfig(app_id="id", app_key="key"), client=_stub_client(ADZUNA_RESPONSE)
    )
    posting = client.fetch("data engineer", "London")[0]

    assert posting.source == "adzuna"
    assert posting.title == "Data Engineer"
    assert posting.company == "Acme Ltd"
    assert posting.salary_is_predicted is True
    assert posting.has_full_description is False
    assert "<b>" not in posting.description
    assert posting.posted_at == date(2026, 9, 1)


def _reed_two_endpoint_client(detail_body: str, detail_status: int = 200) -> httpx.Client:
    """Stub both Reed endpoints: /search returns a snippet, /jobs/{id} the full text."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/jobs/" in request.url.path:
            return httpx.Response(detail_status, json={"jobDescription": detail_body})
        return httpx.Response(200, json=REED_SEARCH_RESPONSE)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_reed_search_alone_is_never_treated_as_a_full_description():
    """Reed's /search endpoint returns a snippet. Without a detail fetch the
    posting must not be offered to the extraction agent as complete."""
    client = ReedClient(ReedConfig(api_key="key"), client=_stub_client(REED_SEARCH_RESPONSE))
    posting = client.fetch("data engineer", "London", fetch_details=False)[0]

    assert posting.has_full_description is False
    assert posting.salary_is_predicted is False
    assert posting.posted_at == date(2026, 9, 1)


def test_reed_detail_fetch_replaces_the_snippet_and_marks_it_full():
    full_body = "<p>" + ("Detailed responsibilities. " * 40) + "</p>"
    client = ReedClient(ReedConfig(api_key="key"), client=_reed_two_endpoint_client(full_body))

    posting = client.fetch("data engineer", "London")[0]

    assert posting.has_full_description is True
    assert len(posting.description) > 400
    assert "<p>" not in posting.description


def test_reed_detail_fetch_failure_leaves_the_posting_usable_but_not_full():
    """A failed detail call must not lose the posting, and must not pretend
    the snippet is the whole description."""
    client = ReedClient(
        ReedConfig(api_key="key"), client=_reed_two_endpoint_client("", detail_status=500)
    )

    postings = client.fetch("data engineer", "London")

    assert len(postings) == 1
    assert postings[0].has_full_description is False


def test_reed_detail_fetch_does_not_mark_a_stub_body_as_full():
    client = ReedClient(
        ReedConfig(api_key="key"), client=_reed_two_endpoint_client("See our website.")
    )

    assert client.fetch("data engineer", "London")[0].has_full_description is False


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_run_ingestion_deduplicates_the_same_role_across_both_providers():
    adzuna = AdzunaClient(
        AdzunaConfig(app_id="id", app_key="key"), client=_stub_client(ADZUNA_RESPONSE)
    )
    reed = ReedClient(
        ReedConfig(api_key="key"),
        client=_reed_two_endpoint_client("<p>" + ("Detail. " * 80) + "</p>"),
    )

    result = run_ingestion([adzuna, reed], queries=["data engineer"], location="London")

    assert result.fetched == 2
    assert result.inserted == 1
    assert result.duplicate_count == 1
    assert result.canonical[0].source == "reed"


def test_one_failing_provider_does_not_abort_the_run():
    """A Reed outage must still leave Adzuna trend data flowing."""

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable", request=request)

    adzuna = AdzunaClient(
        AdzunaConfig(app_id="id", app_key="key"), client=_stub_client(ADZUNA_RESPONSE)
    )
    reed = ReedClient(
        ReedConfig(api_key="key"),
        client=httpx.Client(transport=httpx.MockTransport(failing)),
    )

    result = run_ingestion([adzuna, reed], queries=["data engineer"], location="London")

    assert result.inserted == 1
    assert result.canonical[0].source == "adzuna"
