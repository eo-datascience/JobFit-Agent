"""Write the fixtures that pin the browser scorer to the Python one.

Scoring exists twice: in Python for the weekly agent, and in TypeScript so a
visitor's CV can be scored in their own browser without uploading it. Two hand
written implementations drift, and a drift here is invisible, because both
sides keep returning plausible numbers.

So Python scores a set of deliberately awkward cases and writes the answers
here. A Vitest suite asserts the TypeScript scorer reproduces them exactly.
Change the scoring rules without mirroring them and the frontend tests fail.

    python scripts/make_parity_fixtures.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.cv import CV
from agents.export import _scoring_rules
from agents.extraction import Confidence, ExtractedSkill, Requirements
from agents.scoring import score

OUT = ROOT / "frontend" / "src" / "__fixtures__" / "parity.json"


def _cv(**kw) -> CV:
    base = {"name": "Case", "seniority": "junior", "years_experience": 2,
            "skills": ["Python", "SQL", "pandas"], "preferred_locations": ["London"],
            "minimum_salary": None, "open_to_remote": True, "summary": ""}
    base.update(kw)
    return CV(**base)


def _req(skills, seniority=None, confidence=Confidence.FULL) -> Requirements:
    return Requirements(
        posting_id="1", source="reed", confidence=confidence, seniority=seniority,
        skills=[ExtractedSkill(name=n, evidence=n, is_essential=e) for n, e in skills],
    )


# Each case is chosen to exercise a branch that could plausibly be mirrored
# wrongly: essential weighting, category credit, the seniority ladder in both
# directions, salary confidence caps, remote matching, and the redistribution
# of the skills weight on a provisional posting.
CASES: list[dict] = [
    {
        "name": "every essential skill matched",
        "cv": _cv(),
        "req": _req([("Python", True), ("SQL", True)], "junior"),
        "salary": (40000, 50000, False), "location": "London",
    },
    {
        "name": "essential skills weigh double the desirable ones",
        "cv": _cv(skills=["Python"]),
        "req": _req([("Python", False), ("Airflow", True)], "junior"),
        "salary": (None, None, False), "location": "London",
    },
    {
        "name": "related experience earns partial credit",
        "cv": _cv(skills=["PostgreSQL"]),
        "req": _req([("MySQL", True)], "junior"),
        "salary": (None, None, False), "location": "London",
    },
    {
        "name": "one level up is a stretch",
        "cv": _cv(seniority="junior"),
        "req": _req([("Python", True)], "mid"),
        "salary": (None, None, False), "location": "London",
    },
    {
        "name": "two levels up is a poor fit",
        "cv": _cv(seniority="junior"),
        "req": _req([("Python", True)], "senior"),
        "salary": (None, None, False), "location": "London",
    },
    {
        "name": "a level below is a step backwards",
        "cv": _cv(seniority="senior"),
        "req": _req([("Python", True)], "mid"),
        "salary": (None, None, False), "location": "London",
    },
    {
        "name": "unstated seniority is neutral",
        "cv": _cv(),
        "req": _req([("Python", True)], None),
        "salary": (None, None, False), "location": "London",
    },
    {
        "name": "an estimated salary cannot score as high as a stated one",
        "cv": _cv(minimum_salary=30000),
        "req": _req([("Python", True)], "junior"),
        "salary": (50000, 60000, True), "location": "London",
    },
    {
        "name": "a stated salary comfortably above the floor",
        "cv": _cv(minimum_salary=30000),
        "req": _req([("Python", True)], "junior"),
        "salary": (50000, 60000, False), "location": "London",
    },
    {
        "name": "a salary below the floor scores nothing",
        "cv": _cv(minimum_salary=60000),
        "req": _req([("Python", True)], "junior"),
        "salary": (30000, 35000, False), "location": "London",
    },
    {
        "name": "remote suits a candidate open to it",
        "cv": _cv(preferred_locations=["Leeds"], open_to_remote=True),
        "req": _req([("Python", True)], "junior"),
        "salary": (None, None, False), "location": "Remote",
    },
    {
        "name": "a location outside the preferred ones",
        "cv": _cv(preferred_locations=["London"]),
        "req": _req([("Python", True)], "junior"),
        "salary": (None, None, False), "location": "Aberdeen",
    },
    {
        "name": "a provisional posting redistributes the skills weight",
        "cv": _cv(),
        "req": _req([("Python", True)], "junior", Confidence.PARTIAL),
        "salary": (40000, 50000, False), "location": "London",
    },
    {
        "name": "nothing matches at all",
        "cv": _cv(skills=["Excel"]),
        "req": _req([("Kubernetes", True), ("Terraform", True)], "lead"),
        "salary": (None, None, False), "location": "Aberdeen",
    },
]


def main() -> None:
    cases = []
    for case in CASES:
        low, high, predicted = case["salary"]
        fit = score(case["cv"], case["req"], salary_min=low, salary_max=high,
                    salary_is_predicted=predicted, location=case["location"])
        cv: CV = case["cv"]
        req: Requirements = case["req"]
        cases.append({
            "name": case["name"],
            "profile": {
                "skills": sorted(cv.skills),
                "seniority": cv.seniority,
                "locations": list(cv.preferred_locations),
                "openToRemote": cv.open_to_remote,
                "minimumSalary": cv.minimum_salary,
            },
            "role": {
                "confidence": req.confidence.value,
                "seniority": req.seniority,
                "skills": [{"name": s.name, "essential": s.is_essential} for s in req.skills],
                "salary_min": low, "salary_max": high, "salary_is_predicted": predicted,
                "location": case["location"],
            },
            "expected": {
                "total": fit.total,
                "provisional": fit.is_provisional,
                "components": [
                    {"name": c.name, "score": round(c.score, 6), "weight": round(c.weight, 6)}
                    for c in fit.components
                ],
                "matched": fit.matched_skills,
                "partial": fit.partial_skills,
                "missingEssential": fit.missing_essential,
            },
        })
        assert asdict(fit)  # the score is a plain dataclass, so it serialises

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rules": _scoring_rules(), "cases": cases}, indent=1),
                   encoding="utf-8")
    print(f"Wrote {len(cases)} parity cases to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
