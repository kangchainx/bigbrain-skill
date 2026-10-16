"""Guard: dualmind never creates or modifies an AGENTS.md.

Lessons live in a user-level experience store and are injected into advisor
requests while the skill is active.  They do **not** belong in a repository's
instruction file, and this skill must never write one -- not the project
``AGENTS.md``, not the global ``~/.codex/AGENTS.md``, not any Claude or Codex
configuration file.  Those files are the user's, they are committed and shared,
and silently editing them would change behaviour long after the session ended.

This module exists so that rule is enforced in one place rather than remembered
in many.  It has no write path at all: it only *recognises* a protected
filename and refuses.  :func:`dualmind.io.write_text` and
:func:`dualmind.io.write_json` call :func:`guard_write` on every write the
package makes, so a future feature that tries to persist lessons into an
instruction file fails loudly instead of succeeding quietly.

There is deliberately no read helper here either: the rule is that no code path
creates, reads-for-write, or modifies these files.  Nothing in dualmind needs
their contents, so nothing is exposed to read them.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import EXIT_CONFIG, DualmindError

# Filenames that belong to the user's agent tooling, never to dualmind.
PROTECTED_FILENAMES = frozenset(
    name.lower()
    for name in (
        "AGENTS.md",
        "AGENTS.MD",
        "AGENTS.Md",
        "CLAUDE.md",
        "CLAUDE.MD",
        "codex.md",
        "codex.toml",
        "config.toml",
        "settings.json",
        "instructions.md",
    )
)

# Directories whose contents are the user's agent configuration.
PROTECTED_DIRNAMES = frozenset(
    name.lower() for name in (".codex", ".claude", ".agents", ".config/codex")
)


def is_protected_path(path):
    """True when ``path`` names an instruction/config file dualmind must not touch."""
    try:
        name = Path(path).name.lower()
    except (TypeError, ValueError):
        return False
    if name not in PROTECTED_FILENAMES:
        return False
    # A file simply *called* AGENTS.md is enough to refuse; being conservative
    # here costs nothing, because dualmind has no legitimate reason to write one
    # anywhere, in any directory.
    return True


def is_inside_protected_dir(path):
    """True when ``path`` sits directly inside a user agent-config directory."""
    try:
        parts = [str(part).lower() for part in Path(path).parts]
    except (TypeError, ValueError):
        return False
    for index, part in enumerate(parts):
        if part in PROTECTED_DIRNAMES and index < len(parts) - 1:
            return True
    return False


def guard_write(path):
    """Raise when a write targets a protected instruction/config file.

    Returns the path unchanged when the write is allowed, so callers can write
    ``path = guard_write(path)``.
    """
    if is_protected_path(path):
        raise DualmindError(
            "refusing to write %s: dualmind never creates or modifies AGENTS.md or any "
            "other agent instruction/config file. Lessons are stored in the user-level "
            "experience directory instead (see references/experience.md)." % path,
            EXIT_CONFIG,
        )
    return path


def audit_for_protected_files(root):
    """List protected filenames found anywhere under ``root`` (read-only scan).

    Used by tests and by ``status --audit`` to prove dualmind left the user's
    instruction files alone.  This only enumerates names; it never opens them.
    """
    found = []
    root = Path(root).expanduser()
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower() in PROTECTED_FILENAMES:
                found.append(str(Path(dirpath) / name))
        # Do not descend into enormous trees we have no business in.
        dirnames[:] = [d for d in dirnames if not d.startswith(".git")]
    return sorted(found)


def protected_fingerprint(paths):
    """sha256 of every protected file that exists, keyed by path.

    Tests compare two snapshots: identical fingerprints before and after a run
    prove dualmind did not touch any instruction file.
    """
    import hashlib

    out = {}
    for raw in paths or []:
        path = Path(raw).expanduser()
        try:
            data = path.read_bytes()
        except OSError:
            continue
        out[str(path)] = hashlib.sha256(data).hexdigest()
    return out


__all__ = [
    "PROTECTED_DIRNAMES",
    "PROTECTED_FILENAMES",
    "audit_for_protected_files",
    "guard_write",
    "is_inside_protected_dir",
    "is_protected_path",
    "protected_fingerprint",
]
