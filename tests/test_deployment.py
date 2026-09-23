"""Tests for deployment: where state lives, and the weekly job's guards.

The guards matter most. A scheduled job that exits cleanly on a week where no
digest arrived is worse than one that fails loudly, because nobody is watching
it run.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import paths
import run_weekly


def test_state_defaults_to_the_project_folder(monkeypatch):
    """Local development must keep working exactly as before deployment."""
    monkeypatch.delenv("JOBFIT_STATE_DIR", raising=False)
    assert paths.state_dir() == Path(".")


def test_state_directory_can_be_redirected(monkeypatch, tmp_path):
    """The scheduled job points this at the private state repository."""
    monkeypatch.setenv("JOBFIT_STATE_DIR", str(tmp_path))
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.CV_PATH == tmp_path / "cv.yml"
        assert reloaded.OUTCOMES_PATH == tmp_path / "data" / "outcomes.json"
        assert reloaded.SEEN_PATH.parent == tmp_path / "data"
    finally:
        monkeypatch.delenv("JOBFIT_STATE_DIR", raising=False)
        importlib.reload(paths)


def test_every_personal_file_lives_under_the_state_directory():
    """Anything left outside it would be committed to the public repository."""
    personal = [paths.CV_PATH, paths.SEEN_PATH, paths.RECOMMENDATIONS_PATH,
                paths.OUTCOMES_PATH, paths.WEIGHTS_PATH, paths.HISTORY_PATH]
    for path in personal:
        assert paths.STATE_DIR in path.parents or path.parent == paths.STATE_DIR


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["run_weekly.py", *argv])
    return run_weekly.main()


def test_a_missing_cv_fails_the_run(monkeypatch, tmp_path):
    monkeypatch.setattr(run_weekly, "CV_PATH", tmp_path / "absent.yml")
    assert _run(monkeypatch, ["--preview"]) == 1


def test_missing_email_settings_fail_before_any_work(monkeypatch, tmp_path):
    """Fail at the start, not after four hundred API calls."""
    cv = tmp_path / "cv.yml"
    cv.write_text("name: Test\n", encoding="utf-8")
    monkeypatch.setattr(run_weekly, "CV_PATH", cv)
    monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    called = []
    monkeypatch.setattr(run_weekly, "run_ingestion", lambda **_: called.append(1))

    assert _run(monkeypatch, []) == 1
    assert called == []


def test_no_postings_fails_the_run_rather_than_passing_silently(monkeypatch, tmp_path):
    """If both job boards are down the digest would be empty and quietly not
    sent, leaving a green run on a week with no email. That must fail."""
    cv = tmp_path / "cv.yml"
    cv.write_text("name: Test\n", encoding="utf-8")
    monkeypatch.setattr(run_weekly, "CV_PATH", cv)
    monkeypatch.setattr(run_weekly.Settings, "from_env",
                        classmethod(lambda cls: SimpleNamespace(
                            reed=None, adzuna=None, search_queries=["x"], search_location="London",
                            wider_sweep=False, wider_sweep_limit=20)))
    monkeypatch.setattr(run_weekly.CV, "from_file", classmethod(lambda cls, _: SimpleNamespace(name="T")))
    monkeypatch.setattr(run_weekly, "ReedClient", lambda *_a, **_k: None)
    monkeypatch.setattr(run_weekly, "AdzunaClient", lambda *_a, **_k: None)
    monkeypatch.setattr(run_weekly, "run_ingestion",
                        lambda **_: SimpleNamespace(canonical=[]))

    assert _run(monkeypatch, ["--preview"]) == 1


@pytest.mark.parametrize("provider, cls_name", [("resend", "ResendSender"),
                                                 ("sendgrid", "SendGridSender")])
def test_the_configured_provider_is_used(monkeypatch, provider, cls_name):
    monkeypatch.setenv("EMAIL_PROVIDER", provider)
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.x")
    monkeypatch.setenv("DIGEST_FROM_EMAIL", "from@example.com")

    assert type(run_weekly._sender()).__name__ == cls_name


# ---------------------------------------------------------------------------
# The wider sweep must never reach the digest
# ---------------------------------------------------------------------------


def test_the_digest_only_ever_searches_the_primary_field():
    """The weekly email stays as narrow as it has always been. Other fields
    exist for the public site alone."""
    from agents.domains import DOMAINS, PRIMARY_DOMAIN
    from config import Settings

    settings = Settings(adzuna=None, reed=None)

    assert settings.search_queries == DOMAINS[PRIMARY_DOMAIN].queries
    for domain in DOMAINS.values():
        if domain.id == PRIMARY_DOMAIN:
            continue
        for query in domain.queries:
            assert query not in settings.search_queries


def test_the_wider_sweep_is_shallower_than_the_primary_one():
    """It exists to populate the site, not to be complete, and it multiplies
    the per posting detail calls."""
    from config import Settings

    settings = Settings(adzuna=None, reed=None)
    assert settings.wider_sweep_limit < 50
