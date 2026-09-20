"""Run Agent 2 over freshly ingested postings.

Usage:
    python run_extraction.py                 # deterministic only, no API cost
    python run_extraction.py --use-model     # also call Claude on full postings
    python run_extraction.py --limit 20
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from agents.extraction import Confidence, Relevance, extract_many, in_domain_only
from agents.ingestion import AdzunaClient, ReedClient, run_ingestion
from config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("jobfit.extraction")


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: extraction")
    parser.add_argument("--limit", type=int, default=25, help="Postings per query per source")
    parser.add_argument(
        "--inspect",
        metavar="POSTING_ID",
        help="Print the cleaned text and detected sections for one posting, then exit.",
    )
    parser.add_argument(
        "--use-model",
        action="store_true",
        help="Call Claude for seniority and essential markers. Costs API credit.",
    )
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()

    llm = None
    if args.use_model:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY is not set. Run without --use-model, or add the key.")
            return 1
        from agents.extraction import AnthropicClient
        llm = AnthropicClient()

    result = run_ingestion(
        sources=[ReedClient(settings.reed), AdzunaClient(settings.adzuna)],
        queries=settings.search_queries[:1],
        location=settings.search_location,
        limit_per_query=args.limit,
    )

    if args.inspect:
        from agents.extraction import find_skills, split_into_sections

        match = next((p for p in result.canonical if p.source_job_id == args.inspect), None)
        if match is None:
            logger.error("Posting %s not in this batch. Try one from the sample below.", args.inspect)
            return 1
        logger.info("Title: %s", match.title)
        logger.info("Full description available: %s", match.has_full_description)
        logger.info("Description length: %d characters", len(match.description))
        logger.info("")
        logger.info("Detected sections:")
        for status, body in split_into_sections(match.description):
            logger.info("  [%s] %s", status or "no heading", body[:120].replace("\n", " | "))
        logger.info("")
        logger.info("Skills found: %s", ", ".join(s.name for s in find_skills(match.description)) or "none")
        logger.info("")
        logger.info("First 800 characters of cleaned text:")
        logger.info("%s", match.description[:800])
        return 0

    requirements = extract_many(result.canonical, llm=llm)

    excluded = [r for r in requirements if r.relevance is Relevance.OUT_OF_DOMAIN]
    if excluded:
        logger.info("")
        logger.info("Excluded as out of domain:")
        for req in excluded[:8]:
            logger.info("    %s (%s)", req.posting_id, req.relevance_reason)

    scored = in_domain_only(requirements)
    full = [r for r in scored if r.confidence is Confidence.FULL]
    logger.info("")
    logger.info("Sample of full confidence extractions:")
    for req in full[:5]:
        logger.info("")
        logger.info("  Posting %s (%s)", req.posting_id, req.source)
        logger.info("    Seniority:  %s", req.seniority or "not stated")
        logger.info("    Experience: %s", f"{req.years_experience} years" if req.years_experience else "not stated")
        logger.info("    Essential:  %s", ", ".join(req.essential_skills) or "none flagged")
        logger.info("    All skills: %s", ", ".join(req.skill_names) or "none found")

    counts: dict[str, int] = {}
    for req in scored:
        for name in req.skill_names:
            counts[name] = counts.get(name, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15]

    logger.info("")
    logger.info("Most demanded skills across %d in domain postings:", len(scored))
    for name, count in top:
        logger.info("    %-20s %d", name, count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
