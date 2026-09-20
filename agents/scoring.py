"""Agent 3: Fit scoring.

Scores a posting against the candidate's CV and explains the result in terms
the candidate can check. Every number in the explanation comes from a field the
scoring step actually computed, so the justification cannot drift from the
score it is describing.

Four components, weighted:

    skills      0.45   What the role asks for against what the CV has
    seniority   0.25   Whether the level is a reasonable step
    salary      0.15   Whether the range clears the candidate's floor
    location    0.15   Whether the role is somewhere they would work

Two ideas carry most of the weight in the skills component. Essential skills
count for more than desirable ones, because missing a stated requirement is a
different thing from missing a bonus. And a same category match earns partial
credit, because someone who knows Prefect will pick up Airflow far faster than
someone who has never orchestrated anything.

Confidence from the extraction agent changes how absence is read. On a full
description, a missing skill means the role does not want it. On an Adzuna
excerpt it means nothing at all, so the skills component is scored on what is
present and its weight is redistributed rather than counting a silence against
the posting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agents.cv import CV, SENIORITY_ORDER
from agents.extraction import Confidence, Requirements
from agents.skills_taxonomy import category_of

logger = logging.getLogger(__name__)

WEIGHTS = {
    "skills": 0.45,
    "seniority": 0.25,
    "salary": 0.15,
    "location": 0.15,
}

# An essential skill counts for this much more than a desirable one.
ESSENTIAL_MULTIPLIER = 2.0

# Credit awarded when the CV has a different tool from the same category.
CATEGORY_MATCH_CREDIT = 0.5

REMOTE_MARKERS = ["remote", "work from home", "wfh", "anywhere"]


@dataclass
class ComponentScore:
    name: str
    score: float
    weight: float
    detail: str

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass
class FitScore:
    posting_id: str
    total: int
    components: list[ComponentScore] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    partial_skills: list[str] = field(default_factory=list)
    missing_essential: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.FULL

    @property
    def is_provisional(self) -> bool:
        """True when the skills component could not be computed.

        A provisional score is not on the same scale as a full one. It answers
        a different question: not "how well does this role fit" but "how well
        does it fit on everything except the part that matters most".
        """
        return self.confidence is Confidence.PARTIAL

    @property
    def rank_key(self) -> tuple[int, int]:
        """Sort key that keeps provisional scores below full ones.

        Redistributing the skills weight across seniority, salary and location
        inflates provisional scores, because those three are easy to score
        highly on. Without this, postings the system knows nothing about
        systematically outrank postings it has fully analysed, which is the
        opposite of useful. Tiering is preferred to an arbitrary discount
        because it makes no claim about how much a provisional score should be
        marked down, only that it cannot be compared like for like.
        """
        return (0 if self.is_provisional else 1, self.total)

    def component(self, name: str) -> ComponentScore | None:
        return next((c for c in self.components if c.name == name), None)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def score_skills(cv: CV, requirements: Requirements) -> tuple[float, dict]:
    """Weighted coverage of the role's skills by the CV.

    Returns the score and the evidence behind it, so the explanation can name
    specific skills rather than asserting a number.
    """
    if not requirements.skills:
        return 0.0, {"matched": [], "partial": [], "missing_essential": [], "detail": "no skills stated"}

    cv_skills = set(cv.skills)
    cv_categories = {category_of(s) for s in cv_skills} - {None}

    matched: list[str] = []
    partial: list[str] = []
    missing_essential: list[str] = []

    earned = 0.0
    possible = 0.0

    for skill in requirements.skills:
        weight = ESSENTIAL_MULTIPLIER if skill.is_essential else 1.0
        possible += weight

        if skill.name in cv_skills:
            earned += weight
            matched.append(skill.name)
        elif category_of(skill.name) in cv_categories:
            earned += weight * CATEGORY_MATCH_CREDIT
            partial.append(skill.name)
        elif skill.is_essential:
            missing_essential.append(skill.name)

    score = earned / possible if possible else 0.0
    detail = f"{len(matched)} of {len(requirements.skills)} skills matched directly"
    if partial:
        detail += f", {len(partial)} by related experience"
    if missing_essential:
        detail += f", missing essential: {', '.join(missing_essential)}"

    return score, {
        "matched": matched,
        "partial": partial,
        "missing_essential": missing_essential,
        "detail": detail,
    }


def score_seniority(cv: CV, requirements: Requirements) -> tuple[float, str]:
    """How well the role's level suits the candidate.

    A role one step above is a stretch worth surfacing rather than a mismatch.
    A role far above is a waste of an application, and a role well below is a
    step backwards.
    """
    if not requirements.seniority:
        return 0.6, "level not stated, treated as neutral"

    try:
        role_rank = SENIORITY_ORDER.index(requirements.seniority)
    except ValueError:
        return 0.6, "level not recognised, treated as neutral"

    gap = role_rank - cv.seniority_rank

    if gap == 0:
        return 1.0, f"{requirements.seniority} matches your level"
    if gap == 1:
        return 0.75, f"{requirements.seniority} is one step up, a reasonable stretch"
    if gap == -1:
        return 0.5, f"{requirements.seniority} is one step below your level"
    if gap > 1:
        return 0.2, f"{requirements.seniority} is {gap} levels above your experience"
    return 0.25, f"{requirements.seniority} is {abs(gap)} levels below your experience"


def score_salary(cv: CV, salary_min: float | None, salary_max: float | None,
                 is_predicted: bool) -> tuple[float, str]:
    """Whether the advertised range clears the candidate's floor.

    A modelled salary is treated as weaker evidence than a stated one, so it
    cannot push a score as high on its own.
    """
    if cv.minimum_salary is None:
        return 0.6, "no salary floor set"
    if salary_min is None and salary_max is None:
        return 0.5, "salary not advertised"

    top = salary_max or salary_min or 0
    confidence_cap = 0.8 if is_predicted else 1.0
    source = "estimated" if is_predicted else "advertised"

    if top >= cv.minimum_salary * 1.2:
        return confidence_cap, f"{source} salary comfortably above your floor"
    if top >= cv.minimum_salary:
        return confidence_cap * 0.8, f"{source} salary meets your floor"
    if top >= cv.minimum_salary * 0.9:
        return confidence_cap * 0.4, f"{source} salary slightly below your floor"
    return 0.0, f"{source} salary below your floor"


def score_location(cv: CV, location: str | None) -> tuple[float, str]:
    if not location:
        return 0.5, "location not stated"

    lowered = location.lower()

    if cv.open_to_remote and any(marker in lowered for marker in REMOTE_MARKERS):
        return 1.0, "remote, which you are open to"

    for preferred in cv.preferred_locations:
        if preferred.lower() in lowered:
            return 1.0, f"in {preferred}"

    return 0.2, f"{location} is outside your preferred areas"


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


def score(
    cv: CV,
    requirements: Requirements,
    salary_min: float | None = None,
    salary_max: float | None = None,
    salary_is_predicted: bool = False,
    location: str | None = None,
) -> FitScore:
    """Produce a fit score between zero and one hundred.

    On a partial extraction the skills component is dropped and its weight is
    spread across the remaining components, because an Adzuna excerpt that does
    not mention Python is not a role that does not want Python.
    """
    skills_score, evidence = score_skills(cv, requirements)
    seniority_score, seniority_detail = score_seniority(cv, requirements)
    salary_score, salary_detail = score_salary(cv, salary_min, salary_max, salary_is_predicted)
    location_score, location_detail = score_location(cv, location)

    partial_extraction = requirements.confidence is Confidence.PARTIAL
    weights = dict(WEIGHTS)

    if partial_extraction:
        # Redistribute the skills weight proportionally across the rest.
        skills_weight = weights.pop("skills")
        remaining = sum(weights.values())
        weights = {k: v + (v / remaining) * skills_weight for k, v in weights.items()}

    components: list[ComponentScore] = []
    if not partial_extraction:
        components.append(ComponentScore("skills", skills_score, weights["skills"], evidence["detail"]))
    components.append(ComponentScore("seniority", seniority_score, weights["seniority"], seniority_detail))
    components.append(ComponentScore("salary", salary_score, weights["salary"], salary_detail))
    components.append(ComponentScore("location", location_score, weights["location"], location_detail))

    total = round(sum(c.contribution for c in components) * 100)

    return FitScore(
        posting_id=requirements.posting_id,
        total=total,
        components=components,
        matched_skills=evidence["matched"],
        partial_skills=evidence["partial"],
        missing_essential=evidence["missing_essential"],
        confidence=requirements.confidence,
    )


def explain(fit: FitScore) -> str:
    """Plain explanation built only from computed fields.

    Nothing here is generated. Every clause names a component and the detail
    that component produced, so the explanation and the score cannot disagree.
    """
    lines = [f"Fit score {fit.total} out of 100."]

    if fit.confidence is Confidence.PARTIAL:
        lines.append(
            "Provisional score. Only a summary of this posting was available, so the "
            "skills comparison could not be made and this score is not comparable "
            "to a fully analysed role."
            "The remaining factors carry the full weight."
        )

    for component in sorted(fit.components, key=lambda c: c.contribution, reverse=True):
        lines.append(
            f"  {component.name.title()}: {component.detail} "
            f"({component.score:.0%} of {component.weight:.0%})"
        )

    if fit.matched_skills:
        lines.append(f"  Direct skill matches: {', '.join(fit.matched_skills)}")
    if fit.partial_skills:
        lines.append(f"  Related experience: {', '.join(fit.partial_skills)}")
    if fit.missing_essential:
        lines.append(f"  Essential skills you do not have: {', '.join(fit.missing_essential)}")

    return "\n".join(lines)
