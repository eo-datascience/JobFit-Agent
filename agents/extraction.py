"""Agent 2: Skill extraction.

Turns a posting into structured requirements without inventing anything the
posting does not say. Two mechanisms, deliberately separated:

  Deterministic   Skills are matched literally against the text from a curated
                  taxonomy. A skill cannot be reported unless its alias appears
                  in the posting, and the matched span is kept as evidence.

  Model assisted  Seniority, years of experience and whether a requirement is
                  essential rather than preferred are judgement calls. These go
                  to Claude with a strict schema, and every field that comes
                  back is validated against the source before it is accepted.

Postings carry a confidence tier reflecting what the source could actually
supply. Adzuna has no detail endpoint, so its postings are excerpts and are
extracted on a reduced basis rather than discarded.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from agents.domains import PRIMARY_DOMAIN, classify_domain
from agents.ingestion import Posting
from agents.skills_taxonomy import (
    CASE_SENSITIVE_SKILLS,
    DESIRABLE_SECTION_HEADINGS,
    ESSENTIAL_SECTION_HEADINGS,
    NEUTRAL_SECTION_HEADINGS,
    SENIORITY_MARKERS,
    alias_to_canonical,
)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000

# Phrases that mark the requirement as mandatory rather than desirable.
_ESSENTIAL_CUES = [
    "must have", "essential", "required", "you will have", "you must",
    "proven experience", "demonstrable", "strong experience",
]
_PREFERRED_CUES = [
    "nice to have", "desirable", "preferred", "bonus", "advantageous",
    "would be a plus", "ideally",
]

_YEARS_PATTERN = re.compile(
    r"(\d+)\s*\+?\s*(?:to\s*\d+\s*)?year[s]?(?:\s+of)?\s+(?:relevant\s+|commercial\s+|professional\s+)?experience",
    re.IGNORECASE,
)


class Confidence(str, Enum):
    """What the source was actually able to supply.

    FULL     A complete description was parsed. Skills, seniority and
             essential markers are all meaningful.
    PARTIAL  Only an excerpt or a title was available. Skills found are real
             but the absence of a skill proves nothing, so downstream scoring
             must not penalise a posting for what is simply missing.
    """

    FULL = "full"
    PARTIAL = "partial"


class Relevance(str, Enum):
    """Whether the posting belongs to the candidate's field at all.

    Keyword search returns roles that merely mention the search terms. An "AI
    Creative Director" matches a search for "data scientist" because its text
    is saturated with the word AI, but scoring it against a data CV produces a
    number with no meaning. Out of domain postings are kept for the forecasting
    agent, which benefits from a wider view of the market, and excluded from
    fit scoring and the weekly digest.
    """

    IN_DOMAIN = "in_domain"
    OUT_OF_DOMAIN = "out_of_domain"


@dataclass
class ExtractedSkill:
    name: str
    # A generous window around the match. This is what makes the extraction
    # auditable: every skill can be traced back to a span in the source.
    evidence: str
    # Just the sentence containing the match. Cue matching uses this rather
    # than the wider window, so a cue belonging to a neighbouring skill cannot
    # be misattributed.
    sentence: str = ""
    is_essential: bool = False

    def __hash__(self) -> int:
        return hash(self.name)


@dataclass
class Requirements:
    posting_id: str
    source: str
    confidence: Confidence
    relevance: Relevance = Relevance.IN_DOMAIN
    relevance_reason: str = ""
    # Which field the posting belongs to, or None when it belongs to none of
    # them. The digest reads only the primary field; the site uses them all.
    domain: str | None = PRIMARY_DOMAIN
    skills: list[ExtractedSkill] = field(default_factory=list)
    seniority: str | None = None
    years_experience: int | None = None
    # Set when the model was called but its output failed validation, so the
    # record falls back to deterministic fields only.
    model_output_rejected: bool = False

    @property
    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]

    @property
    def essential_skills(self) -> list[str]:
        return [s.name for s in self.skills if s.is_essential]


# ---------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------


def find_skills(text: str) -> list[ExtractedSkill]:
    """Match taxonomy skills literally against the text.

    Aliases are checked longest first so that a longer phrase wins over a
    shorter overlapping one. Word boundaries prevent matching "R" inside
    ordinary words or "go" inside "going".
    """
    if not text:
        return []

    lookup = alias_to_canonical()
    found: dict[str, ExtractedSkill] = {}

    for alias in sorted(lookup, key=len, reverse=True):
        canonical = lookup[alias]
        if canonical in found:
            continue
        # A handful of skill names are also ordinary English words, so those
        # match only when capitalised as the product is.
        sensitive = canonical in CASE_SENSITIVE_SKILLS and alias == canonical.lower()
        flags = 0 if sensitive else re.IGNORECASE
        needle = canonical if sensitive else alias
        pattern = re.compile(rf"(?<![\w+#]){re.escape(needle)}(?![\w+#])", flags)
        match = pattern.search(text)
        if match:
            found[canonical] = ExtractedSkill(
                name=canonical,
                evidence=_evidence_window(text, match.start(), match.end()),
                sentence=_sentence_around(text, match.start(), match.end()),
            )

    return sorted(found.values(), key=lambda s: s.name)


_SENTENCE_BREAK = re.compile(r"[.!?\n]")


def _sentence_around(text: str, start: int, end: int) -> str:
    """Return only the sentence containing the match."""
    left_breaks = [m.end() for m in _SENTENCE_BREAK.finditer(text, 0, start)]
    left = left_breaks[-1] if left_breaks else 0
    right_match = _SENTENCE_BREAK.search(text, end)
    right = right_match.start() if right_match else len(text)
    return text[left:right].strip()


def _evidence_window(text: str, start: int, end: int, padding: int = 120) -> str:
    """Return the matched term with surrounding context, for auditability."""
    left = max(0, start - padding)
    right = min(len(text), end + padding)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right].strip()}{suffix}"


def split_into_sections(text: str) -> list[tuple[str | None, str]]:
    """Split a posting into (status, body) sections.

    Postings group requirements under headings rather than tagging each skill
    individually, so status is inherited from the heading a skill sits under.
    Status is "essential", "desirable" or None when no heading applies.
    """
    if not text:
        return []

    lines = text.split("\n")
    sections: list[tuple[str | None, list[str]]] = [(None, [])]

    for line in lines:
        stripped = line.strip().lower().rstrip(":").strip()
        # A heading is short and matches a known phrase. Length guards against
        # a sentence that merely contains the word "essential".
        is_heading = len(stripped) <= 60 and stripped
        status: str | None = None
        opens_section = False
        if is_heading:
            if any(h in stripped for h in DESIRABLE_SECTION_HEADINGS):
                status, opens_section = "desirable", True
            elif any(h in stripped for h in ESSENTIAL_SECTION_HEADINGS):
                status, opens_section = "essential", True
            elif any(h in stripped for h in NEUTRAL_SECTION_HEADINGS):
                # Closes whatever block was open without opening a new one.
                status, opens_section = None, True

        if opens_section:
            sections.append((status, []))
        else:
            sections[-1][1].append(line)

    return [(status, "\n".join(body)) for status, body in sections if body]


def mark_essential(skills: list[ExtractedSkill], text: str) -> list[ExtractedSkill]:
    """Mark skills essential or desirable using the section they appear in.

    Two passes. Section membership is the primary signal because postings
    organise requirements under headings. Inline cues near the skill are a
    fallback for postings written as continuous prose. Desirable always wins
    over essential, since claiming a nice to have is mandatory is the more
    damaging error for a candidate deciding whether to apply.
    """
    sections = split_into_sections(text)
    essential_text = " ".join(body.lower() for status, body in sections if status == "essential")
    desirable_text = " ".join(body.lower() for status, body in sections if status == "desirable")

    lookup = alias_to_canonical()
    aliases_by_skill: dict[str, list[str]] = {}
    for alias, canonical in lookup.items():
        aliases_by_skill.setdefault(canonical, []).append(alias)

    for skill in skills:
        aliases = aliases_by_skill.get(skill.name, [skill.name.lower()])
        in_desirable = any(alias in desirable_text for alias in aliases)
        in_essential = any(alias in essential_text for alias in aliases)

        if in_desirable:
            skill.is_essential = False
            continue
        if in_essential:
            skill.is_essential = True
            continue

        # Fallback for prose style postings with no headings. The sentence is
        # used rather than the wider evidence window, so a cue attached to a
        # different skill nearby cannot bleed across.
        window = (skill.sentence or skill.evidence).lower()
        if any(cue in window for cue in _PREFERRED_CUES):
            skill.is_essential = False
        elif any(cue in window for cue in _ESSENTIAL_CUES):
            skill.is_essential = True

    return skills


def detect_seniority(title: str, description: str = "") -> str | None:
    """Seniority from the title first, falling back to the description.

    The title is the more reliable signal, because a description often mentions
    reporting into a senior person without the role itself being senior.
    """
    for level, markers in SENIORITY_MARKERS:
        if any(marker in title.lower() for marker in markers):
            return level
    for level, markers in SENIORITY_MARKERS:
        if any(marker in description.lower()[:400] for marker in markers):
            return level
    return None


def detect_years(text: str) -> int | None:
    match = _YEARS_PATTERN.search(text or "")
    if not match:
        return None
    years = int(match.group(1))
    # Anything beyond this is almost always a parsing artefact rather than a
    # genuine requirement.
    return years if 0 < years <= 25 else None


# ---------------------------------------------------------------------------
# Model assisted extraction
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """You extract structured hiring requirements from UK job postings.

Rules you must follow without exception:
1. Report only what the posting states. Never infer, assume or supplement.
2. If the posting does not state something, return null for that field.
3. Every skill you return must appear verbatim in the posting text.
4. Return valid JSON only. No prose, no markdown fences, no commentary.

Schema:
{
  "seniority": "junior" | "mid" | "senior" | "lead" | null,
  "years_experience": integer or null,
  "essential_skills": [list of strings, each appearing verbatim in the posting],
  "preferred_skills": [list of strings, each appearing verbatim in the posting]
}"""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    """Thin wrapper so the agent can be tested without the SDK or a key."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._model = model

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def parse_model_json(raw: str) -> dict[str, Any] | None:
    """Parse the model response, tolerating fences but not inventing structure."""
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Model returned unparseable JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_against_source(payload: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Drop anything the model claims that the posting does not support.

    This is the grounding check. A skill that does not appear in the source is
    removed rather than trusted, and an out of range seniority or year count is
    discarded. What survives is guaranteed to be traceable to the posting.
    """
    lowered = source_text.lower()
    clean: dict[str, Any] = {}

    seniority = payload.get("seniority")
    clean["seniority"] = seniority if seniority in {"junior", "mid", "senior", "lead"} else None

    years = payload.get("years_experience")
    clean["years_experience"] = years if isinstance(years, int) and 0 < years <= 25 else None

    for key in ("essential_skills", "preferred_skills"):
        raw_list = payload.get(key) or []
        if not isinstance(raw_list, list):
            clean[key] = []
            continue
        kept = [
            item for item in raw_list
            if isinstance(item, str) and item.strip() and item.lower() in lowered
        ]
        dropped = len(raw_list) - len(kept)
        if dropped:
            logger.warning("Dropped %d ungrounded entries from %s", dropped, key)
        clean[key] = kept

    return clean


# ---------------------------------------------------------------------------
# Relevance gate
# ---------------------------------------------------------------------------


def classify_relevance(title: str, skills: list[ExtractedSkill]) -> tuple[Relevance, str]:
    """Whether a posting belongs to any field this system covers.

    A thin view over classify_domain, kept because relevance is what most of
    the pipeline cares about: a posting either gets scored or it does not.
    """
    domain, reason = classify_domain(title, [s.name for s in skills])
    return (Relevance.IN_DOMAIN if domain else Relevance.OUT_OF_DOMAIN), reason


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


def extract(posting: Posting, llm: LLMClient | None = None) -> Requirements:
    """Extract requirements from a single posting.

    Deterministic extraction always runs. The model is only consulted when a
    full description is available, because asking it to judge seniority from a
    two line excerpt invites exactly the guessing this design avoids.
    """
    confidence = Confidence.FULL if posting.has_full_description else Confidence.PARTIAL
    searchable = f"{posting.title}\n{posting.description}"

    skills = mark_essential(find_skills(searchable), searchable)
    domain, reason = classify_domain(posting.title, [s.name for s in skills])
    relevance = Relevance.IN_DOMAIN if domain else Relevance.OUT_OF_DOMAIN
    requirements = Requirements(
        posting_id=posting.source_job_id,
        source=posting.source,
        confidence=confidence,
        relevance=relevance,
        relevance_reason=reason,
        domain=domain,
        skills=skills,
        seniority=detect_seniority(posting.title, posting.description),
        years_experience=detect_years(posting.description),
    )

    if confidence is Confidence.PARTIAL or relevance is Relevance.OUT_OF_DOMAIN or llm is None:
        return requirements

    try:
        raw = llm.complete(SYSTEM_PROMPT, _build_user_prompt(posting))
    except Exception as exc:  # noqa: BLE001
        # Deliberately broad. The SDK can raise network, auth, rate limit and
        # serialisation errors, and the correct response to all of them is the
        # same: keep the deterministic extraction and mark the model output as
        # rejected. A failed model call must never cost us a posting.
        logger.warning("Model call failed for %s: %s", posting.source_job_id, exc)
        requirements.model_output_rejected = True
        return requirements

    payload = parse_model_json(raw)
    if payload is None:
        requirements.model_output_rejected = True
        return requirements

    validated = validate_against_source(payload, searchable)
    _merge_model_output(requirements, validated)
    return requirements


def _build_user_prompt(posting: Posting) -> str:
    return (
        f"Job title: {posting.title}\n"
        f"Company: {posting.company or 'Not stated'}\n"
        f"Location: {posting.location or 'Not stated'}\n\n"
        f"Posting text:\n{posting.description}"
    )


def _merge_model_output(requirements: Requirements, validated: dict[str, Any]) -> None:
    """Let validated model output fill gaps and upgrade essential markers.

    The model never overwrites a deterministic finding with nothing. It can
    supply a seniority the regex missed, but it cannot erase one the regex
    found, because the regex result is evidence based and the model's is not.
    """
    if validated.get("seniority") and not requirements.seniority:
        requirements.seniority = validated["seniority"]
    if validated.get("years_experience") and not requirements.years_experience:
        requirements.years_experience = validated["years_experience"]

    essential_text = " ".join(validated.get("essential_skills", [])).lower()
    for skill in requirements.skills:
        if skill.name.lower() in essential_text:
            skill.is_essential = True


def extract_many(postings: list[Posting], llm: LLMClient | None = None) -> list[Requirements]:
    results = [extract(posting, llm) for posting in postings]
    full = sum(1 for r in results if r.confidence is Confidence.FULL)
    in_domain = sum(1 for r in results if r.relevance is Relevance.IN_DOMAIN)
    rejected = sum(1 for r in results if r.model_output_rejected)
    logger.info(
        "Extracted %d postings: %d full confidence, %d partial, %d model outputs rejected.",
        len(results), full, len(results) - full, rejected,
    )
    logger.info(
        "%d of %d are in domain and will be scored. %d excluded as out of domain.",
        in_domain, len(results), len(results) - in_domain,
    )
    return results


def in_domain_only(results: list[Requirements]) -> list[Requirements]:
    """Filter for the scoring agent. Out of domain postings stay in the
    database for the forecasting agent but never reach the digest."""
    return [r for r in results if r.relevance is Relevance.IN_DOMAIN]


def only_domain(results: list[Requirements], domain: str) -> list[Requirements]:
    """Postings from one field.

    The digest uses this to stay in the primary field even when the wider
    sweep has brought other fields into the same run.
    """
    return [r for r in results if r.domain == domain]
