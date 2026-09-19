"""Run Agent 1 end to end.

Usage:
    python run_ingestion.py              # fetch, deduplicate and persist
    python run_ingestion.py --dry-run    # fetch and report, write nothing
"""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from agents.ingestion import AdzunaClient, ReedClient, run_ingestion
from config import Settings
from db import repository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

# httpx logs the full request URL at INFO level, which for Adzuna includes
# app_id and app_key as query parameters. Anything above WARNING keeps those
# credentials out of the console, out of log files and out of screenshots.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("jobfit.ingestion")


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: ingestion")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to the database")
    parser.add_argument("--limit", type=int, default=50, help="Results per query per source")
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Skip Reed detail fetching. Much faster, but descriptions stay as snippets.",
    )
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()

    sources = [
        ReedClient(settings.reed, fetch_details=not args.no_details),
        AdzunaClient(settings.adzuna),
    ]

    result = run_ingestion(
        sources=sources,
        queries=settings.search_queries,
        location=settings.search_location,
        limit_per_query=args.limit,
    )

    full_text = sum(1 for p in result.canonical if p.has_full_description)
    logger.info(
        "Fetched %d, kept %d, dropped %d duplicates. %d of %d carry a full description.",
        result.fetched, result.inserted, result.duplicate_count, full_text, result.inserted,
    )

    if args.dry_run:
        for posting in result.canonical[:10]:
            logger.info(
                "  [%s] %s at %s (%s)",
                posting.source, posting.title, posting.company or "unknown", posting.location or "",
            )
        logger.info("Dry run: nothing written.")
        return 0

    with repository.connect(settings.database_url) as conn:
        repository.apply_schema(conn)
        run_id = repository.start_run(conn, source="combined", query=",".join(settings.search_queries))
        try:
            repository.upsert_postings(conn, result.canonical)
            repository.finish_run(
                conn, run_id, result.fetched, result.inserted, result.duplicate_count
            )
        except Exception as exc:
            repository.finish_run(
                conn, run_id, result.fetched, 0, 0, status="failed", error_message=str(exc)
            )
            raise

    logger.info("Ingestion run %d complete.", run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
