"""Snapshot history.

The forecasting agent needs a series, and a single run produces one point. This
records what each ingestion run saw so that history accumulates week by week
and the forecast becomes meaningful over time rather than at first run.

Deliberately file based rather than a database table. History is small, a few
kilobytes a week, and keeping it in a readable JSON file means the candidate
can inspect or correct it without a database client. It also means the
forecasting agent works before Postgres is configured, which matters when the
project is cloned by someone who wants to see it run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from agents.extraction import Requirements
from paths import HISTORY_PATH

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = HISTORY_PATH


@dataclass
class Snapshot:
    """One ingestion run, reduced to what the forecaster needs.

    Only skill counts are kept, not the postings themselves. History should
    stay small and should not quietly become a second copy of the database.
    """

    run_date: date
    postings_seen: int
    skill_counts: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "run_date": self.run_date.isoformat(),
            "postings_seen": self.postings_seen,
            "skill_counts": self.skill_counts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        return cls(
            run_date=date.fromisoformat(data["run_date"]),
            postings_seen=int(data.get("postings_seen", 0)),
            skill_counts={str(k): int(v) for k, v in data.get("skill_counts", {}).items()},
        )


def summarise(requirements: list[Requirements], run_date: date | None = None) -> Snapshot:
    """Reduce a run to per skill posting counts.

    Counts postings rather than mentions, so a verbose posting repeating
    "Python" a dozen times contributes one, same as a terse one.
    """
    counts: dict[str, int] = {}
    for requirement in requirements:
        for skill in set(requirement.skill_names):
            counts[skill] = counts.get(skill, 0) + 1

    return Snapshot(
        run_date=run_date or datetime.now(UTC).date(),
        postings_seen=len(requirements),
        skill_counts=counts,
    )


def load(path: str | Path = DEFAULT_HISTORY_PATH) -> list[Snapshot]:
    target = Path(path)
    if not target.exists():
        return []

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # A corrupt history file must not stop the pipeline. Losing trend data
        # is recoverable, losing the run is not.
        logger.error("History at %s is unreadable and will be ignored: %s", target, exc)
        return []

    return [Snapshot.from_dict(item) for item in raw]


def append(snapshot: Snapshot, path: str | Path = DEFAULT_HISTORY_PATH) -> list[Snapshot]:
    """Add a snapshot, replacing any existing entry for the same date.

    Re-running on the same day overwrites rather than double counting, so
    testing the pipeline repeatedly does not inflate that day's demand.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    history = [s for s in load(target) if s.run_date != snapshot.run_date]
    history.append(snapshot)
    history.sort(key=lambda s: s.run_date)

    target.write_text(
        json.dumps([s.to_dict() for s in history], indent=2),
        encoding="utf-8",
    )
    logger.info("History now holds %d runs, earliest %s", len(history), history[0].run_date)
    return history


def as_series(history: list[Snapshot]) -> dict[str, dict[date, int]]:
    """Reshape history into per skill date series for the forecaster."""
    series: dict[str, dict[date, int]] = {}
    for snapshot in history:
        for skill, count in snapshot.skill_counts.items():
            series.setdefault(skill, {})[snapshot.run_date] = count
    return series
