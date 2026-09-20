"""Candidate profile.

The CV is supplied as a small YAML file rather than parsed from a PDF. Parsing
a PDF introduces a failure mode that is invisible at scoring time: a mangled
extraction produces a confident but wrong fit score, and nobody finds out. A
structured file is explicit, diffable, and lets the candidate see exactly what
the scoring agent believes about them.

Skills are normalised through the same taxonomy the extraction agent uses, so
"sklearn" on a CV and "scikit-learn" in a posting resolve to the same canonical
name and match correctly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agents.extraction import find_skills

logger = logging.getLogger(__name__)

SENIORITY_ORDER = ["junior", "mid", "senior", "lead"]


@dataclass
class CV:
    name: str
    seniority: str
    years_experience: int
    skills: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    minimum_salary: int | None = None
    open_to_remote: bool = True
    # Free text that is scanned for skills the structured list missed, so a
    # skill mentioned only in a project description still counts.
    summary: str = ""

    @property
    def seniority_rank(self) -> int:
        try:
            return SENIORITY_ORDER.index(self.seniority)
        except ValueError:
            return 0

    @classmethod
    def from_file(cls, path: str | Path) -> CV:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            # ValueError rather than TypeError on purpose. This surfaces to a
            # candidate who has mis-edited their own CV file, and "bad value in
            # your file" is a more useful message than a type complaint.
            raise ValueError(f"{path} does not contain a YAML mapping")  # noqa: TRY004

        missing = [k for k in ("name", "seniority", "years_experience") if k not in raw]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")

        seniority = str(raw["seniority"]).lower()
        if seniority not in SENIORITY_ORDER:
            raise ValueError(
                f"seniority must be one of {SENIORITY_ORDER}, got {seniority!r}"
            )

        cv = cls(
            name=raw["name"],
            seniority=seniority,
            years_experience=int(raw["years_experience"]),
            skills=[str(s) for s in raw.get("skills", [])],
            preferred_locations=[str(loc) for loc in raw.get("preferred_locations", [])],
            minimum_salary=raw.get("minimum_salary"),
            open_to_remote=bool(raw.get("open_to_remote", True)),
            summary=str(raw.get("summary", "")),
        )
        cv.skills = cls._normalise_skills(cv)
        return cv

    @staticmethod
    def _normalise_skills(cv: CV) -> list[str]:
        """Resolve declared skills and summary text to canonical names.

        Anything the taxonomy does not recognise is kept as written rather than
        discarded, so a niche skill still appears in the profile even though it
        cannot take part in category matching.
        """
        canonical: set[str] = set()
        unrecognised: list[str] = []

        for declared in cv.skills:
            matches = find_skills(declared)
            if matches:
                canonical.update(m.name for m in matches)
            else:
                unrecognised.append(declared)

        if cv.summary:
            canonical.update(m.name for m in find_skills(cv.summary))

        if unrecognised:
            logger.info(
                "CV skills not in the taxonomy, kept as written: %s",
                ", ".join(unrecognised),
            )

        return sorted(canonical) + sorted(unrecognised)
