"""Tests for Agent 5: Weekly digest.

No network. SendGrid is reached through an httpx mock transport, the same way
the job board clients are tested, so every send path can be exercised without
a key and without sending anything.

The tests weighted most heavily are the ones where a mistake would quietly cost
the candidate an opportunity: a failed send hiding roles, a repeat send
training them to ignore the email, and untrusted text breaking the layout.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from agents.digest import (
    MAX_ENTRIES,
    Digest,
    DigestEntry,
    ResendSender,
    SendGridSender,
    compile_digest,
    deliver,
    load_seen,
    mark_seen,
    render_html,
    render_text,
)
from agents.extraction import Confidence
from agents.ingestion import Posting
from agents.scoring import FitScore

WEEK = date(2026, 9, 21)


def _posting(job_id: str, title: str = "Data Engineer", **overrides) -> Posting:
    base = {
        "source": "reed",
        "source_job_id": job_id,
        "title": title,
        "description": "x" * 500,
        "has_full_description": True,
        "company": "Acme Ltd",
        "location": "London",
        "salary_min": 45000,
        "salary_max": 55000,
        "url": f"https://www.reed.co.uk/jobs/{job_id}",
    }
    base.update(overrides)
    return Posting(**base)


def _fit(job_id: str, total: int, provisional: bool = False, **overrides) -> FitScore:
    return FitScore(
        posting_id=job_id,
        total=total,
        confidence=Confidence.PARTIAL if provisional else Confidence.FULL,
        matched_skills=overrides.get("matched", ["Python", "SQL"]),
        partial_skills=overrides.get("partial", []),
        missing_essential=overrides.get("missing", []),
    )


def _scored(*specs) -> list[tuple[FitScore, Posting]]:
    # Each role gets its own title, so the fixture describes distinct
    # opportunities. Identical titles at one employer are treated as a single
    # repeated listing, which is tested separately.
    return [(_fit(j, t, p), _posting(j, title=f"Data Engineer {j}")) for j, t, p in specs]


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to, subject, html_body, text_body) -> None:
        self.sent.append({"to": to, "subject": subject, "html": html_body, "text": text_body})


class FailingSender:
    def send(self, to, subject, html_body, text_body) -> None:
        raise RuntimeError("SendGrid unavailable")


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def test_already_sent_postings_are_not_repeated():
    """Resending last week's roles trains the reader to ignore the email."""
    digest = compile_digest(
        _scored(("1", 90, False), ("2", 85, False)), seen={"reed:1"}, week_of=WEEK
    )

    assert [e.posting.source_job_id for e in digest.entries] == ["2"]
    assert digest.skipped_already_sent == 1


def test_roles_below_the_threshold_are_left_out():
    digest = compile_digest(_scored(("1", 90, False), ("2", 40, False)), set(), WEEK, min_score=60)
    assert [e.posting.source_job_id for e in digest.entries] == ["1"]


def test_provisional_roles_go_in_a_separate_section():
    """A provisional score is not comparable and must never appear to rank
    alongside a fully analysed one."""
    digest = compile_digest(_scored(("1", 80, False), ("2", 95, True)), set(), WEEK)

    assert [e.posting.source_job_id for e in digest.entries] == ["1"]
    assert [e.posting.source_job_id for e in digest.provisional] == ["2"]


def test_full_roles_are_ranked_ahead_of_provisional_ones_for_the_limit():
    """When the cap bites, a higher provisional number must not crowd out a
    fully analysed role."""
    specs = [(f"p{i}", 99, True) for i in range(MAX_ENTRIES)] + [("full", 70, False)]
    digest = compile_digest(_scored(*specs), set(), WEEK)

    assert "full" in [e.posting.source_job_id for e in digest.entries]


def test_the_digest_is_capped():
    specs = [(str(i), 90, False) for i in range(MAX_ENTRIES + 5)]
    digest = compile_digest(_scored(*specs), set(), WEEK)
    assert len(digest.entries) == MAX_ENTRIES


# ---------------------------------------------------------------------------
# Delivery and the seen store
# ---------------------------------------------------------------------------


def test_a_successful_send_records_the_postings(tmp_path):
    seen_path = tmp_path / "seen.json"
    digest = compile_digest(_scored(("1", 90, False)), set(), WEEK)
    sender = RecordingSender()

    sent = deliver(digest, sender, "me@example.com", "Emmanuel Olusolade", seen_path)

    assert sent is True
    assert len(sender.sent) == 1
    assert load_seen(seen_path) == {"reed:1"}


def test_a_failed_send_does_not_mark_anything_as_sent(tmp_path):
    """The most important test in this file. If postings were recorded before
    the send and the send failed, those roles would be hidden permanently with
    no record of why."""
    seen_path = tmp_path / "seen.json"
    digest = compile_digest(_scored(("1", 90, False)), set(), WEEK)

    with pytest.raises(RuntimeError):
        deliver(digest, FailingSender(), "me@example.com", "Emmanuel", seen_path)

    assert load_seen(seen_path) == set()


def test_after_a_failed_send_the_same_roles_are_offered_again(tmp_path):
    seen_path = tmp_path / "seen.json"
    scored = _scored(("1", 90, False))

    with pytest.raises(RuntimeError):
        deliver(compile_digest(scored, load_seen(seen_path), WEEK), FailingSender(),
                "me@example.com", "Emmanuel", seen_path)

    retry = compile_digest(scored, load_seen(seen_path), WEEK)
    assert [e.posting.source_job_id for e in retry.entries] == ["1"]


def test_an_empty_digest_is_not_sent(tmp_path):
    """An email saying nothing new trains the reader to ignore the sender."""
    sender = RecordingSender()
    sent = deliver(Digest(week_of=WEEK), sender, "me@example.com", "Emmanuel", tmp_path / "s.json")

    assert sent is False
    assert sender.sent == []


def test_a_corrupted_seen_store_fails_loudly(tmp_path):
    """Silently treating it as empty would resend everything."""
    path = tmp_path / "seen.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="not a valid seen store"):
        load_seen(path)


def test_mark_seen_accumulates_across_weeks(tmp_path):
    path = tmp_path / "seen.json"
    mark_seen(["reed:1"], path)
    mark_seen(["reed:2"], path)
    assert load_seen(path) == {"reed:1", "reed:2"}


# ---------------------------------------------------------------------------
# Rendering and untrusted input
# ---------------------------------------------------------------------------


def test_untrusted_titles_are_escaped():
    """Titles come from job boards this system does not control."""
    hostile = _posting("1", title='<script>alert("x")</script> Data Engineer')
    digest = Digest(week_of=WEEK, entries=[DigestEntry(posting=hostile, fit=_fit("1", 90))])

    html_body = render_html(digest, "Emmanuel")

    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body


def test_a_real_company_name_with_markup_characters_renders_safely():
    posting = _posting("1", company="Smith & Jones <Consulting>")
    digest = Digest(week_of=WEEK, entries=[DigestEntry(posting=posting, fit=_fit("1", 90))])

    html_body = render_html(digest, "Emmanuel")

    assert "Smith &amp; Jones &lt;Consulting&gt;" in html_body


def test_non_http_links_are_not_rendered_as_links():
    posting = _posting("1", url="javascript:alert(1)")
    digest = Digest(week_of=WEEK, entries=[DigestEntry(posting=posting, fit=_fit("1", 90))])

    assert "javascript:" not in render_html(digest, "Emmanuel")


def test_predicted_salaries_are_labelled_as_estimates():
    posting = _posting("1", salary_is_predicted=True)
    digest = Digest(week_of=WEEK, entries=[DigestEntry(posting=posting, fit=_fit("1", 90))])

    assert "estimated" in render_html(digest, "Emmanuel")


def test_missing_essentials_are_shown_so_the_score_is_explained():
    digest = Digest(
        week_of=WEEK,
        entries=[DigestEntry(posting=_posting("1"), fit=_fit("1", 70, missing=["Airflow"]))],
    )
    assert "Airflow" in render_html(digest, "Emmanuel")


def test_the_plain_text_version_carries_every_role():
    digest = compile_digest(_scored(("1", 90, False), ("2", 80, True)), set(), WEEK)
    text = render_text(digest)

    assert "BEST MATCHES" in text
    assert "provisional" in text.lower()
    assert "reed.co.uk/jobs/1" in text


# ---------------------------------------------------------------------------
# SendGrid transport
# ---------------------------------------------------------------------------


def test_sendgrid_payload_carries_both_formats():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(202)

    sender = SendGridSender(
        "SG.key", "from@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer SG.key"}),
    )
    sender.send("to@example.com", "Subject", "<p>hi</p>", "hi")

    types = [c["type"] for c in captured["body"]["content"]]
    assert types == ["text/plain", "text/html"]
    assert captured["body"]["personalizations"][0]["to"][0]["email"] == "to@example.com"


def test_a_sendgrid_rejection_raises_so_nothing_is_marked_sent(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="The from address does not match a verified Sender Identity")

    sender = SendGridSender(
        "SG.key", "from@example.com", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    seen_path = tmp_path / "seen.json"
    digest = compile_digest(_scored(("1", 90, False)), set(), WEEK)

    with pytest.raises(RuntimeError, match="403"):
        deliver(digest, sender, "me@example.com", "Emmanuel", seen_path)

    assert load_seen(seen_path) == set()


# ---------------------------------------------------------------------------
# Resend transport
# ---------------------------------------------------------------------------


def test_resend_payload_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "abc123"})

    sender = ResendSender("re_key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    sender.send("me@example.com", "Subject", "<p>hi</p>", "hi")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["body"]["to"] == ["me@example.com"]
    assert captured["body"]["html"] == "<p>hi</p>"
    assert captured["body"]["text"] == "hi"


def test_resend_defaults_to_the_shared_test_sender():
    """No domain is needed for a digest sent to its own author."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "abc123"})

    sender = ResendSender("re_key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    sender.send("me@example.com", "s", "h", "t")

    assert "onboarding@resend.dev" in captured["body"]["from"]


def test_resend_wrong_recipient_explains_the_fix_and_records_nothing(tmp_path):
    """The shared sender only delivers to the account owner. The error must say
    so, rather than leaving the reader to decode a bare 403."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, text="You can only send testing emails to your own email address"
        )

    sender = ResendSender("re_key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    seen_path = tmp_path / "seen.json"
    digest = compile_digest(_scored(("1", 90, False)), set(), WEEK)

    with pytest.raises(RuntimeError, match="DIGEST_TO_EMAIL"):
        deliver(digest, sender, "someone-else@example.com", "Emmanuel", seen_path)

    assert load_seen(seen_path) == set()


def test_resend_errors_do_not_leak_the_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Invalid key=re_SECRET123 supplied")

    sender = ResendSender("re_SECRET123", client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(RuntimeError) as excinfo:
        sender.send("me@example.com", "s", "h", "t")

    assert "re_SECRET123" not in str(excinfo.value)


def test_a_failure_recording_recommendations_leaves_roles_unsent(tmp_path, monkeypatch):
    """The first live send happened before recommendations were recorded, so
    ten roles were marked sent but unknown to the outcome monitor. If recording
    fails, the roles must stay unmarked so they are offered again."""

    def broken_record(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("agents.digest.record_recommendations", broken_record)
    seen_path = tmp_path / "seen.json"
    digest = compile_digest(_scored(("1", 90, False)), set(), WEEK)

    with pytest.raises(OSError):
        deliver(digest, RecordingSender(), "me@example.com", "Emmanuel", seen_path,
                recommendations_path=tmp_path / "recs.json")

    assert load_seen(seen_path) == set()


def test_a_successful_send_records_recommendations_and_marks_seen(tmp_path):
    from agents.outcomes import load_recommendations

    seen_path = tmp_path / "seen.json"
    recs_path = tmp_path / "recs.json"
    digest = compile_digest(_scored(("1", 90, False)), set(), WEEK)

    deliver(digest, RecordingSender(), "me@example.com", "Emmanuel", seen_path,
            recommendations_path=recs_path)

    assert load_seen(seen_path) == {"reed:1"}
    assert "reed:1" in load_recommendations(recs_path)


# ---------------------------------------------------------------------------
# Repeat listings
# ---------------------------------------------------------------------------


def test_one_employers_identical_listing_takes_only_one_slot():
    """The first live digest spent four of ten slots on one employer's
    identical role, posted separately in four locations."""
    scored = [
        (_fit(str(i), 77), _posting(str(i), title="Trainee Ai Engineer",
                                    company="IT Career Switch", location=loc))
        for i, loc in enumerate(["London", "Leeds", "Manchester", "Bristol"])
    ] + [(_fit("other", 70), _posting("other", title="Data Analyst", company="Acme Ltd"))]

    digest = compile_digest(scored, set(), WEEK)
    titles = [e.posting.title for e in digest.entries]

    assert titles.count("Trainee Ai Engineer") == 1
    assert "Data Analyst" in titles
    assert digest.skipped_repeat_listing == 3


def test_collapsed_locations_are_kept_rather_than_discarded():
    """The four copies were in different parts of London. Hiding the other
    three would lose information that matters, since one location may be far
    easier to reach. They take no slot, but they are still shown."""
    scored = [
        (_fit(str(i), 77), _posting(str(i), title="Trainee Ai Engineer",
                                    company="IT Career Switch", location=loc))
        for i, loc in enumerate(["E151AZ", "W52TD", "SW34LY", "E145HQ"])
    ]

    digest = compile_digest(scored, set(), WEEK)
    kept = digest.entries[0]

    assert kept.posting.location == "E151AZ"
    assert kept.other_locations == ["W52TD", "SW34LY", "E145HQ"]


def test_other_locations_appear_in_both_email_formats():
    entry = DigestEntry(
        posting=_posting("1", location="E151AZ"),
        fit=_fit("1", 77),
        other_locations=["W52TD", "SW34LY"],
    )
    digest = Digest(week_of=WEEK, entries=[entry])

    assert "Also listed in 2 other locations" in render_html(digest, "Emmanuel")
    assert "W52TD" in render_text(digest)


def test_a_full_digest_still_attaches_later_copies_of_kept_listings():
    """Once the shortlist is full, a later copy of a role already in it should
    still add its location rather than being lost."""
    scored = [(_fit(f"f{i}", 95 - i), _posting(f"f{i}", title=f"Role {i}"))
              for i in range(MAX_ENTRIES)]
    scored.append((_fit("dup", 60), _posting("dup", title="Role 0", location="Leeds")))

    digest = compile_digest(scored, set(), WEEK)
    role_zero = next(e for e in digest.entries if e.posting.title == "Role 0")

    assert "Leeds" in role_zero.other_locations


def test_repeat_detection_ignores_case_and_spacing():
    scored = [
        (_fit("1", 80), _posting("1", title="Data  Engineer", company="Acme Ltd")),
        (_fit("2", 79), _posting("2", title="data engineer", company="ACME LTD")),
    ]
    assert len(compile_digest(scored, set(), WEEK).entries) == 1


def test_the_same_title_at_different_employers_is_kept():
    """Two companies both hiring a Data Engineer are two real opportunities."""
    scored = [
        (_fit("1", 80), _posting("1", title="Data Engineer", company="Acme Ltd")),
        (_fit("2", 79), _posting("2", title="Data Engineer", company="Beta plc")),
    ]
    assert len(compile_digest(scored, set(), WEEK).entries) == 2


def test_the_highest_scoring_copy_of_a_repeat_listing_is_the_one_kept():
    scored = [
        (_fit("low", 70), _posting("low", title="Data Engineer", company="Acme Ltd")),
        (_fit("high", 88), _posting("high", title="Data Engineer", company="Acme Ltd")),
    ]
    kept = compile_digest(scored, set(), WEEK).entries
    assert [e.posting.source_job_id for e in kept] == ["high"]
