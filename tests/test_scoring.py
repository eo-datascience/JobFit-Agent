"""Tests for Agent 3: Fit scoring.

The important properties here are directional. A change to the CV or the
posting must move the score the way a human would expect, and the explanation
must never claim something the score did not compute.
"""

from __future__ import annotations

import pytest

from agents.cv import CV
from agents.extraction import Confidence, ExtractedSkill, Relevance, Requirements
from agents.scoring import (
    WEIGHTS,
    explain,
    score,
    score_location,
    score_salary,
    score_seniority,
    score_skills,
)


def _cv(**overrides) -> CV:
    defaults = {
        "name": "Test Candidate",
        "seniority": "junior",
        "years_experience": 2,
        "skills": ["Python", "SQL", "pandas", "Prefect", "AWS"],
        "preferred_locations": ["London"],
        "minimum_salary": 35000,
        "open_to_remote": True,
    }
    defaults.update(overrides)
    return CV(**defaults)


def _requirements(skills: list[tuple[str, bool]], seniority: str | None = None,
                  confidence: Confidence = Confidence.FULL) -> Requirements:
    return Requirements(
        posting_id="1",
        source="reed",
        confidence=confidence,
        relevance=Relevance.IN_DOMAIN,
        skills=[ExtractedSkill(name=n, evidence=n, is_essential=e) for n, e in skills],
        seniority=seniority,
    )


# ---------------------------------------------------------------------------
# Skills component
# ---------------------------------------------------------------------------


def test_full_skill_match_scores_perfectly():
    result, _ = score_skills(_cv(), _requirements([("Python", True), ("SQL", True)]))
    assert result == 1.0


def test_no_skill_match_scores_zero():
    result, _ = score_skills(_cv(), _requirements([("Kubernetes", True), ("Terraform", True)]))
    assert result == 0.0


def test_essential_skills_weigh_more_than_desirable_ones():
    """Missing a stated requirement is worse than missing a bonus."""
    has_essential = _requirements([("Python", True), ("Kubernetes", False)])
    has_desirable = _requirements([("Kubernetes", True), ("Python", False)])

    essential_score, _ = score_skills(_cv(), has_essential)
    desirable_score, _ = score_skills(_cv(), has_desirable)

    assert essential_score > desirable_score


def test_same_category_experience_earns_partial_credit():
    """The CV has Prefect. The role wants Airflow. That is not nothing."""
    result, evidence = score_skills(_cv(), _requirements([("Airflow", True)]))

    assert 0 < result < 1
    assert "Airflow" in evidence["partial"]
    assert "Airflow" not in evidence["missing_essential"]


def test_unrelated_missing_essential_is_reported():
    _, evidence = score_skills(_cv(), _requirements([("Tableau", True)]))
    assert "Tableau" in evidence["missing_essential"]


def test_posting_with_no_skills_scores_zero_on_skills():
    result, evidence = score_skills(_cv(), _requirements([]))
    assert result == 0.0
    assert evidence["detail"] == "no skills stated"


# ---------------------------------------------------------------------------
# Seniority component
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cv_level, role_level, expected_order",
    [
        ("junior", "junior", "exact"),
        ("junior", "mid", "stretch"),
        ("junior", "lead", "far"),
    ],
)
def test_seniority_gap_reduces_the_score(cv_level, role_level, expected_order):
    result, _ = score_seniority(_cv(seniority=cv_level), _requirements([], seniority=role_level))
    expectations = {"exact": 1.0, "stretch": 0.75, "far": 0.2}
    assert result == expectations[expected_order]


def test_one_step_up_beats_two_steps_up():
    stretch, _ = score_seniority(_cv(seniority="junior"), _requirements([], seniority="mid"))
    far, _ = score_seniority(_cv(seniority="junior"), _requirements([], seniority="lead"))
    assert stretch > far


def test_unstated_seniority_is_neutral_not_penalised():
    result, detail = score_seniority(_cv(), _requirements([], seniority=None))
    assert result == 0.6
    assert "not stated" in detail


# ---------------------------------------------------------------------------
# Salary component
# ---------------------------------------------------------------------------


def test_salary_above_floor_scores_well():
    result, _ = score_salary(_cv(minimum_salary=35000), 45000, 55000, is_predicted=False)
    assert result == 1.0


def test_salary_below_floor_scores_zero():
    result, _ = score_salary(_cv(minimum_salary=50000), 25000, 30000, is_predicted=False)
    assert result == 0.0


def test_predicted_salary_cannot_score_as_high_as_a_stated_one():
    """Adzuna models salaries. A modelled figure is weaker evidence."""
    stated, _ = score_salary(_cv(minimum_salary=35000), 50000, 60000, is_predicted=False)
    predicted, _ = score_salary(_cv(minimum_salary=35000), 50000, 60000, is_predicted=True)

    assert predicted < stated


def test_unadvertised_salary_is_neutral():
    result, detail = score_salary(_cv(), None, None, is_predicted=False)
    assert result == 0.5
    assert "not advertised" in detail


# ---------------------------------------------------------------------------
# Location component
# ---------------------------------------------------------------------------


def test_preferred_location_scores_full():
    result, _ = score_location(_cv(), "London, EC2")
    assert result == 1.0


def test_remote_scores_full_when_open_to_it():
    result, _ = score_location(_cv(open_to_remote=True), "Fully Remote")
    assert result == 1.0


def test_remote_does_not_score_full_when_not_open_to_it():
    result, _ = score_location(_cv(open_to_remote=False, preferred_locations=["London"]), "Remote")
    assert result < 1.0


def test_distant_location_scores_low():
    result, _ = score_location(_cv(), "Aberdeen")
    assert result == 0.2


# ---------------------------------------------------------------------------
# Total score and confidence handling
# ---------------------------------------------------------------------------


def test_strong_match_scores_higher_than_weak_match():
    strong = score(
        _cv(),
        _requirements([("Python", True), ("SQL", True)], seniority="junior"),
        salary_min=40000, salary_max=50000, location="London",
    )
    weak = score(
        _cv(),
        _requirements([("Tableau", True), ("Qlik", True)], seniority="lead"),
        salary_min=20000, salary_max=25000, location="Aberdeen",
    )

    assert strong.total > weak.total


def test_adding_a_required_skill_to_the_cv_raises_the_score():
    """The most basic directional guarantee the model must hold."""
    requirements = _requirements([("Airflow", True), ("Python", True)], seniority="junior")

    without = score(_cv(), requirements, location="London")
    with_skill = score(_cv(skills=["Python", "SQL", "pandas", "Prefect", "AWS", "Airflow"]),
                       requirements, location="London")

    assert with_skill.total > without.total


def test_score_is_bounded():
    perfect = score(
        _cv(),
        _requirements([("Python", True)], seniority="junior"),
        salary_min=100000, salary_max=120000, location="London",
    )
    assert 0 <= perfect.total <= 100


def test_partial_extraction_drops_the_skills_component():
    """An excerpt that does not mention Python is not a role that rejects it."""
    result = score(
        _cv(),
        _requirements([("Python", True)], seniority="junior", confidence=Confidence.PARTIAL),
        location="London",
    )

    assert result.component("skills") is None
    assert result.confidence is Confidence.PARTIAL


def test_redistributed_weights_still_sum_to_one():
    result = score(
        _cv(),
        _requirements([], seniority="junior", confidence=Confidence.PARTIAL),
        location="London",
    )
    assert sum(c.weight for c in result.components) == pytest.approx(1.0)


def test_full_extraction_weights_sum_to_one():
    result = score(_cv(), _requirements([("Python", True)], seniority="junior"), location="London")
    assert sum(c.weight for c in result.components) == pytest.approx(sum(WEIGHTS.values()))


def test_partial_posting_is_not_punished_for_missing_skills():
    """The same thin posting must not score below itself merely for silence."""
    thin = _requirements([], seniority="junior", confidence=Confidence.PARTIAL)
    full_but_empty = _requirements([], seniority="junior", confidence=Confidence.FULL)

    assert score(_cv(), thin, location="London").total > score(
        _cv(), full_but_empty, location="London"
    ).total


# ---------------------------------------------------------------------------
# Explanation grounding
# ---------------------------------------------------------------------------


def test_explanation_reports_the_same_score_it_was_given():
    result = score(_cv(), _requirements([("Python", True)], seniority="junior"), location="London")
    assert f"{result.total} out of 100" in explain(result)


def test_explanation_names_only_skills_that_were_actually_matched():
    result = score(_cv(), _requirements([("Python", True), ("Tableau", True)]), location="London")
    text = explain(result)

    assert "Python" in text
    assert "Tableau" in text
    assert "Kubernetes" not in text


def test_explanation_discloses_when_skills_were_not_scored():
    result = score(
        _cv(),
        _requirements([("Python", True)], confidence=Confidence.PARTIAL),
        location="London",
    )
    text = explain(result)
    assert "Provisional" in text
    assert "only a summary" in text.lower()
    assert "not comparable" in text


def test_provisional_scores_never_outrank_fully_analysed_ones():
    """Redistributing the skills weight inflates provisional scores, because
    seniority, salary and location are all easy to score highly on. Without
    tiering, postings the system knows nothing about would fill the digest."""
    provisional = score(
        _cv(),
        _requirements([("Python", True)], confidence=Confidence.PARTIAL),
        salary_min=60000,
        location="London",
    )
    full = score(
        _cv(),
        # Skills the CV has neither directly nor in the same family.
        _requirements([("Kubernetes", True), ("Terraform", True), ("Tableau", True)]),
        salary_min=60000,
        location="London",
    )

    # The provisional score is genuinely the higher number.
    assert provisional.total > full.total
    # But it must still rank below, because the two are not comparable.
    assert provisional.rank_key < full.rank_key
    assert max([provisional, full], key=lambda f: f.rank_key) is full


def test_is_provisional_reflects_confidence():
    partial = score(_cv(), _requirements([("Python", True)], confidence=Confidence.PARTIAL))
    full = score(_cv(), _requirements([("Python", True)]))

    assert partial.is_provisional is True
    assert full.is_provisional is False
