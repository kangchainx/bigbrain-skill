#!/usr/bin/env python3
"""bigbrain command line -- the entry point the skill calls.

This file is deliberately thin: it only makes the ``bigbrain`` package
importable and hands over.  All logic lives in ``bigbrain/cli.py``.

    score    compute the escalation score and decide whether to escalate
    start    open a session; ask for the plan, milestones and criteria
    report   send a milestone result for review
    stuck    re-escalate the current milestone with the failure details
    finish   write report.md/report.json (retrospective runs automatically)
    status   print session state, or audit for AGENTS.md-shaped files
    lessons  the user-level experience store: list / add / prune / export
    setup    interactive wizard that writes ~/.bigbrain/config.json

Exit codes are the loop control; run with --help for the table.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bigbrain import cli  # noqa: E402  (path setup must come first)

if __name__ == "__main__":
    sys.exit(cli.run())
