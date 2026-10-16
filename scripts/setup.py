#!/usr/bin/env python3
"""Interactive setup wizard: detect, ask, validate, then write ~/.bigbrain/config.json.

Thin wrapper -- all logic lives in ``bigbrain/setup_wizard.py``.  Equivalent to
``bigbrain_cli.py setup``.

Usage:
  setup.py [--timeout SECONDS]

Exit codes:
  0 configuration saved
  1 aborted (nothing saved)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bigbrain import cli  # noqa: E402  (path setup must come first)

if __name__ == "__main__":
    sys.exit(cli.run(["setup"] + sys.argv[1:]))
