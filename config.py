"""Central configuration for JobFit Agent.

Every secret is read from the environment. Nothing is hardcoded, so the same
code runs locally and on Railway without modification.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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
    def from_env(cls) -> "AdzunaConfig":
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
    def from_env(cls) -> "ReedConfig":
        return cls(api_key=_require("REED_API_KEY"))


@dataclass(frozen=True)
class Settings:
    database_url: str
    adzuna: AdzunaConfig
    reed: ReedConfig
    search_queries: list[str] = field(
        default_factory=lambda: [
            "data scientist",
            "data engineer",
            "machine learning engineer",
            "data analyst",
        ]
    )
    search_location: str = "London"
    request_timeout_seconds: float = 20.0
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_require("DATABASE_URL"),
            adzuna=AdzunaConfig.from_env(),
            reed=ReedConfig.from_env(),
        )
