"""Agent 6: Outcome monitoring.

Closes the loop. The scoring weights were set by hand, and this agent lets real
application results correct them: it records what happened after each
application, measures which scoring components actually separated the
applications that went somewhere from the ones that did not, and nudges the
weights toward that evidence.

Learning from a personal job search is statistically hazardous, and almost all
of this module exists to handle that rather than to compute the adjustment.

  Silence is not rejection. An application sent last week with no reply is
  pending, not failed. Counting it as a failure would teach the model that
  whatever it recommended most recently was wrong. Silence only counts as a
  non response once a fixed window has passed.

  The sample is tiny. A single person produces dozens of outcomes, not
  thousands, which cannot support free estimation of four weights. Nothing is
  adjusted until there are enough resolved outcomes of both kinds, and even
  then the learned weights are shrunk heavily toward the originals, with the
  pull toward the evidence growing only as the evidence does.

  Adjustments are bounded. No weight may drift beyond half or one and a half
  times its original value, however strong the signal, so a run of luck cannot
  switch a component off.

  A component that never varies carries no information. Every posting searched
  so far is in London, so the location score is identical across applications
  and its correlation with outcomes is undefined. Such components keep their
  original weight rather than being misread as unimportant.

  What the system saw is recorded when it saw it. The component scores behind
  a recommendation are stored at the moment the digest sends it, because the
  weights, the CV and the posting itself may all change before an outcome
  arrives, and learning from recomputed scores would learn from something the
  system never actually showed.

Every adjustment is saved with the evidence behind it and can be reverted.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path

from agents.scoring import WEIGHTS
from paths import OUTCOMES_PATH as _OUTCOMES_PATH
from paths import RECOMMENDATIONS_PATH as _RECOMMENDATIONS_PATH
from paths import WEIGHTS_PATH as _WEIGHTS_PATH

logger = logging.getLogger(__name__)

RECOMMENDATIONS_PATH = _RECOMMENDATIONS_PATH
OUTCOMES_PATH = _OUTCOMES_PATH
WEIGHTS_PATH = _WEIGHTS_PATH

# An application with no reply after this long counts as no response.
RESPONSE_WINDOW_DAYS = 21

# Outcomes needed before any adjustment, in total and of each kind.
MIN_RESOLVED = 20
MIN_PER_CLASS = 5

# How strongly the original weights resist the evidence. The pull toward the
# learned weights is n / (n + PRIOR_STRENGTH), so twenty outcomes move the
# weights under a third of the way and a hundred move them two thirds.
PRIOR_STRENGTH = 50

# A learned weight may not leave this band around its original value.
MAX_DRIFT = 0.5


class Outcome(str, Enum):
    APPLIED = "applied"
    NO_RESPONSE = "no_response"
    REJECTED = "rejected"
    RESPONSE = "response"
    INTERVIEW = "interview"
    OFFER = "offer"


POSITIVE = {Outcome.RESPONSE, Outcome.INTERVIEW, Outcome.OFFER}
NEGATIVE = {Outcome.REJECTED, Outcome.NO_RESPONSE}


@dataclass
class Recommendation:
    """A role the digest sent, with the component scores it had at the time."""

    key: str
    title: str
    company: str | None
    total: int
    components: dict[str, float]
    provisional: bool
    recommended_on: str


@dataclass
class OutcomeRecord:
    key: str
    outcome: Outcome
    applied_on: str
    updated_on: str


@dataclass
class ComponentEvidence:
    component: str
    correlation: float | None
    mean_positive: float | None
    mean_negative: float | None
    note: str = ""


@dataclass
class WeightProposal:
    ready: bool
    reason: str
    current: dict[str, float]
    proposed: dict[str, float] = field(default_factory=dict)
    evidence: list[ComponentEvidence] = field(default_factory=list)
    resolved: int = 0
    positives: int = 0
    negatives: int = 0
    pending: int = 0
    learning_rate: float = 0.0


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError(f"{path} is corrupted. Inspect it rather than overwriting it.") from None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_recommendations(recs: list[Recommendation], path: Path = RECOMMENDATIONS_PATH) -> None:
    """Store what the digest sent. Existing snapshots are never overwritten,
    because the first recommendation is the one that counts."""
    existing = {r["key"]: r for r in _read_json(path, [])}
    for rec in recs:
        existing.setdefault(rec.key, asdict(rec))
    _write_json(path, list(existing.values()))


def load_recommendations(path: Path = RECOMMENDATIONS_PATH) -> dict[str, Recommendation]:
    return {r["key"]: Recommendation(**r) for r in _read_json(path, [])}


def load_outcomes(path: Path = OUTCOMES_PATH) -> dict[str, OutcomeRecord]:
    records = {}
    for raw in _read_json(path, []):
        raw["outcome"] = Outcome(raw["outcome"])
        records[raw["key"]] = OutcomeRecord(**raw)
    return records


def record_outcome(
    key: str,
    outcome: Outcome,
    on: date,
    recommendations_path: Path = RECOMMENDATIONS_PATH,
    outcomes_path: Path = OUTCOMES_PATH,
) -> OutcomeRecord:
    """Record or update the outcome of a recommended role.

    Only roles the digest actually recommended can be recorded, because an
    outcome with no snapshot behind it has nothing to learn from.
    """
    if key not in load_recommendations(recommendations_path):
        raise KeyError(f"{key} was never recommended by the digest, so there is nothing to learn from.")

    records = load_outcomes(outcomes_path)
    existing = records.get(key)
    applied_on = existing.applied_on if existing else on.isoformat()
    record = OutcomeRecord(key=key, outcome=outcome, applied_on=applied_on, updated_on=on.isoformat())
    records[key] = record

    _write_json(outcomes_path, [{**asdict(r), "outcome": r.outcome.value} for r in records.values()])
    return record


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    """The weights scoring should use: learned if any, otherwise the originals."""
    data = _read_json(path, {})
    return dict(data.get("current") or WEIGHTS)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def resolve(record: OutcomeRecord, today: date) -> Outcome | None:
    """Return the outcome to learn from, or None while it is still pending.

    An application still marked applied is pending until the response window
    passes, after which silence becomes a genuine non response.
    """
    if record.outcome is not Outcome.APPLIED:
        return record.outcome
    waited = today - date.fromisoformat(record.applied_on)
    if waited >= timedelta(days=RESPONSE_WINDOW_DAYS):
        return Outcome.NO_RESPONSE
    return None


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


def _correlation(xs: list[float], ys: list[int]) -> float | None:
    """Pearson correlation with a binary outcome, which is the point biserial.

    Returns None when either variable never varies, because the correlation is
    then undefined rather than zero, and treating it as zero would wrongly mark
    the component as unimportant.
    """
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return cov / (var_x * var_y) ** 0.5


def propose_weights(
    today: date,
    recommendations_path: Path = RECOMMENDATIONS_PATH,
    outcomes_path: Path = OUTCOMES_PATH,
    weights_path: Path = WEIGHTS_PATH,
) -> WeightProposal:
    current = load_weights(weights_path)
    recs = load_recommendations(recommendations_path)
    outcomes = load_outcomes(outcomes_path)

    rows: list[tuple[dict[str, float], int]] = []
    pending = 0
    for key, record in outcomes.items():
        rec = recs.get(key)
        # Provisional recommendations were scored without a skills component,
        # so they cannot say anything about how much skills should count.
        if rec is None or rec.provisional:
            continue
        resolved = resolve(record, today)
        if resolved is None:
            pending += 1
            continue
        rows.append((rec.components, 1 if resolved in POSITIVE else 0))

    positives = sum(y for _, y in rows)
    negatives = len(rows) - positives
    proposal = WeightProposal(
        ready=False, reason="", current=current,
        resolved=len(rows), positives=positives, negatives=negatives, pending=pending,
    )

    if len(rows) < MIN_RESOLVED:
        proposal.reason = (
            f"{len(rows)} resolved outcomes so far, {MIN_RESOLVED} needed before the "
            f"weights are adjusted. {pending} still pending."
        )
        return proposal
    if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
        proposal.reason = (
            f"Need at least {MIN_PER_CLASS} positive and {MIN_PER_CLASS} negative outcomes "
            f"to compare them. Have {positives} and {negatives}."
        )
        return proposal

    ys = [y for _, y in rows]
    signal: dict[str, float] = {}
    for component, prior in WEIGHTS.items():
        xs = [comps.get(component, 0.0) for comps, _ in rows]
        pos = [x for x, y in zip(xs, ys, strict=True) if y]
        neg = [x for x, y in zip(xs, ys, strict=True) if not y]
        r = _correlation(xs, ys)
        evidence = ComponentEvidence(
            component=component,
            correlation=round(r, 3) if r is not None else None,
            mean_positive=round(sum(pos) / len(pos), 3),
            mean_negative=round(sum(neg) / len(neg), 3),
        )
        if r is None:
            evidence.note = "never varied across applications, so it carries no information and keeps its weight"
            signal[component] = prior
        else:
            # A component that failed to separate outcomes, or pointed the
            # wrong way, earns no evidence of importance. Its weight is then
            # carried by the prior and the floor below, not driven to zero.
            signal[component] = max(r, 0.0)
            evidence.note = "separated outcomes" if r > 0.1 else "did not separate outcomes"
        proposal.evidence.append(evidence)

    total_signal = sum(signal.values())
    if total_signal == 0:
        proposal.reason = "No component separated positive from negative outcomes. Weights unchanged."
        return proposal
    learned = {k: v / total_signal for k, v in signal.items()}

    rate = len(rows) / (len(rows) + PRIOR_STRENGTH)
    blended = {k: current[k] + rate * (learned[k] - current[k]) for k in WEIGHTS}
    bounded = {
        k: min(max(v, WEIGHTS[k] * (1 - MAX_DRIFT)), WEIGHTS[k] * (1 + MAX_DRIFT))
        for k, v in blended.items()
    }
    norm = sum(bounded.values())

    proposal.proposed = {k: round(v / norm, 4) for k, v in bounded.items()}
    proposal.learning_rate = round(rate, 3)
    proposal.ready = True
    proposal.reason = (
        f"{len(rows)} resolved outcomes ({positives} positive, {negatives} negative). "
        f"Weights moved {rate:.0%} of the way toward the evidence."
    )
    return proposal


def apply_proposal(proposal: WeightProposal, today: date, path: Path = WEIGHTS_PATH) -> None:
    """Adopt a proposal, keeping the full history so it can be reverted."""
    if not proposal.ready:
        raise ValueError(f"Proposal is not ready: {proposal.reason}")
    data = _read_json(path, {})
    history = data.get("history", [])
    history.append({
        "date": today.isoformat(),
        "previous": proposal.current,
        "adopted": proposal.proposed,
        "resolved": proposal.resolved,
        "learning_rate": proposal.learning_rate,
        "evidence": [asdict(e) for e in proposal.evidence],
    })
    _write_json(path, {"current": proposal.proposed, "history": history})


def revert(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    """Undo the most recent adjustment."""
    data = _read_json(path, {})
    history = data.get("history", [])
    if not history:
        raise ValueError("There is no adjustment to revert.")
    last = history.pop()
    _write_json(path, {"current": last["previous"], "history": history})
    return last["previous"]
