"""Export the public dashboard data.

This module is the boundary between the private system and the public website,
so its most important property is what it cannot see.

The export never receives the candidate's CV, their outcomes, their
recommendations or the record of what was sent. It takes only the postings the
job boards published, what the extraction agent found in them, a set of public
sample profiles, and aggregate skill history. Privacy is therefore enforced by
the function's inputs rather than by remembering to leave fields out.

Job descriptions are not exported either. Titles, companies, salaries and links
are the listing itself; republishing full descriptions would go beyond linking
back to the source.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from agents.cv import CV
from agents.digest import _listing_identity, compile_digest
from agents.domains import DOMAINS, PRIMARY_DOMAIN
from agents.extraction import Confidence, Relevance, Requirements
from agents.forecasting import MIN_WEEKS_FOR_FORECAST, Trend, build_report_from_series
from agents.ingestion import Posting
from agents.scoring import (
    CATEGORY_MATCH_CREDIT,
    ESSENTIAL_MULTIPLIER,
    REMOTE_MARKERS,
    SENIORITY_ORDER,
    WEIGHTS,
    FitScore,
    score,
)
from agents.skills_taxonomy import SKILL_CATEGORIES, alias_to_canonical

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Excluded postings shown on the pipeline page. Enough to show the relevance
# gate at work without turning the page into a list of rejected jobs.
MAX_EXCLUDED_SHOWN = 25

# Skills shown on the demand page.
MAX_SKILLS = 30

# Score a role must reach to count toward a profile's shortlist, matching the
# threshold the real digest uses.
SHORTLIST_THRESHOLD = 60

# A skill needs this many fully described postings before its essential rate is
# published. Below it, one posting would swing the rate by tens of percent.
MIN_POSTINGS_FOR_RATE = 5

# Score explanations are written for a candidate reading their own digest. On a
# public page, "your level" would read as addressing the visitor.
_PUBLIC_WORDING = (
    ("no salary floor set",
     "the profile sets no salary floor, so pay is rewarded without a threshold"),
    ("your floor", "the profile's salary floor"),
    ("your level", "the profile's level"),
    ("your ", "the profile's "),
)


def _public(detail: str) -> str:
    for private, public in _PUBLIC_WORDING:
        detail = detail.replace(private, public)
    return detail


@dataclass
class Profile:
    """A public sample profile, identified by its file name."""

    id: str
    cv: CV
    # Which field this profile belongs to, so the site can pair a visitor's
    # chosen field with a profile that makes sense in it.
    domain: str = PRIMARY_DOMAIN

    @classmethod
    def load_all(cls, directory: Path) -> list[Profile]:
        import yaml

        profiles = []
        for path in sorted(directory.glob("*.yml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            domain = str(raw.get("domain", PRIMARY_DOMAIN))
            if domain not in DOMAINS:
                domain = PRIMARY_DOMAIN
            profiles.append(cls(id=path.stem, cv=CV.from_file(path), domain=domain))
        return profiles


def _slug(posting: Posting) -> str:
    return f"{posting.source}-{posting.source_job_id}"


def _score_payload(fit: FitScore) -> dict[str, Any]:
    return {
        "total": fit.total,
        "provisional": fit.is_provisional,
        "components": [
            {"name": c.name, "score": round(c.score, 3),
             "weight": round(c.weight, 3), "detail": _public(c.detail)}
            for c in fit.components
        ],
        "matched": list(fit.matched_skills),
        "partial": list(fit.partial_skills),
        "missing_essential": list(fit.missing_essential),
    }


def _role_payload(posting: Posting, req: Requirements,
                  profiles: list[Profile]) -> dict[str, Any]:
    scores = {}
    for profile in profiles:
        fit = score(profile.cv, req,
                    salary_min=posting.salary_min, salary_max=posting.salary_max,
                    salary_is_predicted=posting.salary_is_predicted,
                    location=posting.location)
        scores[profile.id] = _score_payload(fit)

    return {
        "id": _slug(posting),
        "source": posting.source,
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "salary_is_predicted": posting.salary_is_predicted,
        "url": posting.url,
        "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
        "confidence": req.confidence.value,
        "seniority": req.seniority,
        "years_experience": req.years_experience,
        "skills": [{"name": s.name, "essential": s.is_essential} for s in req.skills],
        "scores": scores,
    }


def _skill_demand(in_domain: list[Requirements]) -> list[dict[str, Any]]:
    """Share of fully described postings mentioning each skill.

    Only fully described postings count, for the same reason as in the
    forecaster: an excerpt cannot show every skill a role asks for, so letting
    excerpts in would dilute every share.
    """
    full = [r for r in in_domain if r.confidence is Confidence.FULL]
    if not full:
        return []
    counts = Counter(name for r in full for name in set(r.skill_names))
    essential = Counter(name for r in full for name in set(r.essential_skills))
    return [
        {"skill": skill, "postings": n, "share": round(n / len(full) * 100, 1),
         "essential_share": (round(essential[skill] / n * 100, 1)
                             if n >= MIN_POSTINGS_FOR_RATE else None)}
        for skill, n in counts.most_common(MAX_SKILLS)
    ]


def _scoring_rules() -> dict[str, Any]:
    """The scoring rules themselves, published so the browser can apply them.

    Visitors score their own CV in their browser, which means the arithmetic
    exists twice: once in Python for the weekly agent and once in TypeScript
    for the site. Two hand written copies drift apart. Publishing the taxonomy,
    the categories and the weights means only the arithmetic is reimplemented,
    and a test asserts these values still match the ones the agent uses.
    """
    return {
        "weights": dict(WEIGHTS),
        "essential_multiplier": ESSENTIAL_MULTIPLIER,
        "category_match_credit": CATEGORY_MATCH_CREDIT,
        "seniority_order": list(SENIORITY_ORDER),
        "remote_markers": list(REMOTE_MARKERS),
        "aliases": alias_to_canonical(),
        "categories": {skill: category
                       for category, members in SKILL_CATEGORIES.items()
                       for skill in members},
    }


def _skill_pairs(in_domain: list[Requirements], top: list[str],
                 limit: int = 12) -> list[dict[str, Any]]:
    """Skills most often asked for in the same fully described posting."""
    wanted = set(top)
    together: Counter[tuple[str, str]] = Counter()
    for req in in_domain:
        if req.confidence is not Confidence.FULL:
            continue
        names = sorted(set(req.skill_names) & wanted)
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                together[(left, right)] += 1
    return [{"a": a, "b": b, "postings": n} for (a, b), n in together.most_common(limit)]


def _skill_trends(series: dict[str, dict[date, int]]) -> dict[str, Any]:
    """Trends from recorded weekly history only, never reconstructed history.

    A public page should not show the less reliable reconstruction. Until
    enough real weeks exist, it says so rather than showing a guess.
    """
    weeks = len({week for per_skill in series.values() for week in per_skill})
    if not series:
        return {"weeks_recorded": 0, "trends": []}
    report = build_report_from_series(series)
    trends = [
        {"skill": s.skill, "trend": s.trend.value,
         "change_pct": s.change_pct, "current": s.current_weekly_rate}
        for s in report.skills
        if s.trend in (Trend.RISING, Trend.FALLING, Trend.STABLE)
    ]
    return {"weeks_recorded": weeks, "trends": trends}


def _collapse_repeats(in_domain: list[Requirements],
                      by_id: dict[str, Posting]) -> list[tuple[Posting, Requirements, list[str]]]:
    """One entry per employer and role, with the other locations attached.

    The browsable list behaves like the digest. One employer's identical role,
    listed separately in several places, appears once rather than filling the
    top of the page with copies. The other locations are kept, not discarded.
    """
    kept: dict[str, tuple[Posting, Requirements, list[str]]] = {}
    for req in in_domain:
        posting = by_id.get(req.posting_id)
        if posting is None:
            continue
        identity = _listing_identity(posting)
        if identity in kept:
            first, _, others = kept[identity]
            if posting.location and posting.location != first.location \
                    and posting.location not in others:
                others.append(posting.location)
            continue
        kept[identity] = (posting, req, [])
    return list(kept.values())


def _profile_shortlist(profile: Profile, in_domain: list[Requirements],
                       by_id: dict[str, Posting], week_of: date) -> dict[str, Any]:
    """What this profile's own digest would contain, against nothing sent before.

    Run through the real digest selection, so the funnel ends at a shortlist of
    exactly the size and shape the system would email.
    """
    scored = []
    for req in in_domain:
        posting = by_id.get(req.posting_id)
        if posting is None:
            continue
        fit = score(profile.cv, req, salary_min=posting.salary_min,
                    salary_max=posting.salary_max,
                    salary_is_predicted=posting.salary_is_predicted,
                    location=posting.location)
        scored.append((fit, posting))

    above = sum(1 for fit, _ in scored if fit.total >= SHORTLIST_THRESHOLD)
    digest = compile_digest(scored, seen=set(), week_of=week_of,
                            min_score=SHORTLIST_THRESHOLD)
    return {
        "above_threshold": above,
        "shortlist": [_slug(e.posting) for e in digest.entries + digest.provisional],
        "repeat_listings": digest.skipped_repeat_listing,
    }


def build_dashboard(
    fetched: int,
    duplicates: int,
    canonical: list[Posting],
    requirements: list[Requirements],
    profiles: list[Profile],
    skill_series: dict[str, dict[date, int]],
    week_of: date,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the public dashboard from public inputs only."""
    by_id = {p.source_job_id: p for p in canonical}
    in_domain = [r for r in requirements if r.relevance is Relevance.IN_DOMAIN]
    excluded = [r for r in requirements if r.relevance is Relevance.OUT_OF_DOMAIN]

    roles = []
    for posting, req, others in _collapse_repeats(in_domain, by_id):
        role = _role_payload(posting, req, profiles)
        role["also_listed_in"] = others
        role["domain"] = req.domain or PRIMARY_DOMAIN
        # The key the outcome monitor expects, which differs from the id used
        # in site URLs. Published rather than reconstructed in the browser, so
        # the two formats cannot drift apart.
        role["outcome_key"] = f"{posting.source}:{posting.source_job_id}"
        roles.append(role)

    by_source = Counter(p.source for p in canonical)
    full_count = sum(1 for r in requirements if r.confidence is Confidence.FULL)

    salaries = sorted(p.salary_min for p in canonical
                      if p.salary_min and not p.salary_is_predicted
                      and any(r.posting_id == p.source_job_id for r in in_domain))

    demand = _skill_demand(in_domain)
    top_skills = [d["skill"] for d in demand[:15]]
    # The denominator the shares above are calculated over. The roles list
    # collapses repeat listings, so counting that instead would leave the page
    # claiming a skill appeared in more postings than exist.
    described = sum(1 for r in in_domain if r.confidence is Confidence.FULL)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "week_of": week_of.isoformat(),
        "pipeline": {
            "fetched": fetched,
            "duplicates": duplicates,
            "canonical": len(canonical),
            "by_source": dict(by_source),
            "full_confidence": full_count,
            "partial_confidence": len(requirements) - full_count,
            "in_domain": len(in_domain),
            "out_of_domain": len(excluded),
            "excluded": [
                {"title": by_id[r.posting_id].title,
                 "company": by_id[r.posting_id].company,
                 "reason": r.relevance_reason}
                for r in excluded[:MAX_EXCLUDED_SHOWN] if r.posting_id in by_id
            ],
            "salary": {
                "stated_count": len(salaries),
                "median_minimum": salaries[len(salaries) // 2] if salaries else None,
            },
            "shortlist_threshold": SHORTLIST_THRESHOLD,
        },
        "domains": [
            {"id": d.id, "label": d.label, "blurb": d.blurb,
             "primary": d.id == PRIMARY_DOMAIN,
             "roles": sum(1 for r in in_domain if (r.domain or PRIMARY_DOMAIN) == d.id)}
            for d in DOMAINS.values()
        ],
        "profiles": [
            {"id": p.id, "name": p.cv.name, "domain": p.domain, "seniority": p.cv.seniority,
             "years_experience": p.cv.years_experience,
             "skills": sorted(p.cv.skills), "summary": p.cv.summary,
             **_profile_shortlist(p, in_domain, by_id, week_of)}
            for p in profiles
        ],
        "roles": roles,
        "scoring": _scoring_rules(),
        "skills": {
            "described": described,
            "demand": demand,
            "pairs": _skill_pairs(in_domain, top_skills),
            "weeks_needed": MIN_WEEKS_FOR_FORECAST,
            **_skill_trends(skill_series),
        },
    }
