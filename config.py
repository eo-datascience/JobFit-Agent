"""Central configuration for JobFit Agent.

Every secret is read from the environment. Nothing is hardcoded, so the same
code runs locally and on Railway without modification.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from agents.domains import DOMAINS, PRIMARY_DOMAIN


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your .env file locally or in the Railway dashboard in production."
        )
    return value


@dataclass(frozen=True)
class AdzunaConfig:
    """Adzuna free tier allows roughly 1,000 calls a month, about 33 a day.

    Adzuna descriptions are excerpts rather than full text and its salaries are
    frequently modelled rather than employer stated, so this source is used for
    breadth and for the aggregate trend data that feeds the forecasting agent.
    """

    app_id: str
    app_key: str
    country: str = "gb"
    base_url: str = "https://api.adzuna.com/v1/api"
    results_per_page: int = 50
    monthly_call_budget: int = 1000

    @classmethod
    def from_env(cls) -> AdzunaConfig:
        return cls(app_id=_require("ADZUNA_APP_ID"), app_key=_require("ADZUNA_APP_KEY"))


@dataclass(frozen=True)
class ReedConfig:
    """Reed returns the full job description, which is what the extraction
    agent needs. This is the primary source for per posting detail.
    """

    api_key: str
    base_url: str = "https://www.reed.co.uk/api/1.0"
    results_per_page: int = 100

    @classmethod
    def from_env(cls) -> ReedConfig:
        return cls(api_key=_require("REED_API_KEY"))


@dataclass(frozen=True)
class Settings:
    adzuna: AdzunaConfig
    reed: ReedConfig
    # The digest's queries. Deliberately only the primary field, so the weekly
    # email stays as narrow as it has always been.
    search_queries: list[str] = field(
        default_factory=lambda: list(DOMAINS[PRIMARY_DOMAIN].queries)
    )
    # The other fields exist so a visitor to the public site can score their own
    # CV against real roles in their line of work. They are fetched shallower
    # and never reach the digest, the forecasting or the outcome monitor.
    wider_sweep: bool = True
    wider_sweep_limit: int = 20
    search_location: str = "London"
    request_timeout_seconds: float = 20.0
    max_retries: int = 3
    # Optional. Only persisting postings with run_ingestion.py uses it. The
    # weekly digest keeps its state in plain files, so requiring a database at
    # startup would stop the scheduled job before it did anything.
    database_url: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            adzuna=AdzunaConfig.from_env(),
            reed=ReedConfig.from_env(),
            database_url=os.environ.get("DATABASE_URL") or None,
        )
