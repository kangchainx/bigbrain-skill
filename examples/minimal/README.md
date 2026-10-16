# Minimal example: add a TTL cache layer with tests

Task: add a TTL cache to a small Python module, with tests, and prove it works.

This walkthrough uses the scripted replies in `mock_rounds.json` — the same fixture the test
suite and the mock server use — so you can follow it end to end without an API key:

```bash
bash examples/minimal/run.sh
```

The scripted scenario is the full milestone flow:

| Round | Call | Reply |
|-------|------|-------|
| 1 | `start` | `continue`, 3 milestones (`m1`/`m2`/`m3`) + 3 global criteria |
| 2 | `report` m1 | verdict `approve` for `m1` |
| 3 | `report` m2 | verdict `revise` for `m2` — the evicted key is not asserted |
| 4 | `report` m2 | verdict `approve` for `m2` |
| 5 | `report` m3 | `status=done`, all 3 criteria met → **DONE** |
| 6 | retrospective | a process summary plus 3 lessons |

## 0. Configure and verify

```bash
export BIGBRAIN_BASE_URL=https://api.example.com
export BIGBRAIN_API_KEY=sk-...

python3 scripts/check_config.py
# OK
#   base url : https://api.example.com
#   model    : claude-opus-5-5
#   api key  : sk-r...9f
#   latency  : 412 ms
#   reply    : pong
```

If this does not exit 0, stop here. The checker names the variable at fault.

## 1. Load your lessons

Always the first step on a Bigbrain trigger:

```bash
python3 scripts/bigbrain_cli.py lessons list --limit 10
# store: /home/you/.bigbrain/experience
# total: 7  shown: 7
#   [workflow   0.87] Require verification commands to be quoted with their verbatim output.
```

Nothing here on a first run — that is fine; lessons accumulate as you use the skill.

## 2. Score the task

```bash
python3 scripts/bigbrain_cli.py score --files-estimated 4 --ambiguity 0.4 --high-risk infra
# [Bigbrain] evaluating escalation score 0.52 <= 0.60 -> stay_local
```

Below threshold. Add a high-risk tag that actually applies, or raise the ambiguity estimate —
do not tune the inputs to reach the answer you want:

```bash
python3 scripts/bigbrain_cli.py score --files-estimated 5 --ambiguity 0.7 --high-risk migration
# [Bigbrain] evaluating escalation score 0.72 > 0.60 -> escalate
```

## 3. Round 1 — escalate and get the milestones

```bash
python3 scripts/bigbrain_cli.py start \
  --task "Add a TTL cache layer to cache.py with tests.
          Acceptance: entries expire after their TTL; the cache is bounded by maxsize and the
          evicted key is asserted; the full test suite stays green.
          Escalation score 0.72." \
  --context-file cache.py --context-file tests/test_cache.py \
  --session .bigbrain/session-cache
```

The advisor replies with one JSON object (real shape, abridged):

```json
{
  "status": "continue",
  "summary": "Plan for the TTL cache, in three milestones, so expiry can be proven before eviction is layered on top.",
  "milestones": [
    {"id": "m1", "title": "Implement TTLCache with an injectable clock",
     "steps": [{"id": "1.1", "action": "...", "files": ["cache.py"], "verify": "..."}],
     "acceptance_criteria": ["get() returns the default once the injected clock passes the TTL"]},
    {"id": "m2", "title": "Bound the cache by maxsize with LRU eviction", "steps": [], "acceptance_criteria": []},
    {"id": "m3", "title": "Run the full suite and document the behaviour", "steps": [], "acceptance_criteria": []}
  ],
  "current_milestone": "m1",
  "acceptance_criteria": [
    "entries expire after their TTL, proven by a test that advances an injected clock",
    "the cache is bounded by maxsize and the evicted key is asserted, not just the length",
    "the full test suite stays green"
  ],
  "criteria_status": [],
  "review": {"verdict": "n/a", "issues": []},
  "next_instructions": "Answer the question from the repo, then work milestone m1 only."
}
```

Note what round 1 established: the **global** criteria for the task, the milestones, and which
one is current. `criteria_status` is empty because nothing is proven yet.

## 4. Work m1, then report it

Do the steps in order and run each `verify`. Then write what happened:

```markdown
## Steps completed
1.1 TTLCache added with an injectable clock.
1.2 Frozen-clock expiry test added.

## Verify
$ python -m unittest discover -s tests
Ran 13 tests in 0.038s
OK
```

```bash
python3 scripts/bigbrain_cli.py report --session .bigbrain/session-cache --result-file r-m1.md
# [Bigbrain] milestone 1/3 sent for review (m1)
# [Bigbrain] round 2/8
# [Bigbrain] verdict: approve for milestone m1
```

## 5. A revise on m2

Round 3 comes back `revise`, and the issues are specific:

```json
{
  "review": {
    "verdict": "revise",
    "milestone_id": "m2",
    "issues": [
      "test_eviction_at_maxsize asserts len(cache) == maxsize but never names the evicted key,
       so a wrong key being dropped would still pass.",
      "No test covers evicting a key that was re-inserted after eviction; the LRU ordering
       claim is therefore unproven."
    ]
  }
}
```

Fix exactly what it named — the assertion, not the implementation — and report again:

```bash
python3 scripts/bigbrain_cli.py report --session .bigbrain/session-cache --result-file r-m2b.md
# [Bigbrain] verdict: approve for milestone m2
```

## 6. Finish

Round 5 returns `status=done` with all three criteria marked met, so the loop ends:

```bash
python3 scripts/bigbrain_cli.py report --session .bigbrain/session-cache --result-file r-m3.md
# [Bigbrain] milestone 3/3 sent for review (m3)
# [Bigbrain] verdict: approve for milestone m3
# DONE
# [Bigbrain] retrospective (done): requesting a process review
# [Bigbrain] lessons saved: 3
# [Bigbrain] report written: .bigbrain/session-cache/report.md
```

**`DONE` requires both halves**: `status=done` *and* every acceptance criterion marked met in
`criteria_status`. An advisor that says `done` without saying which criteria passed gets told
so, and the loop continues — try `mock_server.py --script done-without-criteria` to see that.

The retrospective summary prints to stdout, the lessons are merged into your store, and
`report.md` / `report.json` land in the session directory:

```
## Tokens
- advisor input: 20,590
- advisor output: 2,550
- advisor total: 23,140 across 6 call(s)
- executor work (estimated): 125,000
- all tokens: 148,140

## Cost estimate
- advisor spend: $0.5001
- executor spend: $0.3750 (estimated)
- actual total: $0.8751
- everything to the premium model: $3.9997
- estimated savings: $3.1246 (78.1%)
```

## 7. If you get stuck instead

When a milestone will not come together, hand over the failure rather than retrying:

```bash
python3 scripts/bigbrain_cli.py stuck --session .bigbrain/session-cache \
  --reason "eviction test passes but the key order is wrong" \
  --failure-file failing-output.txt --attempts 2
```

The advisor is told, explicitly, not to restate the plan that just failed — it must diagnose
and give a different approach, narrow the milestone, or declare a real blocker.

## Running it offline

```bash
# against the built-in scripted scenario
python3 scripts/mock_server.py --script milestones --port 0 --port-file /tmp/port
export BIGBRAIN_BASE_URL="http://127.0.0.1:$(cat /tmp/port)"
export BIGBRAIN_API_KEY=test-key

# or with no server at all
export BIGBRAIN_MOCK=examples/minimal/mock_rounds.json

# or without sending anything
python3 scripts/bigbrain_cli.py --dry-run start --task "..." --session /tmp/s
```

Both are for testing only. Never present a mock run as a real advisor review.
