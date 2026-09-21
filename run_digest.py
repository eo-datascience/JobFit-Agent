"""Run Agent 5: the weekly digest.

Usage:
    python run_digest.py --preview          # render to digest_preview.html, send nothing
    python run_digest.py                    # send for real, no approval step
    python run_digest.py --min-score 70     # stricter threshold

Preview first. It writes the exact email to a local file and touches neither
SendGrid nor the record of what has been sent, so it can be run as often as you
like without consuming postings.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

from agents.cv import CV
from agents.digest import (
    DEFAULT_SEEN_PATH,
    RESEND_TEST_SENDER,
    ResendSender,
    SendGridSender,
    compile_digest,
    deliver,
    load_seen,
    render_html,
)
from agents.extraction import extract_many, in_domain_only
from agents.forecasting import today
from agents.ingestion import AdzunaClient, ReedClient, run_ingestion
from agents.outcomes import load_weights
from agents.scoring import score
from config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("jobfit.digest")

PREVIEW_PATH = Path("digest_preview.html")


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: weekly digest")
    parser.add_argument("--cv", default="cv.yml")
    parser.add_argument("--limit", type=int, default=50, help="Postings per query per source")
    parser.add_argument("--min-score", type=int, default=60)
    parser.add_argument("--preview", action="store_true", help="Render locally, send nothing")
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_env()

    cv_path = Path(args.cv)
    if not cv_path.exists():
        logger.error("No CV found at %s. Copy cv.example.yml to cv.yml first.", cv_path)
        return 1
    candidate = CV.from_file(cv_path)

    provider = os.environ.get("EMAIL_PROVIDER", "resend").lower()
    if not args.preview:
        required = {
            "resend": ("RESEND_API_KEY", "DIGEST_TO_EMAIL"),
            "sendgrid": ("SENDGRID_API_KEY", "DIGEST_FROM_EMAIL", "DIGEST_TO_EMAIL"),
        }
        if provider not in required:
            logger.error("Unknown EMAIL_PROVIDER %r. Use resend or sendgrid.", provider)
            return 1
        missing = [k for k in required[provider] if not os.environ.get(k)]
        if missing:
            logger.error("Cannot send, missing from .env: %s", ", ".join(missing))
            logger.error("Run with --preview to see the email without sending it.")
            return 1

    result = run_ingestion(
        sources=[ReedClient(settings.reed), AdzunaClient(settings.adzuna)],
        queries=settings.search_queries,
        location=settings.search_location,
        limit_per_query=args.limit,
    )
    requirements = in_domain_only(extract_many(result.canonical))
    by_id = {p.source_job_id: p for p in result.canonical}
    # Learned weights if the outcome monitor has adopted any, otherwise the originals.
    weights = load_weights()

    scored = []
    for req in requirements:
        posting = by_id.get(req.posting_id)
        if posting is None:
            continue
        scored.append((
            score(candidate, req,
                  salary_min=posting.salary_min, salary_max=posting.salary_max,
                  salary_is_predicted=posting.salary_is_predicted, location=posting.location, weights=weights),
            posting,
        ))

    seen = load_seen(DEFAULT_SEEN_PATH)
    digest = compile_digest(scored, seen, week_of=today(), min_score=args.min_score)

    if args.preview:
        PREVIEW_PATH.write_text(render_html(digest, candidate.name), encoding="utf-8")
        logger.info("Preview written to %s. Nothing was sent or recorded.", PREVIEW_PATH.resolve())
        if not digest.is_empty:
            webbrowser.open(PREVIEW_PATH.resolve().as_uri())
        else:
            logger.info("The digest is empty, so a real run would send nothing either.")
        return 0

    if provider == "sendgrid":
        sender = SendGridSender(os.environ["SENDGRID_API_KEY"], os.environ["DIGEST_FROM_EMAIL"])
    else:
        sender = ResendSender(
            os.environ["RESEND_API_KEY"],
            os.environ.get("DIGEST_FROM_EMAIL") or RESEND_TEST_SENDER,
        )
    try:
        deliver(digest, sender, os.environ["DIGEST_TO_EMAIL"], candidate.name, DEFAULT_SEEN_PATH)
    except RuntimeError as exc:
        logger.error("Send failed, nothing was recorded as sent: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
