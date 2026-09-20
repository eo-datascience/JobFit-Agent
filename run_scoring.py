"""Run the pipeline end to end: ingest, extract, then score against your CV.

Usage:
    python run_scoring.py                  # score with cv.yml
    python run_scoring.py --cv cv.yml      # explicit path
    python run_scoring.py --top 20         # show more results
    python run_scoring.py --min-score 60   # only roles worth a look
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from agents.cv import CV
from agents.extraction import extract_many, in_domain_only
from agents.ingestion import AdzunaClient, ReedClient, run_ingestion
from agents.scoring import explain, score
from config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("jobfit.scoring")


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: fit scoring")
    parser.add_argument("--cv", default="cv.yml", help="Path to your CV file")
    parser.add_argument("--limit", type=int, default=25, help="Postings per query per source")
    parser.add_argument("--top", type=int, default=10, help="How many results to show")
    parser.add_argument("--min-score", type=int, default=0, help="Hide anything below this")
    args = parser.parse_args()

    cv_path = Path(args.cv)
    if not cv_path.exists():
        logger.error("No CV found at %s", cv_path)
        logger.error("Copy cv.example.yml to cv.yml and edit it, then run this again.")
        return 1

    load_dotenv()
    settings = Settings.from_env()
    candidate = CV.from_file(cv_path)

    logger.info("Loaded CV for %s: %s, %s skills declared.",
                candidate.name, candidate.seniority, len(candidate.skills))

    result = run_ingestion(
        sources=[ReedClient(settings.reed), AdzunaClient(settings.adzuna)],
        queries=settings.search_queries,
        location=settings.search_location,
        limit_per_query=args.limit,
    )

    requirements = in_domain_only(extract_many(result.canonical))
    by_id = {p.source_job_id: p for p in result.canonical}

    scored = []
    for req in requirements:
        posting = by_id.get(req.posting_id)
        if posting is None:
            continue
        fit = score(
            candidate,
            req,
            salary_min=posting.salary_min,
            salary_max=posting.salary_max,
            salary_is_predicted=posting.salary_is_predicted,
            location=posting.location,
        )
        scored.append((fit, posting))

    # Sorted so a fully analysed role always outranks a provisional one.
    scored.sort(key=lambda pair: pair[0].rank_key, reverse=True)
    shown = [pair for pair in scored if pair[0].total >= args.min_score][: args.top]

    logger.info("")
    logger.info("=" * 78)
    logger.info("TOP MATCHES FOR %s", candidate.name.upper())
    logger.info("=" * 78)

    for fit, posting in shown:
        logger.info("")
        marker = "  (provisional)" if fit.is_provisional else ""
        logger.info("  %3d/100%s  %s", fit.total, marker, posting.title)
        logger.info("           %s, %s", posting.company or "unknown company", posting.location or "")
        logger.info("           %s", explain(fit))
        if fit.missing_essential:
            logger.info("           Missing: %s", ", ".join(fit.missing_essential))
        logger.info("           %s", posting.url or "")

    if not shown:
        logger.info("")
        logger.info("  Nothing scored at or above %d. Try lowering --min-score.", args.min_score)

    if scored:
        full = [f for f, _ in scored if not f.is_provisional]
        provisional = [f for f, _ in scored if f.is_provisional]
        logger.info("")
        if full:
            logger.info(
                "%d fully analysed postings. Average %d, best %d.",
                len(full), round(sum(f.total for f in full) / len(full)), max(f.total for f in full),
            )
        if provisional:
            logger.info(
                "%d provisional, scored without skills and ranked below the above.",
                len(provisional),
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
