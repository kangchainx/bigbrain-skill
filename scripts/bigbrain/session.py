"""Session state: the transcript, per-round artefacts and token accounting.

A session directory holds everything a run produced, so a finished loop can be
audited without re-reading the conversation:

    transcript.json          the whole conversation plus loop state
    round-NN-request.json    the exact payload sent (with a _meta block)
    round-NN-response.json   the raw reply, the parsed reply and usage
    report.json / report.md  written by the reporting step (item 3)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import EXIT_CONFIG, BigbrainError, bigbrain_home_dir

SESSION_DIR_DEFAULT_ROOT = ".bigbrain"
TRANSCRIPT_FILE = "transcript.json"
REQUEST_TEMPLATE = "round-%02d-request.json"
RESPONSE_TEMPLATE = "round-%02d-response.json"
REPAIR_SUFFIX = "-repair"
REPORT_JSON = "report.json"
REPORT_MD = "report.md"

TRANSCRIPT_VERSION = 2

# Loop states recorded in the transcript.
STATE_OPEN = "open"
STATE_DONE = "done"
STATE_BLOCKED = "blocked"
STATE_MAX_ROUNDS = "max-rounds"
STATE_STUCK = "stuck"


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def default_session_root(cwd=None):
    """Where an unqualified session goes: ``<cwd>/.bigbrain``.

    Sessions are workspace state, so they stay next to the code (and are
    gitignored by install.sh), unlike the user-level experience store.
    """
    base = Path(cwd) if cwd else Path(os.getcwd())
    return base / SESSION_DIR_DEFAULT_ROOT


def resolve_session_dir(session=None, create=False, cwd=None):
    if session:
        path = Path(session).expanduser()
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = default_session_root(cwd) / ("session-%s" % stamp)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def require_session_dir(session):
    if not session:
        raise BigbrainError(
            "--session DIR is required (the directory printed by start)", EXIT_CONFIG
        )
    path = Path(session).expanduser()
    if not (path / TRANSCRIPT_FILE).is_file():
        raise BigbrainError(
            "no bigbrain session at %s (expected %s; run start first)"
            % (path, path / TRANSCRIPT_FILE),
            EXIT_CONFIG,
        )
    return path


def sessions_root_for(session_dir):
    """Best-effort guess at the shared parent of a session directory."""
    path = Path(session_dir).expanduser().resolve()
    if path.name.startswith("session-"):
        return path.parent
    return path.parent


# --------------------------------------------------------------------------
# Transcript
# --------------------------------------------------------------------------


def load_transcript(session_dir):
    path = Path(session_dir) / TRANSCRIPT_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BigbrainError("cannot read session transcript %s: %s" % (path, exc), EXIT_CONFIG)
    except ValueError as exc:
        raise BigbrainError("session transcript %s is corrupt: %s" % (path, exc), EXIT_CONFIG)


def new_transcript(task, cfg, cwd=None, reasons=None):
    return {
        "version": TRANSCRIPT_VERSION,
        "task": task,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cwd": str(Path(cwd) if cwd else Path(os.getcwd())),
        "base_url": cfg.get("base_url"),
        "backend": cfg.get("backend", "api"),
        "codex_thread_id": os.environ.get("CODEX_THREAD_ID"),
        "model": cfg.get("model"),
        "max_rounds": cfg.get("max_rounds"),
        "threshold": cfg.get("threshold"),
        "weights": cfg.get("weights"),
        "escalation_reasons": list(reasons or []),
        "rounds": [],
        "messages": [],
        "status": STATE_OPEN,
        # Milestone flow (item 2).
        "milestones": [],
        "acceptance_criteria": [],
        "current_milestone": None,
        "criteria_status": [],
        "milestone_reviews": [],
        # Token accounting (item 3).
        "usage": {"input_tokens": 0, "output_tokens": 0, "calls": 0, "by_kind": {}},
        # Retrospective (item 7) and lessons (items 4/5) hooks.
        "retrospective": None,
        "lessons_saved": 0,
        "escalations": 0,
    }


def save_transcript(session_dir, transcript):
    from .io import write_json
    if (Path(session_dir) / "claude-session.json").exists():
        from .native_session import checkpoint, durable_write, mark_applied
        journal = checkpoint(session_dir, transcript)
        durable_write(Path(session_dir) / TRANSCRIPT_FILE, transcript)
        mark_applied(session_dir, journal)
        return Path(session_dir) / TRANSCRIPT_FILE
    return write_json(Path(session_dir) / TRANSCRIPT_FILE, transcript)


def metadata_path(session_dir):
    return Path(session_dir) / "session.json"


# --------------------------------------------------------------------------
# Round artefacts
# --------------------------------------------------------------------------


def request_path(session_dir, round_number, repair=False):
    name = REQUEST_TEMPLATE % round_number
    if repair:
        name = name.replace(".json", REPAIR_SUFFIX + ".json")
    return Path(session_dir) / name


def response_path(session_dir, round_number, repair=False):
    name = RESPONSE_TEMPLATE % round_number
    if repair:
        name = name.replace(".json", REPAIR_SUFFIX + ".json")
    return Path(session_dir) / name


# --------------------------------------------------------------------------
# Token accounting (item 3)
# --------------------------------------------------------------------------


def record_usage(transcript, usage, kind="round", model=None):
    """Accumulate one API call's token usage into the transcript.

    ``kind`` separates ordinary rounds from the retrospective so the report can
    show where the tokens actually went.  ``usage`` is the dict produced by
    :func:`bigbrain.client.usage_of` -- absent usage counts as a call with zero
    tokens, never as a silent skip, so ``calls`` stays honest.
    """
    usage = usage or {}
    bucket = transcript.setdefault(
        "usage", {"input_tokens": 0, "output_tokens": 0, "calls": 0, "by_kind": {}}
    )
    in_tokens = int(usage.get("input_tokens") or 0)
    out_tokens = int(usage.get("output_tokens") or 0)
    bucket["input_tokens"] = int(bucket.get("input_tokens") or 0) + in_tokens
    bucket["output_tokens"] = int(bucket.get("output_tokens") or 0) + out_tokens
    bucket["calls"] = int(bucket.get("calls") or 0) + 1
    if "cli_cost_usd" in usage:
        bucket["cli_cost_usd"] = bucket.get("cli_cost_usd", 0.0) + usage["cli_cost_usd"]
    if usage.get("cli_cost_missing"):
        bucket["cli_cost_missing"] = True

    per_kind = bucket.setdefault("by_kind", {})
    entry = per_kind.setdefault(kind, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
    entry["input_tokens"] += in_tokens
    entry["output_tokens"] += out_tokens
    entry["calls"] += 1

    if usage.get("present") is False:
        bucket["usage_missing_calls"] = int(bucket.get("usage_missing_calls") or 0) + 1
    for model in (usage.get("models") or []) + ([model] if model else []):
        bucket.setdefault("models", [])
        if model not in bucket["models"]:
            bucket["models"].append(model)
    return bucket


def usage_totals(transcript):
    bucket = transcript.get("usage") or {}
    return {
        "input_tokens": int(bucket.get("input_tokens") or 0),
        "output_tokens": int(bucket.get("output_tokens") or 0),
        "calls": int(bucket.get("calls") or 0),
        "by_kind": dict(bucket.get("by_kind") or {}),
        "usage_missing_calls": int(bucket.get("usage_missing_calls") or 0),
        "models": list(bucket.get("models") or []),
    }


def advisor_calls_estimate(transcript):
    """Number of advisor calls made, including repair attempts."""
    return int((transcript.get("usage") or {}).get("calls") or 0)


#: Rough characters-per-token ratio used to size the executor's own work.  The
#: API never reports the executor's tokens to us -- that model runs outside this
#: skill -- so the savings comparison has to estimate them.
CHARS_PER_TOKEN = 4

#: Tokens a coding agent plausibly spends per escalation round on the work the
#: advisor never sees: reading the files it needs, producing the edit, running
#: the verification command, reading the failure, retrying.  25k is a
#: deliberately conservative figure for a real repository -- large enough that
#: the estimate is not a rounding error, small enough that the savings claim is
#: not inflated by it.  Configurable via BIGBRAIN_EXECUTOR_TOKENS_PER_ROUND.
DEFAULT_EXECUTOR_TOKENS_PER_ROUND = 25000

#: Reported executor output is only the visible tip: the rest is file reads,
#: command output and retries that never reach us.  Applied to reported chars.
EXECUTOR_CONTEXT_MULTIPLIER = 6

#: A coding agent's token mix is dominated by input (file contents, command
#: output) over output (edits, prose).  80/20 is a conventional split.
EXECUTOR_INPUT_SHARE = 0.8


def record_executor_work(transcript, text=None, chars=0, source=None):
    """Accumulate an estimate of the tokens the *executor* spent on this task.

    Called with the executor's own written output each round.  This is an
    estimate, and the report says so; it exists so the "everything to the
    premium model" comparison covers the work, not just the advice.
    """
    if text is not None:
        chars += len(str(text))
    bucket = transcript.setdefault("executor_work", {"chars": 0, "sources": []})
    bucket["chars"] = int(bucket.get("chars") or 0) + max(0, int(chars))
    if source:
        bucket["sources"].append(source)
    return bucket


def executor_token_estimate(transcript, per_round=None):
    """Estimated executor tokens for the whole run.

    Three sources, most explicit first:

    1. ``executor_tokens_override`` -- the caller measured it, believe it.
    2. ``per_round * rounds`` -- the documented per-round allowance, overridable
       via ``BIGBRAIN_EXECUTOR_TOKENS_PER_ROUND``.
    3. reported chars of executor output, scaled up.

    The per-round term is a floor rather than a sum: a round where the executor
    reported nothing still cost it something, so the estimate never collapses to
    zero just because the report files were terse.
    """
    override = transcript.get("executor_tokens_override")
    if isinstance(override, str):
        override = override.strip()
    if override:
        try:
            return max(0, int(override))
        except (TypeError, ValueError):
            pass

    rounds = len(transcript.get("rounds") or [])
    if per_round is None:
        per_round = int(transcript.get("executor_tokens_per_round") or 0) or \
            DEFAULT_EXECUTOR_TOKENS_PER_ROUND
    floor = max(0, int(per_round)) * max(0, rounds)

    bucket = transcript.get("executor_work") or {}
    chars = int(bucket.get("chars") or 0)
    from_chars = int((chars / CHARS_PER_TOKEN) * EXECUTOR_CONTEXT_MULTIPLIER)

    return max(floor, from_chars)


# --------------------------------------------------------------------------
# Session listing (used by `status --all` / reporting)
# --------------------------------------------------------------------------


def list_sessions(root):
    root = Path(root).expanduser()
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if (child / TRANSCRIPT_FILE).is_file():
            out.append(child)
    return out


def is_inside(path, parent):
    """True when ``path`` resolves to ``parent`` or something below it."""
    try:
        path = Path(path).expanduser().resolve()
        parent = Path(parent).expanduser().resolve()
    except OSError:  # pragma: no cover - defensive
        return False
    if path == parent:
        return True
    return parent in path.parents


def user_home_dir(env=None):
    return bigbrain_home_dir(env)


__all__ = [
    "REPORT_JSON",
    "REPORT_MD",
    "SESSION_DIR_DEFAULT_ROOT",
    "STATE_BLOCKED",
    "STATE_DONE",
    "STATE_MAX_ROUNDS",
    "STATE_OPEN",
    "STATE_STUCK",
    "TRANSCRIPT_FILE",
    "TRANSCRIPT_VERSION",
    "advisor_calls_estimate",
    "default_session_root",
    "is_inside",
    "list_sessions",
    "load_transcript",
    "metadata_path",
    "new_transcript",
    "record_usage",
    "request_path",
    "require_session_dir",
    "resolve_session_dir",
    "response_path",
    "save_transcript",
    "usage_totals",
    "user_home_dir",
]
