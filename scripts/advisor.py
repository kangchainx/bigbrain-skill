#!/usr/bin/env python3
"""bigbrain advisor loop -- one call per round, driven by the executor (Codex).

Thin wrapper -- all logic lives in ``bigbrain/cli.py``.  Kept at this path
because older documents and sessions refer to ``scripts/advisor.py``; the
supported entry point is now ``scripts/bigbrain_cli.py``, which adds ``score``,
``stuck``, ``finish`` and ``lessons``.  This wrapper accepts the same arguments
and is exactly equivalent for ``start`` / ``report`` / ``status``.

Usage:
  advisor.py [--mock FILE] [--dry-run] start  --task TEXT [--context-file F ...]
  advisor.py report --session DIR --result-file F
  advisor.py status --session DIR

Run ``advisor.py --help`` for the full argument list.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bigbrain import cli  # noqa: E402  (path setup must come first)

if __name__ == "__main__":
    sys.exit(cli.run())
