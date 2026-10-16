"""End-of-run reporting: tokens, cost, savings (item 3).

Two artefacts land in the session directory:

    report.json   machine-readable, everything the numbers were derived from
    report.md     the same thing for a human

The savings figure needs an honest baseline.  bigbrain's claim is that only the
*judgement* is escalated: the advisor plans and reviews, while the bulk of the
token volume -- reading files, writing code, running tests -- stays with the
cheaper executor model.  So the comparison is "what if every token in this run
had been billed at the advisor's rate", not "what if the advisor had never
existed".  Everything the estimate rests on is printed alongside it.
"""

from __future__ import annotations

import time
from pathlib import Path

from .config import (
    DEFAULT_PRICE_IN,
    DEFAULT_PRICE_OUT,
    EXIT_CONFIG,
    BigbrainError,
)
from .io import write_json, write_text
from .session import (
    CHARS_PER_TOKEN,
    EXECUTOR_CONTEXT_MULTIPLIER,
    EXECUTOR_INPUT_SHARE,
    REPORT_JSON,
    REPORT_MD,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_MAX_ROUNDS,
    executor_token_estimate,
    load_transcript,
    usage_totals,
)

PER_MTOK = 1_000_000


def price_config(cfg):
    prices = dict(cfg.get("prices") or {})
    prices.setdefault("advisor_in", DEFAULT_PRICE_IN)
    prices.setdefault("advisor_out", DEFAULT_PRICE_OUT)
    prices.setdefault("baseline_in", prices["advisor_in"])
    prices.setdefault("baseline_out", prices["advisor_out"])
    prices.setdefault("executor_in", prices["advisor_in"])
    prices.setdefault("executor_out", prices["advisor_out"])
    return prices


def cost_of(input_tokens, output_tokens, price_in, price_out):
    return (int(input_tokens or 0) / PER_MTOK) * float(price_in or 0.0) + (
        int(output_tokens or 0) / PER_MTOK
    ) * float(price_out or 0.0)


CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.1


def advisor_cost_of(input_total, cache_write, cache_read, output_tokens, price_in, price_out):
    """Advisor cost; ``input_total`` includes the cached portions, which are re-priced."""
    uncached = max(0, int(input_total or 0) - int(cache_write or 0) - int(cache_read or 0))
    return (
        cost_of(uncached, output_tokens, price_in, price_out)
        + cost_of(cache_write, 0, float(price_in or 0.0) * CACHE_WRITE_MULT, 0)
        + cost_of(cache_read, 0, float(price_in or 0.0) * CACHE_READ_MULT, 0)
    )


def build_report(transcript, cfg=None, session_dir=None):
    """Compute the report payload.  Pure: takes a transcript, returns a dict."""
    cfg = cfg or {}
    prices = price_config(cfg)
    totals = usage_totals(transcript)

    advisor_in = totals["input_tokens"]
    advisor_out = totals["output_tokens"]
    usage_bucket = transcript.get("usage") or {}
    cache_write = int(usage_bucket.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage_bucket.get("cache_read_input_tokens") or 0)
    advisor_cost = advisor_cost_of(
        advisor_in, cache_write, cache_read, advisor_out, prices["advisor_in"], prices["advisor_out"]
    )

    # The executor's own work never reaches this API, so its token volume is an
    # estimate (see session.py).  It is split into an input/output mix rather
    # than priced as pure input, because the executor's edits and reports are
    # output-priced and pretending otherwise would flatter the savings figure.
    executor_tokens = executor_token_estimate(
        transcript, per_round=cfg.get("executor_tokens_per_round")
    )
    executor_in = int(executor_tokens * EXECUTOR_INPUT_SHARE)
    executor_out = executor_tokens - executor_in
    executor_cost = cost_of(
        executor_in, executor_out, prices["executor_in"], prices["executor_out"]
    )

    # The comparison: this run cost the executor's spend plus the advisor's
    # spend.  Routing the whole run to the premium model would have cost the
    # same total token volume at the premium rate -- that is the baseline, and
    # the difference is what bigbrain saved.
    total_tokens = advisor_in + advisor_out + executor_tokens
    baseline_cost = cost_of(
        total_tokens * EXECUTOR_INPUT_SHARE,
        total_tokens * (1 - EXECUTOR_INPUT_SHARE),
        prices["baseline_in"],
        prices["baseline_out"],
    )
    actual_cost = advisor_cost + executor_cost
    savings = baseline_cost - actual_cost
    savings_pct = (savings / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

    rounds = transcript.get("rounds") or []
    escalations = int(transcript.get("escalations") or 0)
    if not escalations:
        # Any run that actually consulted the advisor escalated at least once.
        escalations = 1 if rounds else 0

    milestones = transcript.get("milestones") or []
    reviews = transcript.get("milestone_reviews") or []
    criteria_status = transcript.get("criteria_status") or []

    votes = {"approve": 0, "revise": 0, "reject": 0}
    for review in reviews:
        if review.get("verdict") in votes:
            votes[review["verdict"]] += 1

    # When done with all criteria met, mark non-approved milestones as completed_early
    status = transcript.get("status")
    all_criteria_met = criteria_status and all(item.get("met") for item in criteria_status)
    if status == STATE_DONE and all_criteria_met:
        for milestone in milestones:
            if milestone.get("state") != "approved":
                milestone["state"] = "completed_early"

    reasons = []
    for round_entry in rounds:
        verdict = round_entry.get("verdict")
        if verdict in ("revise", "reject"):
            reasons.append("round %s: %s %s" % (round_entry.get("round"), verdict, round_entry.get("milestone_id") or ""))

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session": str(session_dir) if session_dir else None,
        "task": transcript.get("task"),
        "status": transcript.get("status"),
        "model": transcript.get("model"),
        "escalations": escalations,
        "rounds": len(rounds),
        "max_rounds": transcript.get("max_rounds"),
        "threshold": transcript.get("threshold"),
        "escalation_reasons": transcript.get("escalation_reasons") or [],
        "milestones": {
            "total": len(milestones),
            "approved": sum(1 for item in milestones if item.get("state") == "approved"),
            "completed_early": sum(1 for item in milestones if item.get("state") == "completed_early"),
            "reviews": len(reviews),
            "verdicts": votes,
            "list": [
                {"id": item.get("id"), "title": item.get("title"), "state": item.get("state", "pending")}
                for item in milestones
            ],
        },
        "acceptance_criteria": {
            "total": len(criteria_status) or len(transcript.get("acceptance_criteria") or []),
            "met": sum(1 for item in criteria_status if item.get("met")),
            "outstanding": [item.get("criterion") for item in criteria_status if not item.get("met")],
        },
        "tokens": {
            "advisor_input": advisor_in,
            "advisor_output": advisor_out,
            "cache_creation_input_tokens": cache_write,
            "cache_read_input_tokens": cache_read,
            "total": advisor_in + advisor_out,
            "calls": totals["calls"],
            "by_kind": totals["by_kind"],
            "calls_without_usage": totals["usage_missing_calls"],
            "retrospective": totals["by_kind"].get("retrospective", {}),
            # The executor's own volume, estimated -- see session.py.  Without
            # it the baseline would only ever cover the advice, and the savings
            # figure would be meaningless.
            "executor_estimated": executor_tokens,
            "executor_chars": int((transcript.get("executor_work") or {}).get("chars") or 0),
            "all_tokens": total_tokens,
        },
        "pricing": {
            "currency": "USD",
            "per": "million tokens",
            "advisor_in": prices["advisor_in"],
            "advisor_out": prices["advisor_out"],
            "baseline_in": prices["baseline_in"],
            "baseline_out": prices["baseline_out"],
            "executor_in": prices["executor_in"],
            "executor_out": prices["executor_out"],
        },
        "cost": {
            "advisor_usd": round(advisor_cost, 6),
            "executor_usd": round(executor_cost, 6),
            "actual_usd": round(actual_cost, 6),
            "baseline_all_advisor_usd": round(baseline_cost, 6),
            "savings_usd": round(savings, 6),
            "savings_pct": round(savings_pct, 2),
        },
        "lessons_saved": int(transcript.get("lessons_saved") or 0),
        "retrospective": bool(transcript.get("retrospective")),
        "notes": _notes(totals, reasons),
    }


def _notes(totals, reasons):
    notes = []
    if totals["calls"] == 0:
        notes.append("no advisor calls were recorded, so token counts and costs are zero")
    elif totals["usage_missing_calls"]:
        notes.append(
            "%d of %d API calls did not report a usage block; their tokens are counted as zero, "
            "so the cost estimate is a floor" % (totals["usage_missing_calls"], totals["calls"])
        )
    if not totals["by_kind"].get("retrospective"):
        notes.append("no retrospective call was recorded for this session")
    if reasons:
        notes.append("rounds with a non-approving verdict: %s" % "; ".join(reasons))
    return notes


def render_markdown(payload):
    tokens = payload["tokens"]
    cost = payload["cost"]
    milestones = payload["milestones"]
    criteria = payload["acceptance_criteria"]

    lines = [
        "# bigbrain report",
        "",
        "- task: %s" % (payload.get("task") or "(none)"),
        "- session: `%s`" % (payload.get("session") or "(none)"),
        "- final status: **%s**" % (payload.get("status") or "open"),
        "- advisor model: `%s`" % (payload.get("model") or "(unset)"),
        "- generated: %s" % payload.get("generated_at"),
        "",
        "## Escalation",
        "",
        "- escalations: **%d**" % payload["escalations"],
        "- rounds used: **%d** of %s" % (payload["rounds"], payload.get("max_rounds")),
        "- escalation threshold: %s" % payload.get("threshold"),
    ]
    if payload.get("escalation_reasons"):
        lines.append("- reasons: %s" % "; ".join(payload["escalation_reasons"]))
    lines.append("")

    lines += [
        "## Milestones",
        "",
    ]

    # Build milestone summary line
    milestone_parts = ["%d milestones" % milestones["total"]]
    if milestones["approved"] > 0:
        milestone_parts.append("%d approved" % milestones["approved"])
    if milestones["completed_early"] > 0:
        milestone_parts.append("%d completed early" % milestones["completed_early"])
    lines.append("- %s" % ", ".join(milestone_parts))

    lines += [
        "- reviews sent: %d (approve %d / revise %d / reject %d)"
        % (
            milestones["reviews"],
            milestones["verdicts"]["approve"],
            milestones["verdicts"]["revise"],
            milestones["verdicts"]["reject"],
        ),
        "",
    ]
    if milestones["list"]:
        lines.append("| milestone | title | state |")
        lines.append("|-----------|-------|-------|")
        for item in milestones["list"]:
            lines.append("| %s | %s | %s |" % (item["id"], item["title"] or "", item["state"]))
        lines.append("")

    lines += [
        "## Acceptance criteria",
        "",
        "- met: **%d** of %d" % (criteria["met"], criteria["total"]),
    ]
    if criteria["outstanding"]:
        lines.append("- outstanding: %s" % "; ".join(str(item) for item in criteria["outstanding"]))
    lines.append("")

    lines += [
        "## Tokens",
        "",
        "- advisor input: **%s**" % _commas(tokens["advisor_input"]),
        "- cache writes / reads: **%s** / **%s**"
        % (_commas(tokens.get("cache_creation_input_tokens", 0)), _commas(tokens.get("cache_read_input_tokens", 0))),
        "- advisor output: **%s**" % _commas(tokens["advisor_output"]),
        "- advisor total: **%s** across %d call(s)" % (_commas(tokens["total"]), tokens["calls"]),
        "- executor work (estimated): **%s** -- from %s chars of reported output x %s"
        % (_commas(tokens["executor_estimated"]), _commas(tokens["executor_chars"]), EXECUTOR_CONTEXT_MULTIPLIER),
        "- all tokens: **%s**" % _commas(tokens["all_tokens"]),
    ]
    by_kind = tokens.get("by_kind") or {}
    for kind, entry in sorted(by_kind.items()):
        lines.append(
            "- %s: %s in / %s out (%d call(s))"
            % (
                kind,
                _commas(entry.get("input_tokens", 0)),
                _commas(entry.get("output_tokens", 0)),
                entry.get("calls", 0),
            )
        )
    lines.append("")

    pricing = payload["pricing"]
    lines += [
        "## Cost estimate",
        "",
        "Advisor priced at $%s/Mtok in, $%s/Mtok out (`BIGBRAIN_PRICE_IN` / `BIGBRAIN_PRICE_OUT`);"
        " executor at $%s/$%s (`BIGBRAIN_EXECUTOR_PRICE_IN` / `_OUT`); baseline at $%s/$%s."
        % (
            pricing["advisor_in"],
            pricing["advisor_out"],
            pricing["executor_in"],
            pricing["executor_out"],
            pricing["baseline_in"],
            pricing["baseline_out"],
        ),
        "",
        "- advisor spend: **$%.4f** (%s tok)" % (cost["advisor_usd"], _commas(tokens["total"])),
        "- executor spend: $%.4f (%s tok, estimated)"
        % (cost["executor_usd"], _commas(tokens["executor_estimated"])),
        "- actual total: **$%.4f**" % cost["actual_usd"],
        "- everything to the premium model: $%.4f" % cost["baseline_all_advisor_usd"],
        "- estimated savings: **$%.4f** (%.1f%%)" % (cost["savings_usd"], cost["savings_pct"]),
        "",
        "_Baseline: the run's whole token volume -- advisor plus estimated executor work --"
        " billed at the premium in/out rates ($%s/$%s per Mtok). Savings are that baseline"
        " minus what the run actually cost. Token figures come from the API's `usage` fields"
        " where reported and are estimated from reported output where they are not; treat this"
        " as a sizing estimate, not an invoice._" % (pricing["baseline_in"], pricing["baseline_out"]),
        "",
    ]

    lines += [
        "## Learning",
        "",
        "- lessons saved to the user-level experience store: **%d**" % payload["lessons_saved"],
        "- retrospective recorded: %s" % ("yes" if payload["retrospective"] else "no"),
        "",
    ]

    if payload.get("notes"):
        lines.append("## Notes")
        lines.append("")
        for note in payload["notes"]:
            lines.append("- %s" % note)
        lines.append("")
    return "\n".join(lines)


def _commas(number):
    try:
        return "{:,}".format(int(number))
    except (TypeError, ValueError):
        return str(number)


def write_report(session_dir, transcript, cfg=None, progress=None):
    """Write ``report.json`` and ``report.md``, and return the payload."""
    payload = build_report(transcript, cfg=cfg, session_dir=session_dir)
    write_json(Path(session_dir) / REPORT_JSON, payload)
    write_text(Path(session_dir) / REPORT_MD, render_markdown(payload))
    if progress is not None:
        progress.report_written(Path(session_dir) / REPORT_MD)
    return payload


def print_report(payload, stream=None, to_stdout=True):
    """Print the human summary so the executor can relay it.

    The default is stderr, not stdout: a finished run writes exactly one JSON
    object to stdout (see ``loop.emit_final``), and the report is prose.  Callers
    that genuinely want it on stdout (``finish``) pass ``stream=sys.stdout``.
    """
    import sys

    text = render_markdown(payload)
    if stream is not None:
        print(text, file=stream)
    elif to_stdout:
        print(text, file=sys.stderr)
    return text


def report_from_session(session_dir, cfg=None, progress=None):
    transcript = load_transcript(session_dir)
    return write_report(session_dir, transcript, cfg=cfg, progress=progress)


def state_label(transcript):
    state = transcript.get("status")
    return {
        STATE_DONE: "done",
        STATE_BLOCKED: "blocked",
        STATE_MAX_ROUNDS: "max rounds",
    }.get(state, state or "open")


def ensure_reportable(transcript):
    """Guard used by `finish` so a report is never written from a broken session."""
    if not isinstance(transcript, dict) or "rounds" not in transcript:
        raise BigbrainError("session transcript is not usable for a report", EXIT_CONFIG)
    return transcript


__all__ = [
    "build_report",
    "cost_of",
    "ensure_reportable",
    "price_config",
    "print_report",
    "render_markdown",
    "report_from_session",
    "state_label",
    "write_report",
]
