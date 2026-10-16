#!/usr/bin/env python3
"""Validate bigbrain configuration and prove the endpoint actually answers.

Thin wrapper -- all logic lives in ``bigbrain/check_config.py``.  Kept at this
path because every document, the skill instructions and the test suite refer to
``scripts/check_config.py``.

Checks presence and format of every configuration value, then performs one real
minimal Messages API call (max_tokens=16, prompt "ping").

Exit codes:
  0 OK
  1 unexpected internal error
  2 missing or malformed configuration
  3 network / DNS / timeout
  4 authentication failure (401/403)
  5 model not found (404)
  6 other HTTP error or unparseable response

Usage:
  check_config.py [--json] [--no-call] [--timeout SECONDS]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bigbrain.check_config import main  # noqa: E402  (path setup must come first)

if __name__ == "__main__":
    sys.exit(main())
