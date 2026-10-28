"""Session status reporting: where a run is, in one screen.

Also carries the audit that proves bigbrain never touched a user instruction
file: :func:`audit_payload` lists the AGENTS.md-shaped files under a root and
their hashes, so a caller can snapshot before and after and compare.
"""

from __future__ import annotations

import time
from pathlib import Path

from .agents_md import audit_for_protected_files, protected_fingerprint
from .session import (
    STATE_BLOCKED,
    STATE_DONE,
    STATE_MAX_ROUNDS,
    list_sessions,
    load_transcript,
    usage_totals,
)
from . import schema, native_session

STATE_LABELS = {
    STATE_DONE: "done",
    STATE_BLOCKED: "blocked",
    STATE_MAX_ROUNDS: "max rounds exhausted",
}


def state_label(state):
    return STATE_LABELS.get(state, state or "open")


def milestone_table(transcript):
    """Per-milestone view: id, title, latest verdict, approval state."""
    reviews = {}
    for review in transcript.get("milestone_reviews") or []:
        reviews[str(review.get("milestone_id"))] = review
    rows = []
    for item in transcript.get("milestones") or []:
        milestone_id = str(item.get("id"))
        review = reviews.get(milestone_id) or {}
        rows.append(
            {
                "id": milestone_id,
                "title": item.get("title") or "",
                "state": item.get("state", "pending"),
                "last_verdict": review.get("verdict"),
                "issues": review.get("issues") or [],
                "steps": len(item.get("steps") or []),
                "criteria": len(item.get("acceptance_criteria") or []),
            }
        )
    return rows


def summary(transcript, session_dir=None):
    rounds = transcript.get("rounds") or []
    last = rounds[-1] if rounds else {}
    totals = usage_totals(transcript)
    criteria_status = transcript.get("criteria_status") or []

    return {
        "session": str(session_dir) if session_dir else None,
        "native": native_session.status(session_dir) if session_dir else None,
        "task": transcript.get("task"),
        "model": transcript.get("model"),
        "base_url": transcript.get("base_url"),
        "status": transcript.get("status"),
        "status_label": state_label(transcript.get("status")),
        "rounds_used": len(rounds),
        "max_rounds": transcript.get("max_rounds"),
        "last_status": last.get("status"),
        "last_verdict": last.get("verdict"),
        "current_milestone": transcript.get("current_milestone"),
        "milestones_used": len(transcript.get("milestones") or []),
        "milestone_reviews": len(transcript.get("milestone_reviews") or []),
        "criteria_met": sum(1 for item in criteria_status if item.get("met")),
        "criteria_total": len(criteria_status)
        or len(transcript.get("acceptance_criteria") or []),
        "lessons_saved": int(transcript.get("lessons_saved") or 0),
        "retrospective": bool(transcript.get("retrospective")),
        "tokens": {
            "input": totals["input_tokens"],
            "output": totals["output_tokens"],
            "calls": totals["calls"],
        },
        "threshold": transcript.get("threshold"),
        "escalation_reasons": transcript.get("escalation_reasons") or [],
        "rounds": rounds,
        "milestones": milestone_table(transcript),
        "artifact_status": schema.is_loop_end(
            {"status": transcript.get("status"), "criteria_status": criteria_status}
        ),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load_summary(session_dir):
    return summary(load_transcript(session_dir), session_dir=session_dir)


def render_text(payload):
    """A compact human rendering of :func:`summary`."""
    lines = [
        "bigbrain session %s" % (payload.get("session") or ""),
        "  task      : %s" % (payload.get("task") or ""),
        "  status    : %s" % payload.get("status_label"),
        "  rounds    : %s of %s" % (payload.get("rounds_used"), payload.get("max_rounds")),
        "  model     : %s" % (payload.get("model") or "(unset)"),
        "  threshold : %s" % payload.get("threshold"),
        "  milestone : %s of %s  (reviews: %s)"
        % (
            payload.get("milestones_used"),
            payload.get("milestones_used"),
            payload.get("milestone_reviews"),
        ),
        "  criteria  : %s of %s met"
        % (payload.get("criteria_met"), payload.get("criteria_total")),
        "  tokens    : %s in / %s out across %s call(s)"
        % (
            payload["tokens"]["input"],
            payload["tokens"]["output"],
            payload["tokens"]["calls"],
        ),
        "  lessons   : %s saved, retrospective %s"
        % (
            payload.get("lessons_saved"),
            "recorded" if payload.get("retrospective") else "not recorded",
        ),
    ]
    if payload.get("escalation_reasons"):
        lines.append("  escalated : %s" % "; ".join(payload["escalation_reasons"]))
    rows = payload.get("milestones") or []
    if rows:
        lines.append("")
        lines.append("  milestones:")
        for row in rows:
            lines.append(
                "    [%-8s] %s %s%s"
                % (
                    row["state"],
                    row["id"],
                    row["title"][:60],
                    "  (last verdict: %s)" % row["last_verdict"] if row["last_verdict"] else "",
                )
            )
    return "\n".join(lines)


def render_all(root):
    """One line per session under ``root``."""
    lines = []
    for session_dir in list_sessions(root):
        try:
            payload = load_summary(session_dir)
        except Exception:  # pragma: no cover - a corrupt session must not break the listing
            lines.append("%s  (unreadable transcript)" % session_dir)
            continue
        lines.append(
            "%-60s %-14s %2s round(s)  %s/%s criteria"
            % (
                session_dir.name,
                payload.get("status_label"),
                payload.get("rounds_used"),
                payload.get("criteria_met"),
                payload.get("criteria_total"),
            )
        )
    return "\n".join(lines)


def audit_payload(root, before=None):
    """Report the protected instruction files under ``root`` and their hashes.

    ``before`` is an optional earlier fingerprint mapping; when supplied, the
    payload says which files changed, which is exactly the check the test suite
    runs to prove bigbrain leaves AGENTS.md alone.
    """
    found = audit_for_protected_files(root)
    after = protected_fingerprint(found)
    payload = {
        "root": str(Path(root).expanduser()),
        "protected_files": found,
        "count": len(found),
        "fingerprint": after,
    }
    if before is not None:
        changed = sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
        payload["changed"] = changed
        payload["unchanged"] = not changed
    return payload


__all__ = [
    "STATE_LABELS",
    "audit_payload",
    "load_summary",
    "milestone_table",
    "render_all",
    "render_text",
    "state_label",
    "summary",
]
