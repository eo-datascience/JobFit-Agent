"""Where the system keeps its memory.

Everything that persists between runs lives under one state directory: the CV,
the record of roles already sent, what was recommended, application outcomes,
skill history and any learned weights.

Keeping it in one place is what makes the scheduled deployment possible. The
public repository holds code only. A separate private repository holds this
directory, so personal data such as where the candidate applied and how each
application went is never published. The scheduled job checks out both, points
JOBFIT_STATE_DIR at the private one, and commits changes back afterwards. The
candidate's own machine points at a local clone of the same private repository,
so outcomes recorded locally are visible to the next scheduled run.

When JOBFIT_STATE_DIR is unset, state lives in the project folder, which keeps
local development working exactly as it did before deployment existed.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Loaded here, not only in the runners, because the path constants below are
# evaluated at import time. load_dotenv never overrides a variable that is
# already set, so values supplied by the scheduled job still take precedence.
load_dotenv()


def state_dir() -> Path:
    return Path(os.environ.get("JOBFIT_STATE_DIR", ".")).expanduser()


STATE_DIR = state_dir()
DATA_DIR = STATE_DIR / "data"

CV_PATH = STATE_DIR / "cv.yml"
SEEN_PATH = DATA_DIR / "sent_postings.json"
RECOMMENDATIONS_PATH = DATA_DIR / "recommendations.json"
OUTCOMES_PATH = DATA_DIR / "outcomes.json"
WEIGHTS_PATH = DATA_DIR / "weights.json"
HISTORY_PATH = DATA_DIR / "skill_history.json"
