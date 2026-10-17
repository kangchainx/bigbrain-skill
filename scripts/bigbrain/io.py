"""Small file helpers shared across the package.

Kept deliberately tiny so nothing here can grow into a second configuration
system.  All writes are atomic-ish: write to a sibling temp file, then replace.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import DEFAULT_MAX_CONTEXT_CHARS, EXIT_CONFIG, BigbrainError


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def read_text_file(path, cap=None):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BigbrainError("cannot read %s: %s" % (path, exc), EXIT_CONFIG)
    if cap is not None and len(text) > cap:
        dropped = len(text) - cap
        text = text[:cap] + "\n... [truncated: %d characters omitted] ..." % dropped
    return text


def read_json_file(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def append_jsonl(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def read_context_files(paths, cap=DEFAULT_MAX_CONTEXT_CHARS):
    """Read context files into one block, truncating to a total character cap.

    Returns ``(block, notes)``.  Truncation is always announced in the block
    itself and in notes so the advisor knows material is missing.  An unreadable
    file is a note, never a failure -- an advisory context file that vanished
    should not abort a round.
    """
    parts = []
    notes = []
    used = 0
    for raw_path in paths or []:
        path = Path(raw_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append("could not read %s: %s" % (raw_path, exc))
            continue
        remaining = cap - used
        if remaining <= 0:
            notes.append("omitted %s: context budget of %d chars exhausted" % (raw_path, cap))
            continue
        if len(text) > remaining:
            dropped = len(text) - remaining
            text = text[:remaining] + "\n... [truncated: %d characters omitted] ..." % dropped
            notes.append("truncated %s (%d chars omitted)" % (raw_path, dropped))
        used += len(text)
        parts.append("--- BEGIN FILE: %s ---\n%s\n--- END FILE: %s ---" % (raw_path, text, raw_path))
    return "\n\n".join(parts), notes


def eprint(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


class Progress:
    """Emitter for the ``[Bigbrain] ...`` progress lines (item 6).

    Every step prints one line to stderr so a human watching the terminal can
    see what the loop is doing without reading the session JSON.  A progress
    line must never carry a secret -- callers pass model and host separately,
    and :meth:`model_selected` deliberately takes only the host, never a URL
    that might embed credentials.
    """

    PREFIX = "[Bigbrain]"

    def __init__(self, stream=None, enabled=True):
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled

    def __call__(self, message):
        self.line(message)

    def line(self, message):
        if not self.enabled:
            return
        print("%s %s" % (self.PREFIX, message), file=self.stream, flush=True)

    # -- named events used across the package --------------------------------
    def score(self, result):
        if result["signals"]["user_request"]:
            self.line("user requested the advisor -> escalate (score %.2f)" % result["score"])
            return
        self.line(
            "evaluating escalation score %.2f %s %.2f -> %s"
            % (
                result["score"],
                ">" if result["decision"] == "escalate" else "<=",
                result["threshold"],
                result["decision"],
            )
        )

    def starting_advisor(self, task=""):
        suffix = " for %r" % task if task else ""
        self.line("starting advisor%s" % suffix)

    def model_selected(self, model, host):
        """Host only -- never a full URL, which can carry userinfo or a token."""
        self.line("selected model %s via %s" % (model, host or "(unset)"))

    def round(self, number, maximum):
        self.line("round %d/%d" % (number, maximum))

    def milestone_sent(self, index, total, milestone_id=""):
        suffix = " (%s)" % milestone_id if milestone_id else ""
        self.line("milestone %d/%d sent for review%s" % (index, total, suffix))

    def verdict(self, verdict, milestone_id=""):
        suffix = " for milestone %s" % milestone_id if milestone_id else ""
        self.line("verdict: %s%s" % (verdict, suffix))

    def lessons_saved(self, count):
        self.line("lessons saved: %d" % count)

    def retrospective(self, state):
        self.line("retrospective (%s): requesting a process review" % state)

    def report_written(self, path):
        self.line("report written: %s" % path)

    def session_opened(self, path):
        self.line("session %s" % path)
