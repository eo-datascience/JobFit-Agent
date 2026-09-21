"""Run Agent 6: record outcomes and let them adjust the scoring weights.

Usage:
    python run_outcomes.py list                          # roles the digest sent you
    python run_outcomes.py record reed:57364886 applied  # you applied
    python run_outcomes.py record reed:57364886 interview
    python run_outcomes.py learn                         # show what would change
    python run_outcomes.py learn --apply                 # adopt it
    python run_outcomes.py revert                        # undo the last adjustment

Outcomes: applied, rejected, response, interview, offer.
An application left at "applied" becomes a non response on its own once three
weeks pass, so you only need to record the ones that go somewhere.
"""

from __future__ import annotations

import argparse
import logging
import sys

from agents.forecasting import today
from agents.outcomes import (
    RESPONSE_WINDOW_DAYS,
    Outcome,
    apply_proposal,
    load_outcomes,
    load_recommendations,
    propose_weights,
    record_outcome,
    resolve,
    revert,
)
from agents.scoring import WEIGHTS

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("jobfit.outcomes")

RECORDABLE = [o.value for o in Outcome if o is not Outcome.NO_RESPONSE]


def cmd_list(_: argparse.Namespace) -> int:
    recs = load_recommendations()
    outcomes = load_outcomes()
    if not recs:
        logger.info("No recommendations yet. They are recorded each time the digest sends.")
        return 0

    now = today()
    logger.info("%-22s %-5s %-14s %s", "KEY", "SCORE", "STATUS", "ROLE")
    for key, rec in sorted(recs.items(), key=lambda kv: kv[1].recommended_on, reverse=True):
        record = outcomes.get(key)
        if record is None:
            status = "not applied"
        else:
            resolved = resolve(record, now)
            status = resolved.value if resolved else "pending"
        marker = "*" if rec.provisional else " "
        logger.info("%-22s %4d%s %-14s %s, %s", key, rec.total, marker, status,
                    rec.title, rec.company or "")
    if any(rec.provisional for rec in recs.values()):
        logger.info("\n* provisional, scored without skills. Not used to learn skill weights.")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    try:
        record = record_outcome(args.key, Outcome(args.outcome), today())
    except KeyError as exc:
        logger.error(str(exc).strip("'\""))
        logger.error("Run `python run_outcomes.py list` to see the keys you can record.")
        return 1
    logger.info("Recorded %s as %s.", record.key, record.outcome.value)
    if record.outcome is Outcome.APPLIED:
        logger.info("If you hear nothing within %d days it will count as no response "
                    "automatically.", RESPONSE_WINDOW_DAYS)
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    proposal = propose_weights(today())
    logger.info(proposal.reason)

    if not proposal.ready:
        logger.info("\nCurrent weights stay as they are:")
        for k, v in proposal.current.items():
            logger.info("    %-10s %.3f", k, v)
        return 0

    logger.info("\nWhat each component told us:")
    for e in proposal.evidence:
        r = "undefined" if e.correlation is None else f"{e.correlation:+.2f}"
        logger.info("    %-10s correlation %-9s %s", e.component, r, e.note)

    logger.info("\n    %-10s %9s %9s %9s", "component", "original", "current", "proposed")
    for k in WEIGHTS:
        logger.info("    %-10s %9.3f %9.3f %9.3f", k, WEIGHTS[k], proposal.current[k], proposal.proposed[k])

    if args.apply:
        apply_proposal(proposal, today())
        logger.info("\nAdopted. Scoring and the digest will use these weights from now on.")
        logger.info("Run `python run_outcomes.py revert` to undo.")
    else:
        logger.info("\nNothing changed. Run with --apply to adopt these weights.")
    return 0


def cmd_revert(_: argparse.Namespace) -> int:
    try:
        restored = revert()
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    logger.info("Reverted. Weights are now:")
    for k, v in restored.items():
        logger.info("    %-10s %.3f", k, v)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="JobFit Agent: outcome monitoring")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show roles the digest has sent you").set_defaults(func=cmd_list)

    rec = sub.add_parser("record", help="Record what happened with a role")
    rec.add_argument("key", help="The key shown by `list`, for example reed:57364886")
    rec.add_argument("outcome", choices=RECORDABLE)
    rec.set_defaults(func=cmd_record)

    learn = sub.add_parser("learn", help="Show, and optionally adopt, learned weights")
    learn.add_argument("--apply", action="store_true")
    learn.set_defaults(func=cmd_learn)

    sub.add_parser("revert", help="Undo the most recent adjustment").set_defaults(func=cmd_revert)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
