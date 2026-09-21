"""Tests for Agent 6: Outcome monitoring.

Weighted toward the statistical safeguards, because a feedback loop that
learns the wrong lesson is worse than no feedback loop at all: it would steer
every future recommendation away from what actually works.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from agents.digest import Digest, DigestEntry, deliver
from agents.extraction import Confidence
from agents.ingestion import Posting
from agents.outcomes import (
    MAX_DRIFT,
    MIN_PER_CLASS,
    MIN_RESOLVED,
    RESPONSE_WINDOW_DAYS,
    Outcome,
    OutcomeRecord,
    Recommendation,
    apply_proposal,
    load_outcomes,
    load_recommendations,
    load_weights,
    propose_weights,
    record_outcome,
    record_recommendations,
    resolve,
    revert,
)
from agents.scoring import WEIGHTS, ComponentScore, FitScore

TODAY = date(2026, 9, 21)
LONG_AGO = (TODAY - timedelta(days=RESPONSE_WINDOW_DAYS + 10)).isoformat()


def _rec(key: str, skills: float, seniority: float = 0.8, salary: float = 0.8,
         location: float = 1.0, provisional: bool = False) -> Recommendation:
    return Recommendation(
        key=key, title="Data Engineer", company="Acme", total=80,
        components={"skills": skills, "seniority": seniority, "salary": salary, "location": location},
        provisional=provisional, recommended_on=LONG_AGO,
    )


def _seed(positive_skill: float, negative_skill: float, n_pos: int, n_neg: int,
          when: date = TODAY, **kwargs) -> None:
    """Record recommendations and resolved outcomes in the working directory."""
    recs = []
    for i in range(n_pos):
        recs.append(_rec(f"pos{i}", positive_skill, **kwargs))
    for i in range(n_neg):
        recs.append(_rec(f"neg{i}", negative_skill, **kwargs))
    record_recommendations(recs)
    for i in range(n_pos):
        record_outcome(f"pos{i}", Outcome.INTERVIEW, when)
    for i in range(n_neg):
        record_outcome(f"neg{i}", Outcome.REJECTED, when)


# ---------------------------------------------------------------------------
# Silence is not rejection
# ---------------------------------------------------------------------------


def test_a_recent_application_with_no_reply_is_pending_not_failed():
    """Counting last week's silence as failure would teach the model that
    whatever it recommended most recently was wrong."""
    recent = OutcomeRecord("k", Outcome.APPLIED, applied_on=(TODAY - timedelta(days=3)).isoformat(),
                           updated_on=TODAY.isoformat())
    assert resolve(recent, TODAY) is None


def test_silence_becomes_a_non_response_after_the_window():
    old = OutcomeRecord("k", Outcome.APPLIED, applied_on=LONG_AGO, updated_on=LONG_AGO)
    assert resolve(old, TODAY) is Outcome.NO_RESPONSE


def test_an_explicit_outcome_resolves_immediately():
    rec = OutcomeRecord("k", Outcome.REJECTED, applied_on=TODAY.isoformat(), updated_on=TODAY.isoformat())
    assert resolve(rec, TODAY) is Outcome.REJECTED


def test_pending_applications_are_excluded_from_learning():
    _seed(0.9, 0.3, MIN_RESOLVED, MIN_RESOLVED)
    record_recommendations([_rec("fresh", 0.1)])
    record_outcome("fresh", Outcome.APPLIED, TODAY)

    proposal = propose_weights(TODAY)

    assert proposal.pending == 1
    assert proposal.resolved == MIN_RESOLVED * 2


# ---------------------------------------------------------------------------
# Small samples
# ---------------------------------------------------------------------------


def test_nothing_changes_below_the_minimum_sample():
    _seed(0.9, 0.3, 3, 3)
    proposal = propose_weights(TODAY)

    assert proposal.ready is False
    assert "needed before" in proposal.reason


def test_nothing_changes_without_enough_of_both_outcomes():
    """Twenty rejections and no successes cannot say what success looks like."""
    _seed(0.9, 0.3, MIN_PER_CLASS - 1, MIN_RESOLVED)
    proposal = propose_weights(TODAY)

    assert proposal.ready is False
    assert "positive" in proposal.reason


def test_learning_rate_grows_with_evidence():
    _seed(0.9, 0.3, 10, 10)
    small = propose_weights(TODAY).learning_rate

    _seed(0.9, 0.3, 60, 60)
    large = propose_weights(TODAY).learning_rate

    assert 0 < small < large < 1


# ---------------------------------------------------------------------------
# Direction and bounds
# ---------------------------------------------------------------------------


def test_a_component_that_separates_outcomes_gains_weight():
    """Successful applications had much higher skills scores."""
    _seed(positive_skill=0.95, negative_skill=0.2, n_pos=40, n_neg=40,
          seniority=0.8, salary=0.8)
    proposal = propose_weights(TODAY)

    assert proposal.ready is True
    assert proposal.proposed["skills"] > WEIGHTS["skills"]


def test_weights_never_leave_their_bounds():
    """However strong the signal, a run of luck cannot switch a component off."""
    _seed(positive_skill=1.0, negative_skill=0.0, n_pos=500, n_neg=500)
    proposal = propose_weights(TODAY)

    for component, weight in proposal.proposed.items():
        # Allow for renormalisation after bounding.
        assert weight >= WEIGHTS[component] * (1 - MAX_DRIFT) * 0.8
        assert weight <= WEIGHTS[component] * (1 + MAX_DRIFT) * 1.2


def test_proposed_weights_sum_to_one():
    _seed(0.9, 0.3, 40, 40)
    proposal = propose_weights(TODAY)
    assert sum(proposal.proposed.values()) == pytest.approx(1.0, abs=1e-3)


def test_a_component_that_never_varies_keeps_its_weight():
    """Every search so far is in London, so location is identical everywhere.
    Its correlation is undefined, not zero, and it must not be read as
    unimportant."""
    _seed(0.9, 0.3, 40, 40, location=1.0)
    proposal = propose_weights(TODAY)

    location = next(e for e in proposal.evidence if e.component == "location")
    assert location.correlation is None
    assert "never varied" in location.note


def test_provisional_recommendations_do_not_teach_skills():
    """They were scored without a skills component."""
    record_recommendations([_rec(f"p{i}", 0.9, provisional=True) for i in range(50)])
    for i in range(50):
        record_outcome(f"p{i}", Outcome.INTERVIEW, TODAY)

    assert propose_weights(TODAY).resolved == 0


# ---------------------------------------------------------------------------
# Snapshots, history and reverting
# ---------------------------------------------------------------------------


def test_the_first_snapshot_is_never_overwritten():
    """Learning must use what the candidate was actually shown."""
    record_recommendations([_rec("k", skills=0.4)])
    record_recommendations([_rec("k", skills=0.9)])

    assert load_recommendations()["k"].components["skills"] == 0.4


def test_outcomes_can_only_be_recorded_for_recommended_roles():
    with pytest.raises(KeyError, match="never recommended"):
        record_outcome("unknown", Outcome.INTERVIEW, TODAY)


def test_updating_an_outcome_keeps_the_original_application_date():
    record_recommendations([_rec("k", 0.8)])
    record_outcome("k", Outcome.APPLIED, TODAY - timedelta(days=10))
    record_outcome("k", Outcome.INTERVIEW, TODAY)

    record = load_outcomes()["k"]
    assert record.applied_on == (TODAY - timedelta(days=10)).isoformat()
    assert record.outcome is Outcome.INTERVIEW


def test_applying_then_reverting_restores_the_original_weights():
    _seed(0.95, 0.2, 40, 40)
    apply_proposal(propose_weights(TODAY), TODAY)
    assert load_weights() != WEIGHTS

    restored = revert()

    assert restored == WEIGHTS
    assert load_weights() == WEIGHTS


def test_an_unready_proposal_cannot_be_applied():
    _seed(0.9, 0.3, 2, 2)
    with pytest.raises(ValueError, match="not ready"):
        apply_proposal(propose_weights(TODAY), TODAY)


def test_reverting_with_no_history_fails_clearly():
    with pytest.raises(ValueError, match="no adjustment"):
        revert()


def test_default_weights_are_used_before_any_learning():
    assert load_weights() == WEIGHTS


# ---------------------------------------------------------------------------
# Integration with the digest
# ---------------------------------------------------------------------------


class _RecordingSender:
    def send(self, to, subject, html_body, text_body) -> None:
        pass


def test_a_sent_digest_records_a_snapshot_for_each_role():
    posting = Posting(
        source="reed", source_job_id="42", title="Data Engineer", description="x" * 500,
        has_full_description=True, company="Acme", location="London",
    )
    fit = FitScore(
        posting_id="42", total=85, confidence=Confidence.FULL,
        components=[ComponentScore("skills", 0.9, 0.45, ""), ComponentScore("location", 1.0, 0.15, "")],
    )
    digest = Digest(week_of=TODAY, entries=[DigestEntry(posting=posting, fit=fit)])

    deliver(digest, _RecordingSender(), "me@example.com", "Emmanuel")

    snapshot = load_recommendations()["reed:42"]
    assert snapshot.components == {"skills": 0.9, "location": 1.0}
    assert snapshot.provisional is False


def test_a_failed_send_records_no_snapshot():
    class Failing:
        def send(self, to, subject, html_body, text_body) -> None:
            raise RuntimeError("down")

    posting = Posting(source="reed", source_job_id="7", title="t", description="x" * 500,
                      has_full_description=True)
    digest = Digest(week_of=TODAY, entries=[DigestEntry(posting=posting, fit=FitScore("7", 80))])

    with pytest.raises(RuntimeError):
        deliver(digest, Failing(), "me@example.com", "Emmanuel")

    assert load_recommendations() == {}
