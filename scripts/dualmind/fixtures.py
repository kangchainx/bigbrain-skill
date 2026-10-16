"""Scripted advisor replies used by the mock server and the offline examples.

The default scenario is the full milestone flow, which is what the loop is
actually for:

    round 1  continue, plan + 3 milestones + global acceptance criteria
    round 2  milestone 1 approved
    round 3  milestone 2 revise
    round 4  milestone 2 approved
    round 5  milestone 3 approved, status=done, every criterion met
    round 6  the retrospective (summary + lessons)

Each entry carries a ``usage`` block so token accounting, cost and the savings
estimate can be exercised without a network call.  ``usage`` is optional; the
loop falls back to a character-based estimate when it is absent.
"""

from __future__ import annotations

import copy
import json


def _usage(input_tokens, output_tokens):
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False)


def _entry(payload, input_tokens, output_tokens):
    """One scripted reply: the advisor's JSON text plus its reported usage.

    ``text`` must be a *string* -- the mock server hands it straight to the
    response body, mirroring what a real API returns, so the client's JSON
    extraction is exercised rather than bypassed.
    """
    import json as _json

    return {
        "text": _json.dumps(payload, ensure_ascii=False),
        "usage": _usage(input_tokens, output_tokens),
    }


GLOBAL_CRITERIA = [
    "entries expire after their TTL, proven by a test that advances an injected clock",
    "the cache is bounded by maxsize and the evicted key is asserted, not just the length",
    "the full test suite stays green",
]


def _base(status, summary, **overrides):
    payload = {
        "status": status,
        "summary": summary,
        "assumptions": [],
        "questions_for_executor": [],
        "plan": [],
        "milestones": [],
        "current_milestone": None,
        "acceptance_criteria": [],
        "criteria_status": [],
        "lessons": [],
        "review": {"verdict": "n/a", "issues": []},
        "next_instructions": "",
        "blocked_reason": None,
    }
    payload.update(overrides)
    return payload


def _round1():
    return _base(
        "continue",
        "Plan for the TTL cache, in three milestones, so expiry can be proven before "
        "eviction is layered on top.",
        assumptions=[
            "Eviction is LRU; the repo states no policy.",
            "TTL uses time.monotonic so a wall-clock change cannot resurrect entries.",
        ],
        questions_for_executor=["Does the existing suite use unittest or pytest?"],
        plan=[
            {
                "id": "1.1",
                "action": "Add TTLCache(ttl=60, maxsize=128) with an injectable clock callable",
                "files": ["cache.py"],
                "verify": "python -c \"from cache import TTLCache; TTLCache()\"",
            },
            {
                "id": "1.2",
                "action": "Cover hit, miss and expiry with tests",
                "files": ["tests/test_cache.py"],
                "verify": "python -m unittest discover -s tests",
            },
        ],
        milestones=[
            {
                "id": "m1",
                "title": "Implement TTLCache with an injectable clock",
                "steps": [
                    {
                        "id": "1.1",
                        "action": "Add TTLCache(ttl=60, maxsize=128) with an injectable clock callable",
                        "files": ["cache.py"],
                        "verify": "python -c \"from cache import TTLCache; TTLCache()\"",
                    },
                    {
                        "id": "1.2",
                        "action": "Add a frozen-clock test proving an expired entry is withheld",
                        "files": ["tests/test_cache.py"],
                        "verify": "python -m unittest discover -s tests",
                    },
                ],
                "acceptance_criteria": [
                    "get() returns the default once the injected clock passes the TTL",
                    "the expired key is absent from __len__",
                ],
            },
            {
                "id": "m2",
                "title": "Bound the cache by maxsize with LRU eviction",
                "steps": [
                    {
                        "id": "2.1",
                        "action": "Evict the least-recently-used key when len == maxsize",
                        "files": ["cache.py"],
                        "verify": "python -m unittest discover -s tests",
                    },
                    {
                        "id": "2.2",
                        "action": "Assert which key was evicted, not just the resulting length",
                        "files": ["tests/test_cache.py"],
                        "verify": "python -m unittest discover -s tests",
                    },
                ],
                "acceptance_criteria": ["the evicted key is asserted by name in a test"],
            },
            {
                "id": "m3",
                "title": "Run the full suite and document the behaviour",
                "steps": [
                    {
                        "id": "3.1",
                        "action": "Run the whole suite and record the verbatim output",
                        "files": ["tests/test_cache.py"],
                        "verify": "python -m unittest discover -s tests",
                    }
                ],
                "acceptance_criteria": ["the full suite passes with no skips"],
            },
        ],
        current_milestone="m1",
        acceptance_criteria=GLOBAL_CRITERIA,
        next_instructions=(
            "Answer the question from the repo, then work milestone m1 only: implement the "
            "class, add the frozen-clock test, run the suite, and report both verify commands."
        ),
    )


def _round2():
    return _base(
        "continue",
        "Milestone m1 verified: the frozen-clock test proves expiry and the key leaves __len__.",
        plan=[],
        current_milestone="m2",
        criteria_status=[
            {
                "criterion": GLOBAL_CRITERIA[0],
                "met": True,
                "evidence": "test_expired_entry_is_withheld advances the injected clock past the TTL",
            },
            {"criterion": GLOBAL_CRITERIA[1], "met": False, "evidence": "eviction not implemented yet"},
            {"criterion": GLOBAL_CRITERIA[2], "met": True, "evidence": "Ran 13 tests, OK"},
        ],
        review={
            "verdict": "approve",
            "milestone_id": "m1",
            "issues": [],
        },
        next_instructions=(
            "Move to milestone m2: add LRU eviction at maxsize and assert which key was dropped, "
            "then re-run the suite and report it verbatim."
        ),
    )


def _round3():
    return _base(
        "continue",
        "Milestone m2 is close: eviction works, but the test asserts the length only, so which "
        "key was dropped is still unproven.",
        plan=[
            {
                "id": "2.2",
                "action": "Assert the specific evicted key, and cover the re-insert-moves-to-front case",
                "files": ["tests/test_cache.py"],
                "verify": "python -m unittest discover -s tests",
            }
        ],
        current_milestone="m2",
        review={
            "verdict": "revise",
            "milestone_id": "m2",
            "issues": [
                "test_eviction_at_maxsize asserts len(cache) == maxsize but never names the "
                "evicted key, so a wrong key being dropped would still pass.",
                "No test covers evicting a key that was re-inserted after eviction; the LRU "
                "ordering claim is therefore unproven.",
            ],
        },
        next_instructions=(
            "Add an assertion naming the evicted key and a re-insert case, re-run the suite and "
            "report the output verbatim."
        ),
    )


def _round4():
    return _base(
        "continue",
        "Milestone m2 approved: the evicted key is now asserted by name and the re-insert case "
        "confirms the LRU ordering.",
        plan=[],
        current_milestone="m3",
        criteria_status=[
            {"criterion": GLOBAL_CRITERIA[0], "met": True, "evidence": "frozen-clock test, unchanged"},
            {
                "criterion": GLOBAL_CRITERIA[1],
                "met": True,
                "evidence": "test_evicts_least_recently_used asserts the dropped key by name",
            },
            {"criterion": GLOBAL_CRITERIA[2], "met": True, "evidence": "Ran 15 tests, OK"},
        ],
        review={"verdict": "approve", "milestone_id": "m2", "issues": []},
        next_instructions=(
            "Finish milestone m3: run the whole suite (no filters, no skips) and report the "
            "verbatim output so completion can be judged."
        ),
    )


def _round5():
    return _base(
        "done",
        "Delivered a TTLCache with an injectable monotonic clock, TTL expiry and bounded LRU "
        "eviction, covered by 15 tests; the full suite is green. Not proven: behaviour under "
        "concurrent access, which was out of scope.",
        plan=[],
        milestones=[],
        current_milestone=None,
        criteria_status=[
            {"criterion": GLOBAL_CRITERIA[0], "met": True, "evidence": "frozen-clock expiry test"},
            {
                "criterion": GLOBAL_CRITERIA[1],
                "met": True,
                "evidence": "evicted key asserted by name in test_evicts_least_recently_used",
            },
            {"criterion": GLOBAL_CRITERIA[2], "met": True, "evidence": "Ran 15 tests in 0.041s -- OK"},
        ],
        review={"verdict": "approve", "milestone_id": "m3", "issues": []},
        next_instructions="Stop the loop and report the delivered change and the unproven area.",
    )


def _retrospective():
    payload = _base(
        "done",
        "run went cleanly; one revision for test thoroughness",
        lessons=[
            {
                "text": "When asking for eviction, require the test to name the evicted key; "
                        "asserting only the resulting length passes on a wrong implementation.",
                "kind": "codex_shortcoming",
                "scope": "global",
                "confidence": 0.9,
            },
            {
                "text": "This user wants verification commands quoted with their verbatim output, "
                        "including the test count, in every report.",
                "kind": "user_preference",
                "scope": "global",
                "confidence": 0.8,
            },
            {
                "text": "State the determinism requirement (an injectable clock) in round 1 when "
                        "the task involves time, rather than retrofitting it after the first review.",
                "kind": "workflow",
                "scope": "global",
                "confidence": 0.7,
            },
        ],
        review={"verdict": "n/a", "issues": []},
        next_instructions="Nothing further; the run is closed.",
    )
    return payload


def milestone_scenario():
    """The full 5-round milestone run plus its retrospective.

    Round 6 is the retrospective reply.  Calls are scripted in order, so the
    same list drives the mock server, ``--mock`` replay and the example.
    """
    return [
        _entry(_round1(), 1840, 620),
        _entry(_round2(), 2620, 310),
        _entry(_round3(), 3180, 420),
        _entry(_round4(), 3760, 300),
        _entry(_round5(), 4310, 380),
        _entry(_retrospective(), 4880, 520),
    ]


def continue_forever():
    """One reply that never finishes, so the max-rounds path is reachable."""
    return [
        {
            "status": "continue",
            "summary": "Still working; more verification needed.",
            "assumptions": [],
            "questions_for_executor": [],
            "plan": [
                {"id": "1", "action": "Keep going", "files": ["x.py"], "verify": "run the tests"}
            ],
            "milestones": [],
            "current_milestone": "m1",
            "acceptance_criteria": ["the tests pass"],
            "criteria_status": [{"criterion": "the tests pass", "met": False, "evidence": "not yet"}],
            "lessons": [],
            "review": {"verdict": "revise", "issues": ["Not yet proven."]},
            "next_instructions": "Continue.",
            "blocked_reason": None,
        }
    ]


def done_without_criteria():
    """``status=done`` but no criteria_status: must NOT end the loop (item 2)."""
    return [
        {
            "status": "done",
            "summary": "I think this is finished.",
            "assumptions": [],
            "questions_for_executor": [],
            "plan": [],
            "milestones": [],
            "current_milestone": None,
            "acceptance_criteria": ["the tests pass"],
            "criteria_status": [],
            "lessons": [],
            "review": {"verdict": "approve", "issues": []},
            "next_instructions": "Stop.",
            "blocked_reason": None,
        },
        {
            "status": "continue",
            "summary": "Corrected: completion without proven criteria is not completion.",
            "assumptions": [],
            "questions_for_executor": [],
            "plan": [
                {"id": "1", "action": "Run the suite", "files": ["tests/x.py"], "verify": "pytest -q"}
            ],
            "milestones": [],
            "current_milestone": None,
            "acceptance_criteria": [],
            "criteria_status": [{"criterion": "the tests pass", "met": False, "evidence": "not shown"}],
            "lessons": [],
            "review": {"verdict": "revise", "issues": ["No evidence the suite ran."]},
            "next_instructions": "Run the suite and report it verbatim.",
            "blocked_reason": None,
        },
    ]


def blocked_script():
    return [
        {
            "status": "blocked",
            "summary": "Cannot proceed without production credentials.",
            "assumptions": [],
            "questions_for_executor": ["Which staging endpoint should be used?"],
            "plan": [],
            "milestones": [],
            "current_milestone": None,
            "acceptance_criteria": [],
            "criteria_status": [],
            "lessons": [],
            "review": {"verdict": "n/a", "issues": ["No credentials available in this environment."]},
            "next_instructions": "Stop and report the blocker to the user.",
            "blocked_reason": "Missing production credentials for the migration target.",
        }
    ]


def stuck_script():
    """A reply for a `stuck` re-escalation: change the approach, do not restate."""
    return [
        {
            "status": "continue",
            "summary": "The approach is wrong: eviction by clock is being conflated with eviction "
                       "by recency. Split them.",
            "assumptions": [],
            "questions_for_executor": [],
            "plan": [
                {
                    "id": "m2-fix",
                    "action": "Keep an OrderedDict for recency and expire lazily on read; do not "
                              "sweep on every write",
                    "files": ["cache.py"],
                    "verify": "python -m unittest discover -s tests",
                }
            ],
            "milestones": [],
            "current_milestone": "m2",
            "acceptance_criteria": [],
            "criteria_status": [],
            "lessons": [],
            "review": {"verdict": "reject", "milestone_id": "m2", "issues": [
                "Do not restate the previous plan; the failure was conceptual, not a missing step."
            ]},
            "next_instructions": "Replace the sweep with lazy expiry on read, then re-run the suite.",
            "blocked_reason": None,
        }
    ]


def garbage_script():
    """A reply that is not JSON at all -- exercises the repair path end to end."""
    return [
        "Sure! Here is my assessment:\n\nI think you should probably not-json at all {{ broken"
    ]


#: A reply cut off mid-JSON, exactly as a real 8000-token ceiling produced it:
#: the object opens, the long fields fill it, and the text stops inside a string
#: with no closing brace.  Reusing the real shape matters -- a short stub would
#: not reproduce the "Unterminated string" parse error the fix is about.
_TRUNCATED_TEXT = _json_dumps(
    {
        "status": "continue",
        "summary": "Round 1 plan, in full detail, for the whole task.",
        "assumptions": ["Eviction is LRU.", "TTL uses a monotonic clock."],
        "questions_for_executor": ["Does the suite use unittest or pytest?"],
        "plan": [
            {
                "id": "1.1",
                "action": "Add TTLCache with an injectable clock callable, defaulting to "
                          "time.monotonic, and a get() that returns the default once the "
                          "deadline has passed, removing the key from the backing mapping",
                "files": ["cache.py"],
                "verify": "python -m unittest discover -s tests",
            }
        ],
        "milestones": [
            {
                "id": "m1",
                "title": "TTL semantics with an injectable clock and expiry tests",
                "steps": [],
                "acceptance_criteria": ["an expired entry is not returned"],
            }
        ],
        "current_milestone": "m1",
        "acceptance_criteria": GLOBAL_CRITERIA,
        "criteria_status": [],
        "lessons": [],
        "review": {"verdict": "n/a", "issues": []},
        "next_instructions": "Start m1. Implement the class, add the frozen-clock test, run "
                             "the suite, and report the verbatim output including the full "
                             "unittest summary line and the answers to the three questions ",
    }
)[:-12]


def truncated_then_concise():
    """A truncated reply, then a short good one -- the max_tokens retry path.

    Entry 1 is cut off mid-string (as an 8000-token ceiling did to a real run);
    entry 2 is the concise answer the retry asks for.  The first entry declares
    ``stop_reason: max_tokens``, which is the whole point: the loop must tell a
    truncated reply apart from a malformed one and retry with *brevity plus a
    bigger budget*, not a generic repair.
    """
    return [
        {"text": _TRUNCATED_TEXT, "usage": _usage(8436, 5635), "stop_reason": "max_tokens"},
        _entry(
            _base(
                "continue",
                "Plan is m1 TTL, m2 eviction, m3 the full suite.",
                current_milestone="m1",
                milestones=[
                    {
                        "id": "m1",
                        "title": "TTL semantics with an injectable clock",
                        "steps": [],
                        "acceptance_criteria": ["an expired entry is not returned"],
                    },
                    {
                        "id": "m2",
                        "title": "Bounded cache with LRU eviction",
                        "steps": [],
                        "acceptance_criteria": ["the evicted key is asserted by name"],
                    },
                    {
                        "id": "m3",
                        "title": "Full suite green",
                        "steps": [],
                        "acceptance_criteria": ["the full suite passes with no skips"],
                    },
                ],
                acceptance_criteria=GLOBAL_CRITERIA,
                next_instructions="Start m1: implement TTLCache with an injectable clock.",
            ),
            8436,
            700,
        ),
    ]


def omit_current_milestone():
    """The advisor approves m2 but names no successor -- current_milestone is null.

    A real advisor does this: round 3 approved m2 and had nothing to point at
    next, because reviewing m3 is what comes after.  The loop must then work out
    that the *next* report is a review of m3, and say so, rather than reusing the
    stale pointer and announcing m2 (see loop.resolve_milestone).
    """
    return [
        _entry(
            _base(
                "continue",
                "Plan for the task, in three milestones.",
                current_milestone="m1",
                milestones=[
                    {
                        "id": "m1",
                        "title": "first unit",
                        "steps": [],
                        "acceptance_criteria": ["m1 is done"],
                    },
                    {
                        "id": "m2",
                        "title": "second unit",
                        "steps": [],
                        "acceptance_criteria": ["m2 is done"],
                    },
                    {
                        "id": "m3",
                        "title": "third unit",
                        "steps": [],
                        "acceptance_criteria": ["m3 is done"],
                    },
                ],
                acceptance_criteria=GLOBAL_CRITERIA,
                next_instructions="Work m1.",
            ),
            1840,
            620,
        ),
        # Approves m1 and moves the pointer on.
        _entry(
            _base(
                "continue",
                "m1 approved.",
                current_milestone="m2",
                review={"verdict": "approve", "milestone_id": "m1", "issues": []},
                next_instructions="Work m2.",
            ),
            2620,
            310,
        ),
        # Approves m2 with **no** current_milestone: the pointer stays at m2,
        # which is now stale, so the next report is m3.
        _entry(
            _base(
                "continue",
                "m2 approved; nothing further to point at.",
                current_milestone=None,
                review={"verdict": "approve", "milestone_id": "m2", "issues": []},
                next_instructions="Work m3.",
            ),
            3180,
            420,
        ),
        # Approves m3 and closes the run.
        _entry(
            _base(
                "done",
                "All three milestones delivered.",
                current_milestone=None,
                criteria_status=[
                    {"criterion": c, "met": True, "evidence": "proven"} for c in GLOBAL_CRITERIA
                ],
                review={"verdict": "approve", "milestone_id": "m3", "issues": []},
                next_instructions="Stop.",
            ),
            3760,
            300,
        ),
        _entry(_retrospective(), 4880, 520),
    ]


SCENARIOS = {
    "milestones": milestone_scenario,
    "continue-forever": continue_forever,
    "continue": continue_forever,
    "blocked": blocked_script,
    "block": blocked_script,
    "stuck": stuck_script,
    "done-without-criteria": done_without_criteria,
    "garbage": garbage_script,
    "truncated-then-concise": truncated_then_concise,
    "omit-current-milestone": omit_current_milestone,
}


def scenario(name):
    """Return a fresh copy of a named scenario."""
    factory = SCENARIOS.get(name)
    if factory is None:
        return None
    return copy.deepcopy(factory())


__all__ = [
    "GLOBAL_CRITERIA",
    "SCENARIOS",
    "blocked_script",
    "continue_forever",
    "done_without_criteria",
    "garbage_script",
    "milestone_scenario",
    "scenario",
    "stuck_script",
]
