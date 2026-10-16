"""The bigbrain command line.

One entry point, several verbs.  The verbs split into three groups:

*decide*   ``score`` -- should this task be escalated at all? (item 1)
*loop*     ``start`` / ``report`` / ``stuck`` / ``finish`` / ``status``
*learn*    ``lessons`` -- the user-level experience store (item 4)

Exit codes are the control signal for the loop, and they are documented in
``--help`` and in SKILL.md.  Every verb prints ``[Bigbrain] ...`` progress lines
to stderr so a human can follow along without reading the session JSON (item 6).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import experience, loop, report, schema, scoring, session
from . import status as status_mod
from .config import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MODEL,
    EXIT_BAD_JSON,
    EXIT_BLOCKED,
    EXIT_CONFIG,
    EXIT_MAX_ROUNDS,
    EXIT_OK,
    BigbrainError,
    config_problems,
    load_config,
    mask_secret,
    parse_weights,
    setup_command,
)
from .io import Progress, eprint, read_context_files
from .session import (
    STATE_DONE,
    require_session_dir,
    resolve_session_dir,
)

PROG = "bigbrain"

DESCRIPTION = """\
Bigbrain: escalate complex coding work to an Opus advisor that plans, reviews
and keeps pushing until the acceptance criteria are actually met.

Exit codes (read these first):
   0   continue -- act on the printed advisor JSON
   0   DONE     -- status=done and every acceptance criterion is met; stop
  10   blocked  -- blocked_reason on stderr
  11   round budget exhausted
  12   advisor returned invalid JSON, even after one repair attempt
   2   configuration problem
   3   network / timeout
   4   auth failure
   5   model not found
   6   other HTTP error / unusable response
"""


# --------------------------------------------------------------------------
# Progress plumbing
# --------------------------------------------------------------------------


def make_progress(args):
    return Progress(enabled=not getattr(args, "quiet", False))


def config_or_fail(cfg):
    problems = config_problems(cfg)
    if problems:
        for problem in problems:
            eprint("%s: configuration error: %s" % (PROG, problem))
        eprint("%s: to configure Bigbrain, run the setup wizard:" % PROG)
        eprint("%s:   %s" % (PROG, setup_command()))
        eprint("%s: see references/config.md; run scripts/check_config.py to diagnose" % PROG)
        return False
    return True


def host_of(cfg):
    """Just the host, for the progress line -- never the full URL."""
    base = cfg.get("base_url") or ""
    match = __import__("re").match(r"^https?://([^/]+)", base)
    return match.group(1) if match else base


def banner(progress, cfg, task=""):
    progress.starting_advisor(task)
    progress.model_selected(cfg.get("model") or DEFAULT_MODEL, host_of(cfg))


# --------------------------------------------------------------------------
# score (item 1)
# --------------------------------------------------------------------------


def cmd_score(args, cfg, progress):
    if args.files_changed is not None and args.files_estimated is not None:
        raise BigbrainError(
            "pass either --files-changed or --files-estimated, not both", EXIT_CONFIG
        )
    files = args.files_changed if args.files_changed is not None else args.files_estimated

    threshold = args.threshold if args.threshold is not None else cfg.get("threshold")
    weights = args.weights if args.weights is not None else cfg.get("weights")
    if isinstance(weights, str):
        problems = []
        weights = parse_weights(weights, problems, "--weights")
        for problem in problems:
            eprint("%s: %s" % (PROG, problem))
        if problems:
            raise BigbrainError("--weights could not be parsed", EXIT_CONFIG)

    result = scoring.score_task(
        files=files,
        ambiguity=args.ambiguity,
        consecutive_failures=args.consecutive_failures,
        high_risk=args.high_risk,
        user_request=args.user_request,
        weights=weights,
        threshold=threshold,
    )
    progress.score(result)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return EXIT_OK

    # The stderr progress line above is the [Bigbrain] banner.  Stdout carries
    # the result itself, in a different shape, so a plain `score` never prints
    # the same sentence twice.
    if args.explain:
        print(scoring.explain(result, include_banner=False))
    else:
        print("decision: %s" % result["decision"])
        print("score   : %.2f (threshold %.2f)" % (result["score"], result["threshold"]))
        if result["reasons"]:
            print("signals : %s" % "; ".join(result["reasons"]))
    return EXIT_OK


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


def cmd_status(args, cfg, progress):
    if args.audit:
        payload = status_mod.audit_payload(args.audit)
        print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else
              "protected instruction files under %s: %d\n%s" % (
                  payload["root"],
                  payload["count"],
                  "\n".join("  %s  %s" % (digest[:12], path) for path, digest in sorted(payload["fingerprint"].items()))
                  or "  (none)",
              ))
        return EXIT_OK

    if args.all:
        root = args.root or os.getcwd()
        text = status_mod.render_all(Path(root) / ".bigbrain")
        print(text or "no sessions under %s" % (Path(root) / ".bigbrain"))
        return EXIT_OK

    session_dir = require_session_dir(args.session)
    payload = status_mod.load_summary(session_dir)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(status_mod.render_text(payload))
    return EXIT_OK


# --------------------------------------------------------------------------
# lessons (item 4)
# --------------------------------------------------------------------------


def _store(args, create=False):
    return experience.resolve_store(create=create)


def cmd_lessons(args, cfg, progress):
    action = args.lessons_command or "list"

    if action == "list":
        store = _store(args)
        lessons = experience.load_lessons(store)
        if args.prune:
            lessons, dropped = experience.prune_lessons(lessons, cap=args.cap or cfg["lesson_cap"])
            experience.save_lessons(store, lessons)
            progress.line("pruned %d lesson(s)" % len(dropped))
        ranked = experience.select_lessons(lessons, limit=args.limit, scope=args.scope)
        if args.json:
            print(json.dumps(
                {"store": str(store), "total": len(lessons), "shown": len(ranked), "lessons": ranked},
                indent=2, ensure_ascii=False,
            ))
        else:
            print("store: %s" % store)
            print("total: %d  shown: %d" % (len(lessons), len(ranked)))
            for item in ranked:
                print(
                    "  [%s %.2f] %s"
                    % (item.get("kind", "workflow")[:11], float(item.get("confidence") or 0), item.get("text"))
                )
            if not ranked:
                print("  (no lessons)")
        return EXIT_OK

    if action == "add":
        store = _store(args, create=True)
        text = args.text
        if args.from_file:
            text = Path(args.from_file).read_text(encoding="utf-8", errors="replace")
        if not text or not text.strip():
            raise BigbrainError("lessons add requires TEXT or --from-file FILE", EXIT_CONFIG)
        lesson = experience.make_lesson(
            text, kind=args.kind, scope=args.scope, confidence=args.confidence,
            session=args.session,
        )
        summary = experience.add_lessons(store, [lesson], cap=cfg["lesson_cap"])
        progress.lessons_saved(summary["added"] + summary["merged"])
        if args.json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            print(
                "store: %s\nadded: %d  merged: %d  total: %d"
                % (store, summary["added"], summary["merged"], summary["total"])
            )
        return EXIT_OK

    if action == "prune":
        store = _store(args)
        lessons = experience.load_lessons(store)
        cap = args.cap or cfg["lesson_cap"]
        kept, dropped = experience.prune_lessons(lessons, cap=cap)
        experience.save_lessons(store, kept)
        progress.line("pruned %d lesson(s), %d kept (cap %d)" % (len(dropped), len(kept), cap))
        if args.json:
            print(json.dumps({"kept": len(kept), "dropped": len(dropped), "cap": cap}, indent=2))
        else:
            print("pruned %d of %d (cap %d, %d kept)" % (len(dropped), len(lessons), cap, len(kept)))
        return EXIT_OK

    if action == "export":
        store = _store(args)
        lessons = experience.select_lessons(experience.load_lessons(store), limit=args.limit)
        target = args.out
        text = experience.render_markdown(lessons)
        if target:
            from .io import write_text

            write_text(Path(target).expanduser(), text)
            progress.line("exported %d lesson(s) to %s" % (len(lessons), target))
            print("exported %d lesson(s) to %s" % (len(lessons), target))
        else:
            print(text)
        return EXIT_OK

    raise BigbrainError("unknown lessons subcommand %r" % action, EXIT_CONFIG)  # pragma: no cover


def _mock_entries(cfg, args):
    path = getattr(args, "mock", None) or cfg.get("mock_path")
    if not path:
        return None
    return loop.load_mock_script(path)


def _inject_lessons(transcript, cfg, progress):
    """Attach the top lessons to the transcript for prompt injection (item 5).

    This is the *only* channel lessons reach the advisor: an appendix on the
    system prompt, built fresh each round.  They are never written to any
    AGENTS.md or any editor/agent configuration file.
    """
    try:
        store = experience.resolve_store()
        lessons = experience.select_lessons(experience.load_lessons(store), limit=cfg["lesson_inject"])
    except BigbrainError as exc:
        eprint("%s: lessons not loaded: %s" % (PROG, exc))
        lessons = []
    except OSError as exc:  # pragma: no cover - defensive
        eprint("%s: lessons not loaded: %s" % (PROG, exc))
        lessons = []
    transcript["_injected_lessons"] = lessons
    if lessons:
        progress.line("injecting %d lesson(s) into the advisor prompt" % len(lessons))
    return lessons


def _save_reply_lessons(transcript, normalised, cfg, progress):
    """Persist any ``lessons[]`` the advisor returned (item 4)."""
    lessons = normalised.get("lessons") or []
    if not lessons:
        return 0
    try:
        store = experience.resolve_store(create=True)
    except BigbrainError as exc:
        eprint("%s: lessons not saved: %s" % (PROG, exc))
        return 0
    records = [
        experience.make_lesson(
            item.get("text"),
            kind=item.get("kind", "workflow"),
            scope=item.get("scope", "global"),
            confidence=item.get("confidence", 0.5),
            session=transcript.get("_session"),
        )
        for item in lessons
        if item.get("text")
    ]
    summary = experience.add_lessons(store, records, cap=cfg["lesson_cap"])
    saved = summary["added"] + summary["merged"]
    transcript["lessons_saved"] = int(transcript.get("lessons_saved") or 0) + saved
    progress.lessons_saved(saved)
    return saved


def _close_out(session_dir, transcript, cfg, args, progress, mock_entries, mock_index):
    """Retrospective + lessons + report, once the loop is terminal (items 3, 7).

    Runs without prompting the user.  A failure in any single step is reported
    and does not change the loop's exit code: the work is already done, and a
    missing postscript is not a reason to call the run failed.

    Everything human-readable goes to **stderr** -- the report markdown included
    -- because stdout belongs to the one final JSON object (item 4).  Returns
    ``(report_path, retrospective_metadata)`` so that object can point at both.
    """
    retrospective_metadata = None
    if getattr(args, "no_retrospective", False):
        transcript["retrospective_skipped"] = "disabled with --no-retrospective"
    else:
        normalised, mock_index = loop.run_retrospective(
            session_dir, transcript, cfg, mock_entries=mock_entries,
            mock_index=mock_index, progress=progress,
        )
        if normalised is not None:
            lessons_saved = _save_reply_lessons(transcript, normalised, cfg, progress)
            retrospective_metadata = {"recorded": True, "lessons_saved": lessons_saved}

    from .session import save_transcript

    save_transcript(session_dir, transcript)

    payload = report.write_report(session_dir, transcript, cfg=cfg, progress=progress)
    eprint("")
    report.print_report(payload, stream=sys.stderr)
    return str(Path(session_dir) / "report.json"), retrospective_metadata


def _terminal(code):
    return code in (EXIT_BLOCKED, EXIT_MAX_ROUNDS)


# --------------------------------------------------------------------------
# start / report / stuck
# --------------------------------------------------------------------------


def _score_and_report(args, cfg, progress):
    """Score the task and print the banner.  Returns the result dict, or None.

    Scoring only happens when the caller actually supplied signals.  Running
    ``start`` with no signals is itself an escalation decision -- the caller
    already looked at the task and chose to escalate -- so it is not second
    guessed.  When signals *are* given, a below-threshold score refuses, because
    at that point the numbers were supplied and they disagree with the call.
    """
    if args.no_score:
        return None

    supplied = any(
        [
            args.files_estimated is not None,
            args.ambiguity,
            args.consecutive_failures,
            args.high_risk,
            args.user_request,
        ]
    )
    if not supplied:
        return None

    result = scoring.score_task(
        files=args.files_estimated,
        ambiguity=args.ambiguity,
        consecutive_failures=args.consecutive_failures,
        high_risk=args.high_risk,
        user_request=args.user_request,
        weights=cfg.get("weights"),
        threshold=cfg.get("threshold"),
    )
    progress.score(result)
    if result["decision"] == "stay_local" and not args.force and not args.user_request:
        eprint(
            "%s: score %.2f does not exceed the threshold %.2f -- on these signals this task "
            "does not need the advisor. Do it locally, or pass --force to escalate anyway."
            % (PROG, result["score"], result["threshold"])
        )
        raise BigbrainError(
            "escalation score below threshold", EXIT_CONFIG, score=result["score"]
        )
    return result


def cmd_start(args, cfg, progress):
    if not args.task or not args.task.strip():
        raise BigbrainError("start requires --task TEXT", EXIT_CONFIG)

    # A dry run must leave no trace: it prints the payload and writes nothing,
    # including the session directory itself.  Checked before it is created.
    if not args.dry_run:
        session_dir = resolve_session_dir(args.session, create=True)
    else:
        session_dir = resolve_session_dir(args.session, create=False)
    transcript_path = session_dir / "transcript.json"
    if transcript_path.is_file() and not args.force:
        raise BigbrainError(
            "session %s already exists; pass a new --session DIR or --force to reuse it" % session_dir,
            EXIT_CONFIG,
        )

    result = _score_and_report(args, cfg, progress)
    if result is None and not args.no_score and not args.force:
        pass  # --no-score with no --force is allowed: the caller opted out.

    transcript = session.new_transcript(
        args.task.strip(), cfg, reasons=(result or {}).get("reasons")
    )
    transcript["escalations"] = 1
    transcript["_session"] = str(session_dir)
    if result:
        transcript["escalation_score"] = result["score"]

    context_block, notes = read_context_files(args.context_file, cap=cfg["max_context_chars"])
    for note in notes:
        eprint("%s: context note: %s" % (PROG, note))

    _inject_lessons(transcript, cfg, progress)

    parts = ["# TASK\n%s" % transcript["task"]]
    if context_block:
        parts.append("# CONTEXT FILES\n%s" % context_block)
    parts.append(
        "# EXECUTOR REQUEST\n"
        "This is round 1. Produce the plan: global acceptance criteria, then milestones -- "
        "each with its own steps and acceptance criteria -- plus any blocking questions the "
        "repository can answer. Exactly one JSON object, no prose."
    )
    user_content = "\n\n".join(parts)

    banner(progress, cfg, transcript["task"])
    mock_entries = _mock_entries(cfg, args)
    normalised, _raw, meta, _index = loop.run_round(
        session_dir, transcript, user_content, cfg,
        mock_entries=mock_entries, mock_index=0, dry_run=args.dry_run, progress=progress,
    )

    if args.dry_run:
        payload = meta["payload"]
        print(json.dumps({"dry_run": True, "round": 1, "request": payload}, indent=2, ensure_ascii=False))
        eprint("%s: dry run -- nothing sent, session not written at %s" % (PROG, session_dir))
        return EXIT_OK

    loop.absorb_reply(transcript, normalised, progress)
    _save_reply_lessons(transcript, normalised, cfg, progress)
    code = loop.finish(session_dir, transcript, normalised, progress=progress)
    report_path, retrospective = None, None
    if loop.loop_ended(session_dir, transcript, normalised, progress):
        report_path, retrospective = _close_out(
            session_dir, transcript, cfg, args, progress, mock_entries, _index
        )
    # Exactly one JSON object on stdout, after every other writer has finished.
    loop.emit_final(normalised, report_path=report_path, retrospective=retrospective)
    return code


def cmd_report(args, cfg, progress):
    session_dir = require_session_dir(args.session)
    transcript = session.load_transcript(session_dir)
    if transcript.get("status") in (STATE_DONE, "blocked", "max-rounds") and not args.force:
        raise BigbrainError(
            "session %s already finished with status=%s; pass --force to add another round"
            % (session_dir, transcript.get("status")),
            EXIT_CONFIG,
        )
    if not args.result_file:
        raise BigbrainError("report requires --result-file FILE", EXIT_CONFIG)

    result_text = Path(args.result_file).read_text(encoding="utf-8", errors="replace")
    session.record_executor_work(
        transcript, text=result_text, source="round-%d-report" % (len(transcript["rounds"]) + 1)
    )
    context_block, notes = read_context_files(args.context_file, cap=cfg["max_context_chars"])
    if context_block:
        # Context the executor gathered and forwarded is executor work too.
        session.record_executor_work(transcript, text=context_block, source="round-%d-context"
                                     % (len(transcript["rounds"]) + 1))
    for note in notes:
        eprint("%s: context note: %s" % (PROG, note))

    transcript["_session"] = str(session_dir)
    _inject_lessons(transcript, cfg, progress)

    milestones = transcript.get("milestones") or []
    # One resolver for the progress line and the prompt body, so the milestone
    # announced is by construction the milestone reviewed.  It falls back to the
    # first unapproved milestone in plan order when the advisor left
    # current_milestone null (see loop.resolve_milestone).
    current_id, index, total = loop.resolve_milestone(transcript, requested=args.milestone)
    if total and index:
        progress.milestone_sent(index, total, current_id)

    parts = ["# EXECUTOR REPORT (round %d complete)" % (len(transcript["rounds"]) + 1)]
    if total and index:
        milestone = schema.find_milestone({"milestones": milestones}, current_id) or {}
        parts.append(
            "# MILESTONE UNDER REVIEW\n"
            "milestone %s of %s -- id=%s title=%s\n"
            "its acceptance criteria: %s"
            % (
                index,
                total,
                current_id,
                milestone.get("title") or "",
                "; ".join(milestone.get("acceptance_criteria") or []) or "(none stated)",
            )
        )
    parts.append(result_text)
    if context_block:
        parts.append("# ADDITIONAL CONTEXT\n%s" % context_block)
    parts.append(
        "# ADVISOR REQUEST\n"
        "Review this result against the milestone's acceptance criteria and the global "
        "criteria. Give one verdict for this milestone (approve/revise/reject) and report "
        "criteria_status for every criterion you can now judge. Set status=done only when "
        "all global acceptance criteria are met and proven. Exactly one JSON object, no prose."
    )
    user_content = "\n\n".join(parts)

    mock_entries = _mock_entries(cfg, args)
    mock_index = len(transcript["rounds"])

    normalised, _raw, meta, index_after = loop.run_round(
        session_dir, transcript, user_content, cfg,
        mock_entries=mock_entries, mock_index=mock_index, dry_run=args.dry_run, progress=progress,
    )

    if args.dry_run:
        print(json.dumps({"dry_run": True, "request": meta["payload"]}, indent=2, ensure_ascii=False))
        eprint("%s: dry run -- session not written" % PROG)
        return EXIT_OK

    loop.absorb_reply(transcript, normalised, progress)
    _save_reply_lessons(transcript, normalised, cfg, progress)
    code = loop.finish(session_dir, transcript, normalised, progress=progress)
    report_path, retrospective = None, None
    if loop.loop_ended(session_dir, transcript, normalised, progress):
        report_path, retrospective = _close_out(
            session_dir, transcript, cfg, args, progress, mock_entries, index_after
        )
    loop.emit_final(normalised, report_path=report_path, retrospective=retrospective)
    return code


def cmd_stuck(args, cfg, progress):
    """Re-escalate with failure details (item 2).

    Used when the executor cannot make progress on the current milestone.  The
    advisor gets the failure in full -- what was tried, the verbatim error, what
    is blocking -- so it can change the approach rather than restate the plan.
    """
    session_dir = require_session_dir(args.session)
    transcript = session.load_transcript(session_dir)
    transcript["_session"] = str(session_dir)
    transcript["escalations"] = int(transcript.get("escalations") or 0) + 1
    transcript["status"] = "stuck"

    details = ""
    if args.failure_file:
        details = Path(args.failure_file).read_text(encoding="utf-8", errors="replace")
    if args.reason:
        details = (details + "\n\n" + args.reason).strip()
    if not details.strip():
        raise BigbrainError(
            "stuck requires --reason TEXT or --failure-file FILE describing what failed",
            EXIT_CONFIG,
        )
    if args.attempts:
        details += "\n\nAttempts already made at this step: %d" % args.attempts

    _inject_lessons(transcript, cfg, progress)

    milestone_id = args.milestone or transcript.get("current_milestone")
    parts = [
        "# EXECUTOR IS STUCK (round %d)" % (len(transcript["rounds"]) + 1),
        "The executor cannot complete the current step. Do not restate the existing plan: "
        "diagnose the failure and give a materially different approach.",
    ]
    if milestone_id:
        parts.append("current milestone: %s" % milestone_id)
    failures = [entry for entry in transcript["rounds"] if entry.get("verdict") in ("revise", "reject")]
    if failures:
        parts.append(
            "previous non-approving verdicts: %s"
            % "; ".join(
                "round %s -> %s" % (entry.get("round"), entry.get("verdict")) for entry in failures[-3:]
            )
        )
    parts.append("# FAILURE DETAILS\n%s" % details)
    parts.append(
        "# ADVISOR REQUEST\n"
        "Either give a corrected, concrete plan (status=continue), state precisely what is "
        "missing and who must supply it (status=blocked), or narrow the milestone so the "
        "executor can finish it. Exactly one JSON object, no prose."
    )
    user_content = "\n\n".join(parts)

    banner(progress, cfg, "stuck: %s" % (milestone_id or "current step"))
    mock_entries = _mock_entries(cfg, args)
    mock_index = len(transcript["rounds"])
    normalised, _raw, meta, index_after = loop.run_round(
        session_dir, transcript, user_content, cfg,
        mock_entries=mock_entries, mock_index=mock_index, dry_run=args.dry_run, progress=progress,
    )
    if args.dry_run:
        print(json.dumps({"dry_run": True, "request": meta["payload"]}, indent=2, ensure_ascii=False))
        eprint("%s: dry run -- session not written" % PROG)
        return EXIT_OK

    loop.absorb_reply(transcript, normalised, progress)
    _save_reply_lessons(transcript, normalised, cfg, progress)
    code = loop.finish(session_dir, transcript, normalised, progress=progress)
    report_path, retrospective = None, None
    if loop.loop_ended(session_dir, transcript, normalised, progress):
        report_path, retrospective = _close_out(
            session_dir, transcript, cfg, args, progress, mock_entries, index_after
        )
    loop.emit_final(normalised, report_path=report_path, retrospective=retrospective)
    return code


def cmd_finish(args, cfg, progress):
    """Write the report for a session, running the retrospective if it has not run.

    ``finish`` writes no advisor reply, so its stdout carries the *report JSON*
    rather than an advisor object -- a different verb's contract, and the reason
    this one does not route through :func:`loop.emit_final`.  The markdown report
    still goes to stderr so ``--json`` on stdout stays parseable.
    """
    session_dir = require_session_dir(args.session)
    transcript = session.load_transcript(session_dir)
    transcript["_session"] = str(session_dir)

    if not transcript.get("retrospective") and not args.no_retrospective:
        mock_entries = _mock_entries(cfg, args)
        index = len(transcript["rounds"])
        normalised, index = loop.run_retrospective(
            session_dir, transcript, cfg, mock_entries=mock_entries, mock_index=index, progress=progress
        )
        if normalised is not None:
            _save_reply_lessons(transcript, normalised, cfg, progress)
        session.save_transcript(session_dir, transcript)

    payload = report.write_report(session_dir, transcript, cfg=cfg, progress=progress)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        report.print_report(payload, stream=sys.stdout)
    return EXIT_OK


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def _add_loop_common(parser, task_side=False):
    parser.add_argument("--session", default=None if task_side else None,
                        help="session directory (default .bigbrain/session-<timestamp>)")
    parser.add_argument("--mock", metavar="SCRIPTED_FILE", default=None,
                        help="replay scripted advisor replies from a JSON list (also BIGBRAIN_MOCK)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request payload without sending it or writing the session")
    parser.add_argument("--quiet", action="store_true", help="suppress the [Bigbrain] progress lines")
    parser.add_argument("--no-retrospective", action="store_true",
                        help="skip the automatic end-of-run retrospective call")


def _add_scoring(parser):
    parser.add_argument("--files-estimated", type=int, default=None,
                        help="estimated number of files the change touches")
    parser.add_argument("--ambiguity", type=float, default=0.0,
                        help="0..1, how ambiguous the requirement is")
    parser.add_argument("--consecutive-failures", type=int, default=0,
                        help="how many times this task has already failed")
    parser.add_argument("--high-risk", action="append", default=[],
                        help="high-risk tag, repeatable or comma-separated (migration, delete, auth, infra, ...)")
    parser.add_argument("--user-request", action="store_true",
                        help="the user explicitly asked for the advisor")
    parser.add_argument("--no-score", action="store_true",
                        help="skip scoring entirely and escalate unconditionally")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="bigbrain_cli.py",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the [Bigbrain] progress lines")
    # Global forms of the loop flags: `advisor.py --dry-run start ...` must keep
    # working, so these are accepted before the subcommand as well as after it.
    # Subparser values win when both are given.
    parser.add_argument("--dry-run", action="store_true", dest="_global_dry_run",
                        help="print the request payload without sending it or writing the session")
    parser.add_argument("--mock", metavar="SCRIPTED_FILE", default=None, dest="_global_mock",
                        help="replay scripted advisor replies from a JSON list (also BIGBRAIN_MOCK)")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- score ---------------------------------------------------------
    score = sub.add_parser("score", help="compute the escalation score and decide (item 1)")
    score.add_argument("--files-changed", type=int, default=None, help="files actually changed")
    score.add_argument("--files-estimated", type=int, default=None, help="files you expect to change")
    score.add_argument("--ambiguity", type=float, default=0.0, help="0..1 ambiguity of the request")
    score.add_argument("--consecutive-failures", type=int, default=0, help="prior failed attempts")
    score.add_argument("--high-risk", action="append", default=[],
                       help="high-risk tag, repeatable or comma-separated")
    score.add_argument("--user-request", action="store_true", help="the user asked for the advisor")
    score.add_argument("--threshold", type=float, default=None,
                       help="override the decision threshold (default 0.6 / BIGBRAIN_THRESHOLD)")
    score.add_argument("--weights", default=None, help="JSON object overriding the weights")
    score.add_argument("--explain", action="store_true", help="print the per-signal breakdown")
    score.add_argument("--json", action="store_true", help="machine-readable output")
    score.add_argument("--quiet", action="store_true", help="suppress the [Bigbrain] progress lines")

    # -- start ---------------------------------------------------------
    start = sub.add_parser("start", help="open a session: ask for the plan and the milestones")
    start.add_argument("--task", required=True, help="what must change, and the acceptance criteria")
    start.add_argument("--context-file", action="append", default=[], help="file to include (repeatable)")
    start.add_argument("--session", default=None, help="session directory")
    start.add_argument("--force", action="store_true", help="escalate even below the threshold, or reuse a session")
    _add_scoring(start)
    start.add_argument("--mock", default=None, help="scripted replies JSON list (also BIGBRAIN_MOCK)")
    start.add_argument("--dry-run", action="store_true", help="print the payload, write nothing")
    start.add_argument("--quiet", action="store_true")
    start.add_argument("--no-retrospective", action="store_true")

    # -- report --------------------------------------------------------
    rep = sub.add_parser("report", help="send a milestone result for review")
    rep.add_argument("--session", required=True, help="session directory")
    rep.add_argument("--result-file", required=True, help="what was done, diffs, verbatim verify output")
    rep.add_argument("--milestone", default=None, help="milestone id under review (default: current)")
    rep.add_argument("--context-file", action="append", default=[], help="extra context (repeatable)")
    rep.add_argument("--force", action="store_true", help="add a round to an already-finished session")
    rep.add_argument("--mock", default=None)
    rep.add_argument("--dry-run", action="store_true")
    rep.add_argument("--quiet", action="store_true")
    rep.add_argument("--no-retrospective", action="store_true")

    # -- stuck ---------------------------------------------------------
    stuck = sub.add_parser("stuck", help="re-escalate the current milestone with failure details")
    stuck.add_argument("--session", required=True)
    stuck.add_argument("--reason", default=None, help="what failed, in one line")
    stuck.add_argument("--failure-file", default=None, help="file with the failure, error output and attempts")
    stuck.add_argument("--attempts", type=int, default=0, help="attempts already made at this step")
    stuck.add_argument("--milestone", default=None, help="milestone id (default: current)")
    stuck.add_argument("--mock", default=None)
    stuck.add_argument("--dry-run", action="store_true")
    stuck.add_argument("--quiet", action="store_true")
    stuck.add_argument("--no-retrospective", action="store_true")

    # -- finish --------------------------------------------------------
    fin = sub.add_parser("finish", help="write report.md/report.json, running the retrospective if needed")
    fin.add_argument("--session", required=True)
    fin.add_argument("--json", action="store_true", help="print report.json instead of report.md")
    fin.add_argument("--no-retrospective", action="store_true")
    fin.add_argument("--mock", default=None)
    fin.add_argument("--quiet", action="store_true")

    # -- status --------------------------------------------------------
    stat = sub.add_parser("status", help="print session state")
    stat.add_argument("--session", default=None, help="session directory")
    stat.add_argument("--all", action="store_true", help="list every session under the session root")
    stat.add_argument("--root", default=None, help="root to list sessions from (with --all)")
    stat.add_argument("--audit", default=None, metavar="DIR",
                      help="list AGENTS.md-shaped files under DIR and their hashes (read-only)")
    stat.add_argument("--json", action="store_true")
    stat.add_argument("--quiet", action="store_true")

    # -- setup ---------------------------------------------------------
    setup = sub.add_parser("setup", help="interactive wizard: detect, ask, validate, write ~/.bigbrain/config.json")
    setup.add_argument("--timeout", type=int, default=None,
                       help="seconds to wait for the validation request (default 20)")
    setup.add_argument("--quiet", action="store_true")

    # -- lessons -------------------------------------------------------
    les = sub.add_parser("lessons", help="the user-level experience store (item 4)")
    les.add_argument("--json", action="store_true")
    les.add_argument("--quiet", action="store_true")
    lsub = les.add_subparsers(dest="lessons_command")

    def _leaf(name, help_text):
        """A lessons subcommand that also accepts --json/--quiet after itself.

        argparse binds a parent's flags before the subcommand token, so
        ``lessons --json add`` works but ``lessons add --json`` does not unless
        the leaf repeats them. Repeating is what read naturally, so both forms
        are supported.
        """
        leaf = lsub.add_parser(name, help=help_text)
        leaf.add_argument("--json", action="store_true")
        leaf.add_argument("--quiet", action="store_true")
        return leaf

    llist = _leaf("list", "list the highest-ranked lessons")
    llist.add_argument("--limit", type=int, default=0, help="how many to show (0 = all)")
    llist.add_argument("--scope", default=None, help="filter by scope")
    llist.add_argument("--prune", action="store_true", help="prune before listing")
    llist.add_argument("--cap", type=int, default=None, help="prune cap")

    ladd = _leaf("add", "add a lesson")
    ladd.add_argument("text", nargs="?", default=None)
    ladd.add_argument("--from-file", default=None)
    ladd.add_argument("--kind", default="workflow")
    ladd.add_argument("--scope", default="global")
    ladd.add_argument("--confidence", type=float, default=0.6)
    ladd.add_argument("--session", default=None)

    lprune = _leaf("prune", help_text="trim the store to the cap")
    lprune.add_argument("--cap", type=int, default=None)

    lexp = _leaf("export", "write or print lessons.md")
    lexp.add_argument("--out", default=None, help="write to this file instead of stdout")
    lexp.add_argument("--limit", type=int, default=0)

    return parser


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


HANDLERS = {
    "score": cmd_score,
    "status": cmd_status,
    "lessons": cmd_lessons,
    "start": cmd_start,
    "report": cmd_report,
    "stuck": cmd_stuck,
    "finish": cmd_finish,
}


def _merge_global_flags(args):
    """Fold the pre-subcommand flags into the subcommand namespace.

    ``advisor.py --dry-run start`` and ``advisor.py start --dry-run`` must both
    work: the first is what older docs and the test suite use, the second reads
    better.  A value given after the subcommand wins.
    """
    for global_name, local_name in (("_global_dry_run", "dry_run"), ("_global_mock", "mock")):
        value = getattr(args, global_name, None)
        if not value:
            continue
        if not hasattr(args, local_name):
            continue
        if getattr(args, local_name, None):
            continue
        setattr(args, local_name, value)
    return args


def main(argv=None):
    args = _merge_global_flags(build_parser().parse_args(argv))
    progress = make_progress(args)

    if args.command == "setup":
        # The wizard is how a missing configuration gets fixed, so it must run
        # before (and regardless of) the configuration check below.
        from . import setup_wizard

        return setup_wizard.run_wizard(
            timeout=args.timeout or setup_wizard.VALIDATE_TIMEOUT
        )

    if args.command == "score":
        # score is a local calculation, so a missing endpoint is not a problem
        # for it -- but every *other* configuration problem still is. A
        # malformed BIGBRAIN_WEIGHTS must fail loudly here rather than quietly
        # scoring with the defaults.
        cfg = load_config()
        blocking = [
            problem
            for problem in config_problems(cfg)
            if "BIGBRAIN_BASE_URL" not in problem and "API_KEY" not in problem
        ]
        if blocking:
            for problem in blocking:
                eprint("%s: configuration error: %s" % (PROG, problem))
            return EXIT_CONFIG
        return cmd_score(args, cfg, progress)

    cfg = load_config()
    if args.command == "status" and getattr(args, "audit", None):
        return cmd_status(args, cfg, progress)
    if args.command == "lessons":
        # The lesson store is entirely local: listing, adding and pruning it
        # must work with no endpoint configured, because the skill's very first
        # step is `lessons list` -- before check_config has been run.
        return cmd_lessons(args, cfg, progress)
    if not config_or_fail(cfg):
        return EXIT_CONFIG

    handler = HANDLERS.get(args.command)
    if handler is None:  # pragma: no cover - argparse already rejects these
        raise BigbrainError("unknown command %r" % args.command, EXIT_CONFIG)
    return handler(args, cfg, progress)


def run(argv=None):
    """``main`` with the shared exception mapping; returns the exit code."""
    try:
        return main(argv)
    except BigbrainError as exc:
        eprint("%s: %s" % (PROG, exc))
        for key, value in exc.extra.items():
            eprint("%s:   %s: %s" % (PROG, key, value))
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        eprint("%s: interrupted" % PROG)
        return 1
    except BrokenPipeError:  # pragma: no cover - piping into head, etc.
        return EXIT_OK
    except Exception:  # pragma: no cover - defensive
        traceback.print_exc()
        return 1


__all__ = ["HANDLERS", "build_parser", "main", "run"]
