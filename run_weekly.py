"""The scheduled weekly job.

One run does everything the system needs each week, fetching postings once and
feeding every step from that single fetch.

    1. Ingest and extract postings.
    2. Record a skill snapshot, so real forecasting history accumulates.
    3. Export the public dashboard data, scored against sample profiles
       rather than the real CV.
    4. Score every in domain posting against the CV, using learned weights
       where the outcome monitor has earned them.
    5. Send the digest.

Running the forecast and digest scripts separately would fetch every posting
twice, roughly four hundred extra Reed requests a week for nothing. Combining
them also means the snapshot and the digest describe exactly the same market.

Usage:
    python run_weekly.py              # the full job, as the scheduler runs it
    python run_weekly.py --preview    # everything except sending and recording
    python run_weekly.py --export-only   # refresh the public dashboard data only

A failed send exits non zero, so the scheduler marks the run as failed and
emails the repository owner, rather than reporting success on a week where no
digest arrived.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from agents.cv import CV
from agents.digest import (
    RESEND_TEST_SENDER,
    ResendSender,
    SendGridSender,
    compile_digest,
    deliver,
    load_seen,
    render_html,
)
from agents.export import Profile, build_dashboard
from agents.extraction import extract_many, in_domain_only
from agents.forecasting import today
from agents.ingestion import AdzunaClient, ReedClient, run_ingestion
from agents.outcomes import load_weights
from agents.scoring import score
from config import Settings
from db import history
from paths import CV_PATH, HISTORY_PATH, SEEN_PATH, STATE_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
for noisy in ("httpx", "httpcore", "cmdstanpy", "prophet"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("jobfit.weekly")

# Written into the public code repository, never the private state directory.
# The scheduled job commits it, and Netlify rebuilds the site from it.
DASHBOARD_PATH = Path("frontend/public/data/dashboard.json")
PROFILES_DIR = Path("profiles")


def _sender():
    provider = os.environ.get("EMAIL_PROVIDER", "resend").lower()
    if provider == "sendgrid":
        return SendGridSender(os.environ["SENDGRID_API_KEY"], os.environ["DIGEST_FROM_EMAIL"])
    return ResendSender(
        os.environ["RESEND_API_KEY"],
        os.environ.get("DIGEST_FROM_EMAIL") or RESEND_TEST_SENDER,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: the weekly job")
    parser.add_argument("--preview", action="store_true",
                        help="Run everything but send nothing and record nothing")
    parser.add_argument("--export-only", action="store_true",
                        help="Refresh the public dashboard data and nothing else")
    parser.add_argument("--limit", type=int, default=50, help="Postings per query per source")
    parser.add_argument("--min-score", type=int, default=60)
    args = parser.parse_args()

    logger.info("State directory: %s", STATE_DIR.resolve())

    if not args.export_only and not CV_PATH.exists():
        logger.error("No CV at %s. It belongs in the state directory.", CV_PATH)
        return 1

    if not args.preview and not args.export_only:
        provider = os.environ.get("EMAIL_PROVIDER", "resend").lower()
        needed = ["DIGEST_TO_EMAIL",
                  "SENDGRID_API_KEY" if provider == "sendgrid" else "RESEND_API_KEY"]
        missing = [k for k in needed if not os.environ.get(k)]
        if missing:
            logger.error("Cannot send, missing: %s", ", ".join(missing))
            return 1

    settings = Settings.from_env()

    # 1. Ingest once.
    result = run_ingestion(
        sources=[ReedClient(settings.reed), AdzunaClient(settings.adzuna)],
        queries=settings.search_queries,
        location=settings.search_location,
        limit_per_query=args.limit,
    )
    extracted = extract_many(result.canonical)
    requirements = in_domain_only(extracted)
    if not requirements:
        # Both providers failing would otherwise produce an empty digest, which
        # is silently not sent, and a green run on a week with no email.
        logger.error("No postings were ingested. The job boards may be unavailable.")
        return 1

    # 2. Record a snapshot so recorded history replaces reconstruction over time.
    if not args.preview and not args.export_only:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        history.append(history.summarise(requirements, run_date=today()), HISTORY_PATH)
        logger.info("Recorded this week's skill snapshot.")

    # 3. Export the public dashboard. Before the send, so a failed email still
    #    refreshes the site: the market data does not depend on it.
    stored = history.load(HISTORY_PATH) if HISTORY_PATH.exists() else []
    dashboard = build_dashboard(
        fetched=result.fetched,
        duplicates=result.duplicate_count,
        canonical=result.canonical,
        requirements=extracted,
        profiles=Profile.load_all(PROFILES_DIR),
        skill_series=history.as_series(stored) if stored else {},
        week_of=today(),
    )
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.write_text(json.dumps(dashboard, indent=1), encoding="utf-8")
    logger.info("Public dashboard written with %d roles.", len(dashboard["roles"]))

    if args.export_only:
        return 0

    # 4. Score with any weights the outcome monitor has earned.
    candidate = CV.from_file(CV_PATH)
    weights = load_weights()
    by_id = {p.source_job_id: p for p in result.canonical}
    scored = [
        (score(candidate, req,
               salary_min=p.salary_min, salary_max=p.salary_max,
               salary_is_predicted=p.salary_is_predicted, location=p.location,
               weights=weights), p)
        for req in requirements
        if (p := by_id.get(req.posting_id)) is not None
    ]

    # 5. Compile and send.
    digest = compile_digest(scored, load_seen(SEEN_PATH), week_of=today(),
                            min_score=args.min_score)

    if args.preview:
        out = Path("digest_preview.html")
        out.write_text(render_html(digest, candidate.name), encoding="utf-8")
        logger.info("Preview written to %s. Nothing was sent or recorded.", out.resolve())
        return 0

    try:
        deliver(digest, _sender(), os.environ["DIGEST_TO_EMAIL"], candidate.name, SEEN_PATH)
    except RuntimeError as exc:
        logger.error("Send failed, nothing was recorded as sent: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
