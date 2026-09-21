"""Shared test configuration.

Every test runs inside its own temporary working directory. The stores under
data/ are addressed by relative paths, so this makes it impossible for any
test, present or future, to read or write the real records of what has been
sent, recommended or learned.

This was added after the digest tests were found writing a fabricated
recommendation into the real data/recommendations.json, where the outcome
monitor would eventually have learned from it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
