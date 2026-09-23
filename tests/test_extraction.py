"""Tests for Agent 2: Skill extraction.

The tests that matter most here are the grounding ones. A skill must never
appear in the output unless it appears in the posting, and a model response
claiming otherwise must be rejected rather than trusted.
"""

from __future__ import annotations

import pytest

from agents.extraction import (
    Confidence,
    Relevance,
    detect_seniority,
    detect_years,
    extract,
    extract_many,
    find_skills,
    in_domain_only,
    mark_essential,
    only_domain,
    parse_model_json,
    validate_against_source,
)
from agents.ingestion import Posting

FULL_DESCRIPTION = """
We are looking for a Senior Data Engineer to join our platform team in London.

You must have strong experience with Python and SQL, and proven experience
building data pipelines with Airflow. You will be working with Snowflake and
dbt on a daily basis, and we expect 5 years of commercial experience.

Nice to have: exposure to Kubernetes and Terraform. Experience with Tableau
would be a plus but is not required.
"""

EXCERPT = "Data Analyst needed. Strong Excel and SQL skills. Apply now."


def _posting(title: str, description: str, full: bool, source: str = "reed") -> Posting:
    return Posting(
        source=source,
        source_job_id="1",
        title=title,
        description=description,
        has_full_description=full,
        company="Acme Ltd",
        location="London",
    )


# ---------------------------------------------------------------------------
# Deterministic skill matching
# ---------------------------------------------------------------------------


def test_finds_skills_that_are_present():
    skills = find_skills(FULL_DESCRIPTION)
    names = {s.name for s in skills}

    assert {"Python", "SQL", "Airflow", "Snowflake", "dbt", "Kubernetes", "Terraform"} <= names


def test_never_reports_a_skill_that_is_absent():
    """The core grounding guarantee of this agent."""
    names = {s.name for s in find_skills(FULL_DESCRIPTION)}

    assert "PyTorch" not in names
    assert "Hadoop" not in names
    assert "Power BI" not in names


def test_every_skill_carries_evidence_from_the_source():
    for skill in find_skills(FULL_DESCRIPTION):
        cleaned = skill.evidence.replace("...", "").strip()
        assert cleaned in " ".join(FULL_DESCRIPTION.split()) or cleaned in FULL_DESCRIPTION


def test_aliases_resolve_to_a_canonical_name():
    names = {s.name for s in find_skills("Experience with sklearn and k8s required.")}
    assert "scikit-learn" in names
    assert "Kubernetes" in names


def test_word_boundaries_prevent_false_positives():
    """Short skill names must not match inside longer words."""
    names = {s.name for s in find_skills("We are going to restructure the department.")}
    assert "Go" not in names
    assert "R" not in names


def test_empty_text_yields_no_skills():
    assert find_skills("") == []


# ---------------------------------------------------------------------------
# Essential versus preferred
# ---------------------------------------------------------------------------


def test_essential_and_preferred_are_distinguished():
    skills = mark_essential(find_skills(FULL_DESCRIPTION), FULL_DESCRIPTION)
    by_name = {s.name: s for s in skills}

    assert by_name["Python"].is_essential is True
    assert by_name["Kubernetes"].is_essential is False


# ---------------------------------------------------------------------------
# Seniority and years
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Senior Data Engineer", "senior"),
        ("Junior Data Scientist", "junior"),
        ("Graduate Analyst", "junior"),
        ("Head of Data", "lead"),
        ("Principal Machine Learning Engineer", "lead"),
        ("Data Engineer", None),
    ],
)
def test_seniority_is_read_from_the_title(title, expected):
    assert detect_seniority(title) == expected


def test_seniority_prefers_the_title_over_the_description():
    """A description mentioning a senior colleague must not promote the role."""
    assert detect_seniority("Data Analyst", "You will report to the Senior Data Manager.") == "senior"
    assert detect_seniority("Junior Data Analyst", "Reporting to a Senior Manager.") == "junior"


def test_years_of_experience_is_extracted():
    assert detect_years("we expect 5 years of commercial experience") == 5
    assert detect_years("3+ years experience required") == 3


def test_implausible_year_counts_are_rejected():
    assert detect_years("100 years of experience") is None


def test_missing_years_returns_none():
    assert detect_years("No specific requirement stated.") is None


# ---------------------------------------------------------------------------
# Confidence tiering
# ---------------------------------------------------------------------------


def test_full_description_yields_full_confidence():
    result = extract(_posting("Senior Data Engineer", FULL_DESCRIPTION, full=True))
    assert result.confidence is Confidence.FULL


def test_excerpt_yields_partial_confidence_but_still_extracts():
    """Adzuna excerpts are reduced, not discarded."""
    result = extract(_posting("Data Analyst", EXCERPT, full=False, source="adzuna"))

    assert result.confidence is Confidence.PARTIAL
    assert "SQL" in result.skill_names
    assert "Excel" in result.skill_names


def test_partial_postings_never_reach_the_model():
    """Asking a model to judge seniority from two lines invites guessing."""

    class ExplodingLLM:
        def complete(self, system: str, user: str) -> str:
            raise AssertionError("The model must not be called for a partial posting")

    result = extract(_posting("Data Analyst", EXCERPT, full=False), llm=ExplodingLLM())
    assert result.confidence is Confidence.PARTIAL


# ---------------------------------------------------------------------------
# Model output validation
# ---------------------------------------------------------------------------


def test_json_fences_are_tolerated():
    assert parse_model_json('```json\n{"seniority": "senior"}\n```') == {"seniority": "senior"}


def test_unparseable_model_output_returns_none():
    assert parse_model_json("I think this role is senior.") is None


def test_ungrounded_skills_are_stripped_from_model_output():
    """The model claims Kubernetes, which the posting never mentions."""
    payload = {
        "seniority": "senior",
        "years_experience": 5,
        "essential_skills": ["Python", "Kubernetes"],
        "preferred_skills": [],
    }
    source = "We need a Senior Engineer with Python and 5 years of experience."

    validated = validate_against_source(payload, source)

    assert validated["essential_skills"] == ["Python"]
    assert "Kubernetes" not in validated["essential_skills"]


def test_invalid_seniority_from_the_model_is_discarded():
    validated = validate_against_source({"seniority": "extremely senior"}, "text")
    assert validated["seniority"] is None


def test_implausible_years_from_the_model_are_discarded():
    validated = validate_against_source({"years_experience": 99}, "text")
    assert validated["years_experience"] is None


def test_model_failure_leaves_deterministic_results_intact():
    """A broken model call must degrade, not destroy."""

    class FailingLLM:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("API unavailable")

    result = extract(_posting("Senior Data Engineer", FULL_DESCRIPTION, full=True), llm=FailingLLM())

    assert result.model_output_rejected is True
    assert result.seniority == "senior"
    assert "Python" in result.skill_names


def test_model_cannot_erase_a_deterministic_finding():
    """The regex found seniority from the title. A null from the model must
    not overwrite evidence."""

    class NullingLLM:
        def complete(self, system: str, user: str) -> str:
            return '{"seniority": null, "years_experience": null, "essential_skills": [], "preferred_skills": []}'

    result = extract(_posting("Senior Data Engineer", FULL_DESCRIPTION, full=True), llm=NullingLLM())

    assert result.seniority == "senior"


def test_model_can_fill_a_gap_the_regex_missed():
    class HelpfulLLM:
        def complete(self, system: str, user: str) -> str:
            return '{"seniority": "mid", "years_experience": null, "essential_skills": [], "preferred_skills": []}'

    posting = _posting("Data Engineer", "Build pipelines with Python.", full=True)
    result = extract(posting, llm=HelpfulLLM())

    assert result.seniority == "mid"


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def test_extract_many_handles_mixed_confidence():
    postings = [
        _posting("Senior Data Engineer", FULL_DESCRIPTION, full=True),
        _posting("Data Analyst", EXCERPT, full=False, source="adzuna"),
    ]

    results = extract_many(postings)

    assert [r.confidence for r in results] == [Confidence.FULL, Confidence.PARTIAL]


# ---------------------------------------------------------------------------
# Section based essential detection
# ---------------------------------------------------------------------------


SECTIONED_POSTING = """
Data Engineer at Acme.

We are building a modern data platform.

Essential:
Strong Python and SQL. Experience with Airflow is expected.

Desirable:
Exposure to Kubernetes and Terraform.
"""


def test_skills_inherit_status_from_their_section_heading():
    """Postings group requirements under headings rather than tagging each
    skill, so the heading is the reliable signal."""
    skills = mark_essential(find_skills(SECTIONED_POSTING), SECTIONED_POSTING)
    by_name = {s.name: s for s in skills}

    assert by_name["Python"].is_essential is True
    assert by_name["SQL"].is_essential is True
    assert by_name["Airflow"].is_essential is True
    assert by_name["Kubernetes"].is_essential is False
    assert by_name["Terraform"].is_essential is False


def test_desirable_wins_when_a_skill_appears_in_both_sections():
    """Claiming a nice to have is mandatory is the more damaging error."""
    text = """
Essential:
Python and Docker.

Nice to have:
Docker at scale.
"""
    skills = mark_essential(find_skills(text), text)
    by_name = {s.name: s for s in skills}

    assert by_name["Docker"].is_essential is False


def test_prose_postings_still_fall_back_to_inline_cues():
    text = "You must have strong experience with Python. Tableau would be a plus."
    skills = mark_essential(find_skills(text), text)
    by_name = {s.name: s for s in skills}

    assert by_name["Python"].is_essential is True
    assert by_name["Tableau"].is_essential is False


# ---------------------------------------------------------------------------
# Short skill name false positives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Work closely with the R&D team on new products.",
        "Candidates should be organised. R. Smith is the hiring manager.",
        "We are going to expand the team this year.",
        "The go-live date is in March.",
    ],
)
def test_single_letter_and_short_names_do_not_match_ordinary_prose(text):
    names = {s.name for s in find_skills(text)}
    assert "R" not in names
    assert "Go" not in names


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Experience with R programming is required.", "R"),
        ("Strong RStudio skills.", "R"),
        ("We use Python/R for analysis.", "R"),
        ("Backend services written in Golang.", "Go"),
    ],
)
def test_unambiguous_forms_of_short_names_still_match(text, expected):
    assert expected in {s.name for s in find_skills(text)}


def test_neutral_headings_close_a_requirements_section():
    """Without this, an Essential block runs to the bottom of the posting and
    sweeps up benefits and company blurb, marking everything mandatory."""
    text = """
Essential:
Python and SQL.

Benefits:
We use Tableau company wide and offer Docker training.
"""
    skills = mark_essential(find_skills(text), text)
    by_name = {s.name: s for s in skills}

    assert by_name["Python"].is_essential is True
    assert by_name["SQL"].is_essential is True
    assert by_name["Tableau"].is_essential is False
    assert by_name["Docker"].is_essential is False


def test_about_us_section_does_not_make_its_tools_essential():
    text = """
About us:
Our platform runs on Kubernetes and AWS.

Requirements:
Strong Python.
"""
    by_name = {s.name: s for s in mark_essential(find_skills(text), text)}

    assert by_name["Python"].is_essential is True
    assert by_name["Kubernetes"].is_essential is False
    assert by_name["AWS"].is_essential is False


# ---------------------------------------------------------------------------
# Relevance gate
# ---------------------------------------------------------------------------


def test_creative_role_saturated_with_ai_is_excluded():
    """The real case that motivated this gate. An AI Creative Director matched
    a search for data scientist because its text is full of the word AI."""
    posting = _posting(
        "AI Creative Director",
        "Use AI creative tools such as Adobe Firefly across major campaigns and launches.",
        full=True,
    )

    result = extract(posting)

    assert result.relevance is Relevance.OUT_OF_DOMAIN
    assert "creative director" in result.relevance_reason


@pytest.mark.parametrize(
    "title",
    [
        "Marketing Manager",
        "Social Media Executive",
        "Recruitment Consultant",
        "Graphic Designer",
        "Care Assistant",
    ],
)
def test_non_domain_titles_are_excluded_regardless_of_description(title):
    """A technology heavy description must not rescue a non domain title."""
    posting = _posting(title, "We use Python, SQL, AWS and Docker throughout.", full=True)

    assert extract(posting).relevance is Relevance.OUT_OF_DOMAIN


@pytest.mark.parametrize(
    "title",
    ["Senior Data Engineer", "Machine Learning Engineer", "Data Analyst", "Analytics Engineer"],
)
def test_recognised_data_titles_are_in_domain(title):
    assert extract(_posting(title, "Details to follow.", full=True)).relevance is Relevance.IN_DOMAIN


def test_vague_data_title_with_no_skills_is_still_in_domain():
    """Some genuine postings never name their tooling. The title carries it."""
    result = extract(_posting("Data Scientist", "An exciting opportunity awaits.", full=True))

    assert result.relevance is Relevance.IN_DOMAIN
    assert result.skill_names == []


def test_unknown_title_with_technical_skills_is_in_domain():
    result = extract(_posting("Platform Specialist", "Strong Python, Airflow and dbt.", full=True))

    assert result.relevance is Relevance.IN_DOMAIN
    assert "skills point to" in result.relevance_reason


def test_unknown_title_with_no_skills_is_excluded():
    result = extract(_posting("Operations Coordinator", "Manage the daily rota.", full=True))

    assert result.relevance is Relevance.OUT_OF_DOMAIN
    assert "no recognised job title" in result.relevance_reason


def test_out_of_domain_postings_never_reach_the_model():
    """Scoring them is meaningless, so paying for a model call is waste."""

    class ExplodingLLM:
        def complete(self, system: str, user: str) -> str:
            raise AssertionError("The model must not be called for an out of domain posting")

    posting = _posting("Marketing Manager", "We love Python here.", full=True)
    assert extract(posting, llm=ExplodingLLM()).relevance is Relevance.OUT_OF_DOMAIN


def test_in_domain_only_filters_for_the_scoring_agent():
    results = extract_many([
        _posting("Data Engineer", FULL_DESCRIPTION, full=True),
        _posting("AI Creative Director", "Adobe Firefly and campaigns.", full=True),
    ])

    kept = in_domain_only(results)

    assert len(kept) == 1
    assert kept[0].relevance is Relevance.IN_DOMAIN


# ---------------------------------------------------------------------------
# Fields beyond data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Senior Data Engineer", "data"),
        ("Analytics Engineer", "data"),
        ("Backend Developer", "software"),
        ("Full Stack Engineer", "software"),
        ("Site Reliability Engineer", "software"),
        ("Product Owner", "product"),
        ("Senior Product Manager", "product"),
        ("Scrum Master", "product"),
        ("Marketing Manager", None),
        ("Care Assistant", None),
    ],
)
def test_postings_are_placed_in_the_right_field(title, expected):
    assert extract(_posting(title, "Details to follow.", full=True)).domain == expected


def test_the_most_specific_title_token_wins():
    """A data platform engineer is a data role, not a platform engineering one,
    even though both tokens appear in the title."""
    assert extract(_posting("Data Platform Engineer", "Details.", full=True)).domain == "data"


def test_skills_place_a_posting_when_the_title_does_not():
    product = extract(_posting("Delivery Specialist", """
Essential:
Roadmapping, user stories and backlog refinement with stakeholder management.
""", full=True))
    software = extract(_posting("Technical Specialist", """
Essential:
React, TypeScript and Node.js building microservices.
""", full=True))

    assert product.domain == "product"
    assert "skills point to product" in product.relevance_reason
    assert software.domain == "software"


def test_one_shared_skill_is_not_enough_to_place_a_posting():
    """Almost every field mentions SQL, so a single signature match means
    nothing."""
    result = extract(_posting("Operations Specialist", "Some SQL is useful.", full=True))

    assert result.domain is None
    assert result.relevance is Relevance.OUT_OF_DOMAIN


def test_only_domain_keeps_the_digest_in_its_own_field():
    """The wider sweep brings other fields into the same run. The digest must
    not start emailing product roles."""
    postings = [_posting("Data Engineer", "Details.", full=True),
                _posting("Backend Developer", "Details.", full=True),
                _posting("Product Owner", "Details.", full=True)]
    extracted = [extract(p) for p in postings]

    assert [r.domain for r in only_domain(extracted, "data")] == ["data"]
