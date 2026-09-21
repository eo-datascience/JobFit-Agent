"""Agent 5: Weekly digest.

The first agent that acts rather than reports. It compiles the week's best
matches, removes anything already sent, and emails the result with no approval
step in between.

Three properties matter more than the email itself.

  Nothing is marked as sent until the send succeeds. Marking first would mean a
  failed send permanently hides those postings, with no record of why, which is
  the worst kind of failure for a tool meant to surface opportunities.

  Every value that came from a job board is escaped before it enters the HTML.
  Titles and company names come from APIs this system does not control, so
  inserting them raw is an injection risk and a broken layout waiting to happen.

  An empty digest is not sent. An email saying "nothing new" trains the reader
  to ignore the sender, which defeats the purpose of the one that matters.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

import httpx

from agents.ingestion import Posting, redact_url
from agents.scoring import FitScore, explain

logger = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
RESEND_URL = "https://api.resend.com/emails"

# Resend's shared test sender. It needs no domain, but it only delivers to the
# email address the Resend account was created with. For a digest sent to its
# own author that restriction costs nothing.
RESEND_TEST_SENDER = "onboarding@resend.dev"
DEFAULT_SEEN_PATH = Path("data/sent_postings.json")

# Hard ceiling on how many roles one email carries. A digest is a shortlist;
# thirty roles is a job board.
MAX_ENTRIES = 10


@dataclass
class DigestEntry:
    posting: Posting
    fit: FitScore

    @property
    def key(self) -> str:
        return f"{self.posting.source}:{self.posting.source_job_id}"


@dataclass
class Digest:
    week_of: date
    entries: list[DigestEntry] = field(default_factory=list)
    provisional: list[DigestEntry] = field(default_factory=list)
    skipped_already_sent: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.entries and not self.provisional

    @property
    def keys(self) -> list[str]:
        return [e.key for e in self.entries + self.provisional]


# ---------------------------------------------------------------------------
# Seen store
# ---------------------------------------------------------------------------


def load_seen(path: Path = DEFAULT_SEEN_PATH) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        # A corrupted store must not silently resend everything, and it must
        # not silently send nothing. Failing loudly is the only safe option.
        raise ValueError(f"{path} is not a valid seen store. Inspect it before sending.") from None


def mark_seen(keys: list[str], path: Path = DEFAULT_SEEN_PATH) -> None:
    """Record postings as sent. Called only after a successful send."""
    seen = load_seen(path) | set(keys)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def compile_digest(
    scored: list[tuple[FitScore, Posting]],
    seen: set[str],
    week_of: date,
    min_score: int = 60,
    limit: int = MAX_ENTRIES,
) -> Digest:
    """Select what this week's email should contain.

    Fully analysed roles and provisional ones are kept in separate sections,
    because a provisional score is not comparable and must never appear to
    rank alongside a real one. Provisional roles fill only the space the full
    ones leave.
    """
    digest = Digest(week_of=week_of)
    ranked = sorted(scored, key=lambda pair: pair[0].rank_key, reverse=True)

    for fit, posting in ranked:
        entry = DigestEntry(posting=posting, fit=fit)
        if entry.key in seen:
            digest.skipped_already_sent += 1
            continue
        if fit.total < min_score:
            continue
        if len(digest.entries) + len(digest.provisional) >= limit:
            break
        (digest.provisional if fit.is_provisional else digest.entries).append(entry)

    logger.info(
        "Digest for week of %s: %d fully analysed, %d provisional, %d skipped as already sent.",
        week_of, len(digest.entries), len(digest.provisional), digest.skipped_already_sent,
    )
    return digest


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _e(value: object) -> str:
    """Escape anything that did not originate in this codebase."""
    return html.escape(str(value), quote=True)


def _salary(posting: Posting) -> str:
    low, high = posting.salary_min, posting.salary_max
    if not low and not high:
        return "Salary not stated"
    parts = [f"£{int(v):,}" for v in (low, high) if v]
    text = " to ".join(parts)
    return f"{text} (estimated)" if posting.salary_is_predicted else text


def _safe_url(url: str | None) -> str | None:
    """Only allow http and https links into the email."""
    if url and url.lower().startswith(("https://", "http://")):
        return url
    return None


def _render_entry(entry: DigestEntry) -> str:
    p, f = entry.posting, entry.fit
    url = _safe_url(p.url)
    title = _e(p.title)
    heading = f'<a href="{_e(url)}" style="color:#1a4d8f;text-decoration:none">{title}</a>' if url else title

    meta = (
        f'<div style="font-size:13px;color:#555">{_e(p.company or "Company not stated")}'
        f' &middot; {_e(p.location or "Location not stated")} &middot; {_e(_salary(p))}</div>'
    )
    rows = [meta]
    if f.matched_skills:
        rows.append(f'<div style="font-size:13px;margin-top:6px"><b>You have:</b> '
                    f'{_e(", ".join(f.matched_skills))}</div>')
    if f.partial_skills:
        rows.append(f'<div style="font-size:13px"><b>Related experience:</b> '
                    f'{_e(", ".join(f.partial_skills))}</div>')
    if f.missing_essential:
        rows.append(f'<div style="font-size:13px;color:#a33"><b>Missing essentials:</b> '
                    f'{_e(", ".join(f.missing_essential))}</div>')

    # Table cells rather than inline blocks. Outlook and several webmail
    # clients ignore display and min-width, which ran the score straight into
    # the title. A provisional score is greyed so a high number there cannot be
    # read as a stronger match than a fully analysed role above it.
    score_colour = "#9a9a9a" if f.is_provisional else "#1a4d8f"
    return (
        '<tr><td style="padding:14px 0;border-bottom:1px solid #eee">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="52" valign="top" style="font-size:22px;font-weight:700;color:{score_colour};'
        f'font-family:Arial,Helvetica,sans-serif">{f.total}</td>'
        '<td valign="top" style="font-family:Arial,Helvetica,sans-serif">'
        f'<div style="font-size:16px;font-weight:600">{heading}</div>'
        f'{"".join(rows)}</td></tr></table></td></tr>'
    )


def render_html(digest: Digest, candidate_name: str) -> str:
    sections = []
    if digest.entries:
        sections.append(
            '<h2 style="font-size:17px;margin:24px 0 4px">Best matches</h2>'
            '<table width="100%" cellpadding="0" cellspacing="0">'
            + "".join(_render_entry(e) for e in digest.entries)
            + "</table>"
        )
    if digest.provisional:
        sections.append(
            '<h2 style="font-size:17px;margin:24px 0 4px">Worth a look</h2>'
            '<p style="font-size:13px;color:#666;margin:0 0 4px">Only a summary of these '
            "postings was available, so skills could not be compared. Their scores are not "
            "comparable with the roles above.</p>"
            '<table width="100%" cellpadding="0" cellspacing="0">'
            + "".join(_render_entry(e) for e in digest.provisional)
            + "</table>"
        )

    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:auto;color:#222">'
        f'<h1 style="font-size:20px">Your JobFit shortlist, week of {digest.week_of:%d %B %Y}</h1>'
        f'<p style="font-size:14px">Hi {_e(candidate_name.split()[0])}, here are this week\'s roles '
        "scored against your CV. Scores are out of 100.</p>"
        + "".join(sections)
        + '<p style="font-size:12px;color:#888;margin-top:28px">Sent automatically by JobFit '
        "Agent. Roles already sent in a previous week are not repeated.</p></div>"
    )


def render_text(digest: Digest) -> str:
    """Plain text fallback, which mail clients use and spam filters expect."""
    lines = [f"Your JobFit shortlist, week of {digest.week_of:%d %B %Y}", ""]
    for label, group in (("BEST MATCHES", digest.entries), ("WORTH A LOOK (provisional)", digest.provisional)):
        if not group:
            continue
        lines += [label, ""]
        for e in group:
            lines.append(f"{e.fit.total}/100  {e.posting.title}")
            lines.append(f"        {e.posting.company or ''}, {e.posting.location or ''}")
            lines.append(f"        {explain(e.fit).splitlines()[0]}")
            if e.posting.url:
                lines.append(f"        {e.posting.url}")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


class Sender(Protocol):
    def send(self, to: str, subject: str, html_body: str, text_body: str) -> None: ...


class ResendSender:
    """The default provider.

    SendGrid retired its permanent free plan in May 2025, leaving a sixty day
    trial followed by a paid plan, which does not suit a job that sends one
    email a week indefinitely. Resend has a permanent free tier of three
    thousand emails a month. Because every provider sits behind the same Sender
    interface, switching required this class and nothing else in the agent.
    """

    def __init__(
        self,
        api_key: str,
        from_address: str = RESEND_TEST_SENDER,
        client: httpx.Client | None = None,
    ) -> None:
        self._from = from_address
        self._client = client or httpx.Client(
            timeout=20.0, headers={"Authorization": f"Bearer {api_key}"}
        )

    def send(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        payload = {
            "from": f"JobFit Agent <{self._from}>",
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        response = self._client.post(RESEND_URL, json=payload)
        if response.status_code >= 400:
            detail = redact_url(response.text)[:300]
            hint = ""
            if response.status_code == 403 and "own email" in response.text.lower():
                hint = (
                    " The test sender only delivers to the address your Resend account "
                    "was created with. Set DIGEST_TO_EMAIL to that address, or verify a domain."
                )
            raise RuntimeError(f"Resend rejected the message ({response.status_code}): {detail}{hint}")


class SendGridSender:
    """Plain HTTP against SendGrid's v3 API.

    The official SDK was not used. httpx is already a dependency, and calling
    the API directly means the send path can be tested with the same mock
    transport as the job board clients, with no network and no key.
    """

    def __init__(self, api_key: str, from_address: str, client: httpx.Client | None = None) -> None:
        self._from = from_address
        self._client = client or httpx.Client(
            timeout=20.0, headers={"Authorization": f"Bearer {api_key}"}
        )

    def send(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self._from, "name": "JobFit Agent"},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body},
            ],
        }
        response = self._client.post(SENDGRID_URL, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"SendGrid rejected the message ({response.status_code}): "
                f"{redact_url(response.text)[:300]}"
            )


def deliver(
    digest: Digest,
    sender: Sender,
    to: str,
    candidate_name: str,
    seen_path: Path = DEFAULT_SEEN_PATH,
) -> bool:
    """Send the digest, and record it as sent only if sending succeeded.

    Returns True when an email went out. An empty digest returns False without
    touching the network or the seen store.
    """
    if digest.is_empty:
        logger.info("Nothing new scored above the threshold this week. No email sent.")
        return False

    subject = (
        f"{len(digest.entries)} strong match{'es' if len(digest.entries) != 1 else ''} "
        f"this week" if digest.entries else "New roles worth a look this week"
    )
    sender.send(
        to=to,
        subject=subject,
        html_body=render_html(digest, candidate_name),
        text_body=render_text(digest),
    )
    # Only reached if send() did not raise.
    mark_seen(digest.keys, seen_path)
    logger.info("Digest sent to %s with %d roles.", to, len(digest.keys))
    return True
