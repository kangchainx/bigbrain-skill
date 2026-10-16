"""dualmind -- escalate complex coding work to an Opus advisor.

Python 3 standard library only.  Nothing here phones home, pushes, publishes or
fetches anything beyond the advisor API the user configured.

Module map
----------
config      environment / config.json / config.env loading, constants, errors
client      the Anthropic-compatible Messages API client (urllib)
schema      the advisor JSON contract: extraction, validation, normalisation
scoring     auto-escalation scoring: signals -> 0..1 score -> decision
session     the transcript, per-round artefacts, token accounting
loop        one round in, one decision out; milestones, completion, retrospective
experience  the user-level lesson store: merge, prune, rank, render
agents_md   the guard that refuses to touch any AGENTS.md or agent config
report      end-of-run tokens, cost estimate and savings
status      session state rendering and the protected-file audit
io          small file helpers, context loading, the [DualMind] progress lines
cli         the command line

Typical use from an entry script::

    from dualmind import cli
    raise SystemExit(cli.run())
"""

from __future__ import annotations

__version__ = "2.0.0"

__all__ = [
    "agents_md",
    "cli",
    "client",
    "config",
    "experience",
    "io",
    "loop",
    "report",
    "schema",
    "scoring",
    "session",
    "status",
    "__version__",
]
