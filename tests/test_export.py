"""Tests for the public dashboard export.

The privacy tests matter most. This data is published on a public website every
week, with nobody reviewing each release.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from agents.export import MIN_POSTINGS_FOR_RATE, Profile, build_dashboard
from agents.extraction import extract
from agents.ingestion import Posting

WEEK = date(2026, 9, 21)
PROFILES = Profile.load_all(Path("profiles"))

MARKER = "UNIQUE-DESCRIPTION-MARKER-7f3a"

DATA_ROLE = f"""Senior Data Engineer at Acme.

Essential:
Strong Python and SQL. Experience with Airflow.

Desirable:
Docker and Kubernetes.

{MARKER} Internal notes the employer published about the team.
""" + ("Further detail. " * 40)


def _posting(job_id: str, title: str, description: str, full: bool = True, **kw) -> Posting:
    base = {"source": "reed", "source_job_id": job_id, "title": title,
            "description": description, "has_full_description": full,
            "company": "Acme Ltd", "location": "London",
            "salary_min": 50000, "salary_max": 60000,
            "url": f"https://www.reed.co.uk/jobs/{job_id}"}
    base.update(kw)
    return Posting(**base)


def _build(postings: list[Posting], series=None) -> dict:
    requirements = [extract(p) for p in postings]
    return build_dashboard(
        fetched=len(postings) + 2, duplicates=2, canonical=postings,
        requirements=requirements, profiles=PROFILES,
        skill_series=series or {}, week_of=WEEK,
        generated_at=datetime(2026, 9, 21, 7, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def test_job_descriptions_are_never_published():
    """Titles and links are the listing. Full descriptions stay with the source."""
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE)])
    assert MARKER not in json.dumps(dashboard)


def _every_key(node) -> set[str]:
    """Every key name anywhere in the snapshot."""
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _every_key(v)}
    if isinstance(node, list):
        return {k for v in node for k in _every_key(v)}
    return set()


def test_no_private_fields_appear_anywhere():
    """Checked against key names rather than raw text.

    A substring scan looked stricter but was wrong in both directions: it
    matched the word "interview" inside the skill alias "customer interviews",
    while still missing a private value stored under an innocent key.
    """
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE)])
    keys = {k.lower() for k in _every_key(dashboard)}

    for forbidden in ("minimum_salary", "outcome", "outcomes", "recommendation",
                      "recommendations", "sent_postings", "description",
                      "digest_to_email", "applied", "interview", "cv", "cv_path"):
        assert forbidden not in keys, forbidden

    # The values that would matter most, checked directly.
    published = json.dumps(dashboard).lower()
    assert "@" not in published.replace("\\u0040", "")  # no email address anywhere
    assert MARKER.lower() not in published


def test_the_export_cannot_be_given_a_real_cv():
    """Privacy by construction: the function has no parameter a CV could
    arrive through, so no future change to its body can leak one."""
    import inspect

    params = set(inspect.signature(build_dashboard).parameters)
    assert not params & {"cv", "candidate", "outcomes", "recommendations", "seen"}


def test_sample_profiles_carry_no_salary_floor():
    assert all(p.cv.minimum_salary is None for p in PROFILES)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_every_role_is_scored_against_every_profile():
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE)])
    role = dashboard["roles"][0]

    assert set(role["scores"]) == {p.id for p in PROFILES}
    for payload in role["scores"].values():
        assert 0 <= payload["total"] <= 100
        assert {c["name"] for c in payload["components"]} >= {"skills", "seniority"}


def test_the_same_role_scores_differently_for_different_profiles():
    """The whole point of offering more than one profile."""
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE)])
    totals = {pid: s["total"] for pid, s in dashboard["roles"][0]["scores"].items()}

    assert totals["junior-data-engineer"] > totals["junior-data-analyst"]


def test_out_of_domain_postings_go_to_the_pipeline_not_the_roles():
    dashboard = _build([
        _posting("1", "Data Engineer", DATA_ROLE),
        _posting("2", "AI Creative Director", "Adobe Firefly across campaigns. " * 30),
    ])

    assert [r["title"] for r in dashboard["roles"]] == ["Data Engineer"]
    assert dashboard["pipeline"]["out_of_domain"] == 1
    assert dashboard["pipeline"]["excluded"][0]["title"] == "AI Creative Director"
    assert "creative director" in dashboard["pipeline"]["excluded"][0]["reason"]


def test_essential_skills_are_marked():
    skills = {s["name"]: s["essential"] for s in
              _build([_posting("1", "Data Engineer", DATA_ROLE)])["roles"][0]["skills"]}

    assert skills["Python"] is True
    assert skills["Kubernetes"] is False


def test_skill_demand_counts_fully_described_postings_only():
    """An excerpt cannot show every skill a role asks for, so it would dilute
    every share if it were counted."""
    dashboard = _build([
        _posting("1", "Data Engineer", DATA_ROLE),
        _posting("2", "Data Analyst", "Excel only.", full=False, source="adzuna"),
    ])
    demand = {d["skill"]: d for d in dashboard["skills"]["demand"]}

    assert demand["Python"]["share"] == 100.0
    assert "Excel" not in demand


def test_no_recorded_history_publishes_no_trends():
    """The public page never shows reconstructed history, only recorded weeks."""
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE)])
    assert dashboard["skills"]["weeks_recorded"] == 0
    assert dashboard["skills"]["trends"] == []


def test_pipeline_counts_are_consistent():
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE),
                        _posting("2", "Data Analyst", DATA_ROLE)])
    p = dashboard["pipeline"]

    assert p["canonical"] == p["in_domain"] + p["out_of_domain"]
    assert p["canonical"] == p["full_confidence"] + p["partial_confidence"]
    assert p["fetched"] == p["canonical"] + p["duplicates"]


def test_the_output_is_json_serialisable():
    json.dumps(_build([_posting("1", "Data Engineer", DATA_ROLE)]))


# ---------------------------------------------------------------------------
# Additions for the public site
# ---------------------------------------------------------------------------


def test_private_state_is_never_read(monkeypatch):
    """Sent roles, recommendations, outcomes and weights describe where the
    owner applied. Reading any of them during export fails this test."""

    def refuse(*_a, **_k):
        raise AssertionError("The export must not read private state")

    for target in ("agents.digest.load_seen", "agents.outcomes.load_recommendations",
                   "agents.outcomes.load_outcomes", "agents.outcomes.load_weights"):
        monkeypatch.setattr(target, refuse)

    _build([_posting("1", "Data Engineer", DATA_ROLE)])


def test_explanations_describe_the_profile_rather_than_the_reader():
    """Written for the owner's own digest, 'your level' would address the
    visitor on a public page."""
    published = json.dumps(_build([_posting("1", "Data Engineer", DATA_ROLE)])["roles"])
    assert "your " not in published.lower()


def test_a_repeat_listing_appears_once_with_its_other_locations():
    """Like the digest, the browsable list must not fill its top rows with one
    employer's identical role listed in several places."""
    postings = [_posting(str(i), "Data Engineer", DATA_ROLE, location=loc)
                for i, loc in enumerate(["London E15", "London W5", "London SW3"])]
    roles = _build(postings)["roles"]

    assert len(roles) == 1
    assert roles[0]["also_listed_in"] == ["London W5", "London SW3"]


def test_each_profile_gets_its_own_shortlist_through_the_real_digest():
    postings = [_posting(str(i), "Data Engineer", DATA_ROLE, company=f"Employer {i}")
                for i in range(3)]
    profiles = _build(postings)["profiles"]

    for profile in profiles:
        assert len(profile["shortlist"]) <= profile["above_threshold"]
        assert set(profile["shortlist"]) <= {f"reed-{i}" for i in range(3)}


def test_the_funnel_only_ever_narrows_for_every_profile():
    postings = [_posting(str(i), "Data Engineer", DATA_ROLE, company=f"Employer {i}")
                for i in range(4)]
    postings.append(_posting("99", "Marketing Manager", DATA_ROLE))
    dashboard = _build(postings)
    p = dashboard["pipeline"]

    for profile in dashboard["profiles"]:
        stages = [p["fetched"], p["canonical"], p["in_domain"],
                  profile["above_threshold"], len(profile["shortlist"])]
        assert stages == sorted(stages, reverse=True)


def test_essential_rate_is_withheld_below_the_minimum():
    """With three postings a rate of 67 percent is one posting's worth."""
    few = _build([_posting(str(i), "Data Engineer", DATA_ROLE, company=f"E{i}")
                  for i in range(MIN_POSTINGS_FOR_RATE - 1)])
    enough = _build([_posting(str(i), "Data Engineer", DATA_ROLE, company=f"E{i}")
                     for i in range(MIN_POSTINGS_FOR_RATE)])

    rate = lambda d: next(x for x in d["skills"]["demand"] if x["skill"] == "Python")["essential_share"]

    assert rate(few) is None
    assert rate(enough) == 100.0


def test_skills_asked_for_together_are_published():
    postings = [_posting(str(i), "Data Engineer", DATA_ROLE, company=f"E{i}") for i in range(3)]
    pairs = {(x["a"], x["b"]) for x in _build(postings)["skills"]["pairs"]}

    assert ("Python", "SQL") in pairs


def test_estimated_salaries_are_left_out_of_the_median():
    postings = [
        _posting("1", "Data Engineer", DATA_ROLE, company="E1", salary_min=40000),
        _posting("2", "Data Engineer", DATA_ROLE, company="E2", salary_min=90000,
                 salary_is_predicted=True),
    ]
    salary = _build(postings)["pipeline"]["salary"]

    assert salary["stated_count"] == 1
    assert salary["median_minimum"] == 40000


def test_the_published_share_denominator_matches_the_shares():
    """The roles list collapses repeat listings, so counting it would leave the
    page claiming a skill appeared in more postings than exist."""
    postings = [_posting(str(i), "Data Engineer", DATA_ROLE, company=f"E{i}") for i in range(4)]
    postings += [_posting("9", "Data Engineer", DATA_ROLE, company="E0", location="Leeds")]
    dashboard = _build(postings)

    described = dashboard["skills"]["described"]
    python = next(d for d in dashboard["skills"]["demand"] if d["skill"] == "Python")

    assert python["postings"] <= described
    assert round(python["postings"] / described * 100, 1) == python["share"]
    assert described > len(dashboard["roles"])


def test_a_profile_without_a_salary_floor_is_explained_not_flagged():
    detail = " ".join(
        c["detail"]
        for role in _build([_posting("1", "Data Engineer", DATA_ROLE)])["roles"]
        for fit in role["scores"].values()
        for c in fit["components"] if c["name"] == "salary"
    )
    assert "no salary floor set" not in detail.lower()
    assert "without a threshold" in detail


# ---------------------------------------------------------------------------
# Rules published for in browser scoring
# ---------------------------------------------------------------------------


def test_published_rules_match_the_ones_the_agent_uses():
    """The site scores a visitor's CV in their browser using these values. If
    the agent's rules change and these do not, the two quietly disagree."""
    from agents.scoring import (
        CATEGORY_MATCH_CREDIT,
        ESSENTIAL_MULTIPLIER,
        REMOTE_MARKERS,
        SENIORITY_ORDER,
        WEIGHTS,
    )

    rules = _build([_posting("1", "Data Engineer", DATA_ROLE)])["scoring"]

    assert rules["weights"] == WEIGHTS
    assert rules["essential_multiplier"] == ESSENTIAL_MULTIPLIER
    assert rules["category_match_credit"] == CATEGORY_MATCH_CREDIT
    assert rules["seniority_order"] == list(SENIORITY_ORDER)
    assert rules["remote_markers"] == list(REMOTE_MARKERS)


def test_published_aliases_cover_the_whole_taxonomy():
    from agents.skills_taxonomy import alias_to_canonical, canonical_skills

    rules = _build([_posting("1", "Data Engineer", DATA_ROLE)])["scoring"]

    assert rules["aliases"] == alias_to_canonical()
    assert set(rules["aliases"].values()) <= set(canonical_skills())
    # The guard from the R and Go bug: the ambiguous bare forms are absent, so
    # "R&D" cannot be read as the R language and "go live" is not Golang.
    assert "r" not in rules["aliases"]
    assert "go" not in rules["aliases"]
    assert rules["aliases"]["r programming"] == "R"


def test_published_categories_allow_related_experience_credit():
    rules = _build([_posting("1", "Data Engineer", DATA_ROLE)])["scoring"]
    categories = rules["categories"]

    assert categories["PostgreSQL"] == categories["MySQL"]
    assert categories.get("Airflow") == categories.get("Prefect")


# ---------------------------------------------------------------------------
# Several fields on one site
# ---------------------------------------------------------------------------

PRODUCT_ROLE = """We are hiring a Product Owner.

Essential:
Roadmapping, User Stories and Backlog Management. Strong Stakeholder Management.

Desirable:
Jira and Discovery.
""" + ("Further detail about the team. " * 20)

SOFTWARE_ROLE = """We are hiring a Backend Engineer.

Essential:
Strong TypeScript and Node.js. Experience with REST APIs and Docker.

Desirable:
React and Kubernetes.
""" + ("Further detail about the team. " * 20)


def test_roles_carry_the_field_they_belong_to():
    dashboard = _build([
        _posting("1", "Data Engineer", DATA_ROLE, company="A"),
        _posting("2", "Backend Engineer", SOFTWARE_ROLE, company="B"),
        _posting("3", "Product Owner", PRODUCT_ROLE, company="C"),
    ])
    fields = {r["title"]: r["domain"] for r in dashboard["roles"]}

    assert fields == {"Data Engineer": "data", "Backend Engineer": "software",
                      "Product Owner": "product"}


def test_the_published_field_list_counts_each_one():
    dashboard = _build([
        _posting("1", "Data Engineer", DATA_ROLE, company="A"),
        _posting("2", "Backend Engineer", SOFTWARE_ROLE, company="B"),
    ])
    counts = {d["id"]: d["roles"] for d in dashboard["domains"]}

    assert counts["data"] == 1
    assert counts["software"] == 1
    assert counts["product"] == 0
    assert next(d for d in dashboard["domains"] if d["primary"])["id"] == "data"


def test_every_profile_declares_a_field():
    dashboard = _build([_posting("1", "Data Engineer", DATA_ROLE)])
    fields = {p["domain"] for p in dashboard["profiles"]}

    assert fields <= {"data", "software", "product"}
    assert "data" in fields


def test_a_product_role_is_not_scored_as_a_data_role():
    """A product posting must be kept and classified, not discarded as it was
    when the gate was only data or not."""
    dashboard = _build([_posting("1", "Product Owner", PRODUCT_ROLE)])

    assert dashboard["pipeline"]["out_of_domain"] == 0
    assert dashboard["roles"][0]["domain"] == "product"
    assert any(s["name"] == "Roadmapping" for s in dashboard["roles"][0]["skills"])


def test_roles_outside_every_field_are_still_turned_away():
    dashboard = _build([_posting("1", "Marketing Manager", DATA_ROLE)])

    assert dashboard["roles"] == []
    assert dashboard["pipeline"]["out_of_domain"] == 1


def test_roles_publish_the_key_the_outcome_monitor_expects():
    """Site ids and outcome keys use different separators. Publishing the key
    means the browser never has to reconstruct it."""
    from agents.digest import DigestEntry
    from agents.scoring import FitScore

    posting = _posting("57364886", "Data Engineer", DATA_ROLE)
    role = _build([posting])["roles"][0]
    expected = DigestEntry(posting=posting, fit=FitScore(posting_id="1", total=80)).key

    assert role["outcome_key"] == expected
    assert role["id"] != role["outcome_key"]
