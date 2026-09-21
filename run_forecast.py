"""Run Agent 4: demand forecasting.

Two sources of history, and the agent prefers the better one.

    Snapshots   Real history, one row per weekly run. Accurate, but empty
                until the pipeline has been running for a month or more.
    Bootstrap   History reconstructed from the dates postings were published.
                Available immediately, less reliable, clearly labelled.

Usage:
    python run_forecast.py                  # bootstrap if no snapshots exist
    python run_forecast.py --bootstrap      # force reconstruction
    python run_forecast.py --snapshot       # record this run into history
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from agents.cv import CV
from agents.extraction import extract_many, in_domain_only
from agents.forecasting import (
    Trend,
    build_bootstrap_report,
    build_report_from_series,
    today,
)
from agents.ingestion import AdzunaClient, ReedClient, run_ingestion
from config import Settings
from db import history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)
logger = logging.getLogger("jobfit.forecast")

HISTORY_PATH = Path("data/skill_history.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: demand forecasting")
    parser.add_argument("--limit", type=int, default=50, help="Postings per query per source")
    parser.add_argument("--bootstrap", action="store_true", help="Force reconstruction from posting dates")
    parser.add_argument("--snapshot", action="store_true", help="Record this run into the history store")
    parser.add_argument("--cv", default="cv.yml", help="Used to flag rising skills you lack")
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()

    result = run_ingestion(
        sources=[ReedClient(settings.reed), AdzunaClient(settings.adzuna)],
        queries=settings.search_queries,
        location=settings.search_location,
        limit_per_query=args.limit,
    )
    requirements = in_domain_only(extract_many(result.canonical))

    if args.snapshot:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        history.append(history.summarise(requirements, run_date=today()), HISTORY_PATH)
        logger.info("Recorded this run into %s", HISTORY_PATH)

    stored = history.load(HISTORY_PATH) if HISTORY_PATH.exists() else []
    series = history.as_series(stored) if stored else {}
    weeks_available = len({week for weeks in series.values() for week in weeks})

    if args.bootstrap or weeks_available < 4:
        if not args.bootstrap:
            logger.info(
                "Only %d week(s) of recorded history. Reconstructing from posting dates instead.",
                weeks_available,
            )
        posting_dates = {p.source_job_id: p.posted_at for p in result.canonical}
        report = build_bootstrap_report(requirements, posting_dates)
        basis = "reconstructed from posting dates"
    else:
        report = build_report_from_series(series)
        basis = f"{weeks_available} weeks of recorded history"

    logger.info("")
    logger.info("=" * 78)
    logger.info("SKILL DEMAND REPORT  (%s)", basis)
    logger.info("=" * 78)

    unit = report.rate_unit
    is_share = unit.startswith("%")

    def fmt_rate(value: float) -> str:
        return f"{value:.0f}% of postings" if is_share else f"{value:.1f} per week"

    uniform = report.uniform_movement
    if uniform is not None:
        logger.warning("")
        logger.warning(
            "Nearly every trending skill is %s at once. Real markets rarely move "
            "like that, so this is more likely a shift in the data than in demand. "
            "Treat the trends below with caution.",
            uniform.value,
        )

    logger.info("")
    logger.info("Most asked for:")
    for demand in report.most_demanded(12):
        logger.info("    %-22s now %-20s %s", demand.skill, fmt_rate(demand.current_weekly_rate), demand.note)

    def fmt_change(demand) -> str:
        # Growth from a zero baseline carries no meaningful percentage.
        if demand.current_weekly_rate <= 0:
            return "emerging"
        # For shares, points are the honest measure. Three percent to seven
        # point six percent is plus four point six points, and calling it
        # "+155%" overstates a move of a few listings.
        if is_share and demand.change_points is not None:
            return f"{demand.change_points:+.1f} pts"
        return f"{demand.change_pct:+.0f}%"

    for label, movers in (("Rising", report.rising(8)), ("Falling", report.falling(8))):
        if movers:
            logger.info("")
            logger.info("%s:", label)
            for demand in movers:
                logger.info(
                    "    %-22s %-10s now %s",
                    demand.skill, fmt_change(demand), fmt_rate(demand.current_weekly_rate),
                )

    cv_path = Path(args.cv)
    if cv_path.exists():
        candidate = CV.from_file(cv_path)
        gaps = [
            d for d in report.rising(20)
            if d.skill not in candidate.skills
        ]
        if gaps:
            logger.info("")
            logger.info("Rising skills you do not have:")
            for demand in gaps[:8]:
                logger.info("    %-22s %s", demand.skill, fmt_change(demand))

    unknown = sum(1 for s in report.skills if s.trend is Trend.INSUFFICIENT_HISTORY)
    if unknown:
        logger.info("")
        logger.info(
            "%d of %d skills lack the history to call a trend. Run with --snapshot "
            "weekly and this shrinks.",
            unknown, len(report.skills),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
