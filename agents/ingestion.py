"""Agent 1: Ingestion.

Pulls live UK postings from Adzuna and Reed, normalises both into a single
schema, and deduplicates across sources before anything reaches the database.

The two sources are not interchangeable and are not used for redundancy:

  Reed    returns the full job description, which the extraction agent needs.
  Adzuna  returns excerpts but exposes salary histograms and regional trend
          data that Reed does not, which the forecasting agent needs.

Adzuna's free tier is roughly 1,000 calls a month, so its calls are batched
rather than polled, and Reed carries the per posting detail.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

# Tokens that appear so often in company names that they add no distinguishing
# value to a dedup key and vary freely between providers.
_COMPANY_NOISE = {
    "ltd", "limited", "llp", "plc", "inc", "incorporated", "group",
    "holdings", "uk", "the", "recruitment", "recruiting", "consulting",
    "consultancy", "solutions", "services", "associates", "partners",
}

# Seniority and contract markers that providers append inconsistently.
_TITLE_NOISE = {
    "permanent", "contract", "temporary", "fulltime", "parttime", "hybrid",
    "remote", "onsite", "urgent", "new", "immediate", "start",
}

_HTML_TAG = re.compile(r"<[^>]+>")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Normalised record
# ---------------------------------------------------------------------------


@dataclass
class Posting:
    """One posting, normalised into a shape both providers map onto."""

    source: str
    source_job_id: str
    title: str
    description: str
    has_full_description: bool
    company: str | None = None
    location: str | None = None
    category: str | None = None
    contract_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "GBP"
    salary_is_predicted: bool = False
    url: str | None = None
    posted_at: date | None = None
    dedup_key: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dedup_key:
            self.dedup_key = build_dedup_key(self.title, self.company, self.location)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return row


# ---------------------------------------------------------------------------
# Text cleaning and deduplication
# ---------------------------------------------------------------------------


def clean_text(value: str | None) -> str:
    """Strip HTML, decode entities and collapse whitespace.

    Reed returns HTML in its descriptions and Adzuna returns entity encoded
    plain text, so both are put through the same cleaner rather than trusting
    either provider's formatting.
    """
    if not value:
        return ""
    text = html.unescape(value)
    text = _HTML_TAG.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE.sub(" ", text).strip()


def _normalise_tokens(value: str | None, noise: set[str]) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = _NON_ALNUM.sub(" ", text.lower())
    tokens = [t for t in text.split() if t and t not in noise]
    return " ".join(sorted(set(tokens)))


def build_dedup_key(title: str, company: str | None, location: str | None) -> str:
    """Build a stable key for matching the same role across both providers.

    Tokens are sorted and deduplicated so that "Data Engineer, Senior" and
    "Senior Data Engineer" collapse to the same key. Noise words that providers
    append inconsistently are dropped first. Location is reduced to its first
    component, since Adzuna reports "London, South East London" where Reed
    reports "London".
    """
    title_part = _normalise_tokens(title, _TITLE_NOISE)
    company_part = _normalise_tokens(company, _COMPANY_NOISE)
    first_location = (location or "").split(",")[0]
    location_part = _normalise_tokens(first_location, set())
    return f"{title_part}|{company_part}|{location_part}"


def deduplicate(postings: Iterable[Posting]) -> tuple[list[Posting], list[Posting]]:
    """Split postings into canonical records and duplicates.

    Where the same role appears on both providers, the record carrying a full
    description wins, because the extraction agent cannot work from an excerpt.
    Where both or neither have full text, the first seen record wins so the
    outcome is deterministic and therefore testable.
    """
    canonical: dict[str, Posting] = {}
    duplicates: list[Posting] = []

    for posting in postings:
        existing = canonical.get(posting.dedup_key)
        if existing is None:
            canonical[posting.dedup_key] = posting
            continue

        if posting.has_full_description and not existing.has_full_description:
            canonical[posting.dedup_key] = posting
            duplicates.append(existing)
        else:
            duplicates.append(posting)

    return list(canonical.values()), duplicates


# ---------------------------------------------------------------------------
# Provider clients
# ---------------------------------------------------------------------------


class JobSource(Protocol):
    name: str

    def fetch(self, query: str, location: str, limit: int) -> list[Posting]: ...


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            # Only the calendar date is kept, so a naive parse is deliberate here.
            parsed = datetime.strptime(value[:19] if "T" in value else value, fmt)  # noqa: DTZ007
            return parsed.date()
        except ValueError:
            continue
    logger.warning("Unrecognised date format from provider: %r", value)
    return None


class AdzunaClient:
    """Breadth and aggregate trend data. Descriptions are excerpts."""

    name = "adzuna"

    def __init__(self, config, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=20.0)

    def fetch(self, query: str, location: str, limit: int = 50) -> list[Posting]:
        url = f"{self.config.base_url}/jobs/{self.config.country}/search/1"
        params = {
            "app_id": self.config.app_id,
            "app_key": self.config.app_key,
            "what": query,
            "where": location,
            "results_per_page": min(limit, self.config.results_per_page),
            "content-type": "application/json",
        }
        response = self._client.get(url, params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        return [self._to_posting(item) for item in results]

    def _to_posting(self, item: dict[str, Any]) -> Posting:
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        return Posting(
            source=self.name,
            source_job_id=str(item.get("id", "")),
            title=clean_text(item.get("title")),
            description=clean_text(item.get("description")),
            # Adzuna truncates descriptions, so extraction must not rely on them.
            has_full_description=False,
            company=clean_text((item.get("company") or {}).get("display_name")) or None,
            location=clean_text((item.get("location") or {}).get("display_name")) or None,
            category=clean_text((item.get("category") or {}).get("label")) or None,
            contract_type=item.get("contract_time"),
            salary_min=float(salary_min) if salary_min is not None else None,
            salary_max=float(salary_max) if salary_max is not None else None,
            salary_is_predicted=str(item.get("salary_is_predicted", "0")) == "1",
            url=item.get("redirect_url"),
            posted_at=_parse_date(item.get("created")),
            raw=item,
        )


class ReedClient:
    """Primary source for per posting detail.

    Reed's /search endpoint returns only a snippet of the description. The
    complete text lives behind /jobs/{jobId}, one request per posting, so
    detail fetching is a separate opt in step rather than something every
    search pays for. The extraction agent cannot parse a snippet, so any
    posting whose detail has not been fetched is flagged accordingly.
    """

    name = "reed"

    # Below this length a description is a stub or a redirect notice rather
    # than a real posting body.
    MIN_FULL_DESCRIPTION_CHARS = 400

    def __init__(
        self,
        config,
        client: httpx.Client | None = None,
        fetch_details: bool = True,
    ) -> None:
        self.config = config
        self.fetch_details = fetch_details
        # Reed uses HTTP basic auth with the API key as the username and an
        # empty password.
        self._client = client or httpx.Client(
            timeout=20.0, auth=(config.api_key, "")
        )

    def fetch(
        self,
        query: str,
        location: str,
        limit: int = 100,
        fetch_details: bool | None = None,
    ) -> list[Posting]:
        params = {
            "keywords": query,
            "locationName": location,
            "resultsToTake": min(limit, self.config.results_per_page),
        }
        response = self._client.get(f"{self.config.base_url}/search", params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        postings = [self._to_posting(item) for item in results]

        should_fetch = self.fetch_details if fetch_details is None else fetch_details
        if should_fetch:
            logger.info("Fetching full descriptions for %d reed postings", len(postings))
            for posting in postings:
                self._enrich_with_detail(posting)

        return postings

    def _enrich_with_detail(self, posting: Posting) -> None:
        """Replace the search snippet with the full description.

        A failure here is logged and skipped rather than raised. The posting
        survives with its snippet and is simply not marked as full, so the
        extraction agent will pass over it instead of parsing a fragment.
        """
        try:
            response = self._client.get(f"{self.config.base_url}/jobs/{posting.source_job_id}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Detail fetch failed for reed job %s: %s", posting.source_job_id, exc)
            return

        detail = response.json()
        description = clean_text(detail.get("jobDescription"))
        if len(description) > len(posting.description):
            posting.description = description
        posting.has_full_description = len(posting.description) >= self.MIN_FULL_DESCRIPTION_CHARS

    def _to_posting(self, item: dict[str, Any]) -> Posting:
        description = clean_text(item.get("jobDescription"))
        return Posting(
            source=self.name,
            source_job_id=str(item.get("jobId", "")),
            title=clean_text(item.get("jobTitle")),
            description=description,
            # The search endpoint returns a snippet. Only a successful detail
            # fetch can set this to True.
            has_full_description=False,
            company=clean_text(item.get("employerName")) or None,
            location=clean_text(item.get("locationName")) or None,
            contract_type="contract" if item.get("contractType") else None,
            salary_min=item.get("minimumSalary"),
            salary_max=item.get("maximumSalary"),
            salary_currency=item.get("currency") or "GBP",
            # Reed salaries are employer stated rather than modelled.
            salary_is_predicted=False,
            url=item.get("jobUrl"),
            posted_at=_parse_date(item.get("date")),
            raw=item,
        )


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


@dataclass
class IngestionResult:
    fetched: int
    canonical: list[Posting]
    duplicates: list[Posting]

    @property
    def inserted(self) -> int:
        return len(self.canonical)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicates)


def run_ingestion(
    sources: list[JobSource],
    queries: list[str],
    location: str,
    limit_per_query: int = 50,
) -> IngestionResult:
    """Fetch across every source and query, then deduplicate the combined set.

    A failure from one provider is logged and skipped rather than aborting the
    run, so a Reed outage still leaves Adzuna trend data flowing.
    """
    collected: list[Posting] = []

    for source in sources:
        for query in queries:
            try:
                batch = source.fetch(query, location, limit_per_query)
            except httpx.HTTPError as exc:
                logger.error("Fetch failed for %s query %r: %s", source.name, query, exc)
                continue
            logger.info("Fetched %d postings from %s for %r", len(batch), source.name, query)
            collected.extend(batch)

    canonical, duplicates = deduplicate(collected)
    logger.info(
        "Ingestion complete: %d fetched, %d canonical, %d duplicates",
        len(collected), len(canonical), len(duplicates),
    )
    return IngestionResult(fetched=len(collected), canonical=canonical, duplicates=duplicates)
