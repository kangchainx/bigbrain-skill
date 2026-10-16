# dualmind

An agent skill that lets Codex hand complex work to an **Opus advisor** and keeps going until
the work is actually done.

Codex is the executor. For large features, multi-file changes, refactors across module
boundaries, ambiguous specs, migrations and other risky work, it escalates to a stronger
advisor model over an Anthropic-compatible Messages API. The advisor clarifies, plans in
milestones with acceptance criteria, reviews the executor's real output critically, and pushes
the task forward instead of stopping to ask the user for every decision. Simple tasks are done
locally, with no advisor at all.

## Features

- **Computed escalation, not a judgement call.** `score` turns files changed, ambiguity,
  consecutive failures, risk tags and an explicit user request into a single 0–1 number and
  compares it to a configurable threshold. Weights and threshold both configurable.
- **A milestone loop with a real finish line.** Round 1 returns the global acceptance criteria
  and 3-ish milestones, each with its own steps and criteria. The executor works one milestone
  at a time and reports it for review. The loop ends only when the advisor returns `done`
  **and** every acceptance criterion is marked met — a `done` that cannot say which criteria
  passed keeps looping.
- **`stuck` re-escalation.** When the executor cannot make progress, it hands over the failure
  and the attempts already made, and gets a materially different approach instead of a
  restatement.
- **Automatic retrospective.** When a session ends — done, blocked, or out of rounds — the
  advisor is called once more to review the *process* and return lessons. No user input needed.
- **A lesson store that grows across sessions.** Lessons live in a user-level directory, are
  injected into every advisor request, and are merged and pruned by confidence × recency.
  **No code path ever creates or modifies an `AGENTS.md`** — see below.
- **End-of-run report.** Escalations, rounds, advisor tokens summed from the API's `usage`
  fields, a cost estimate at configurable prices, and an estimated saving versus sending
  everything to the premium model. Written to `report.md` + `report.json`.
- **Visible progress.** Every step prints `[DualMind] ...` lines to stderr.
- **Python 3 standard library only** — no pip installs, no dependencies.
- **Local only** — no push, no publish. The installer's tarball fetch is the one network call,
  and only when there is no local checkout.

## Install

```bash
./install.sh                          # ${CODEX_HOME:-$HOME/.codex}/skills/dualmind
                                      # plus a symlink in ~/.agents/skills/dualmind
./install.sh --claude                 # also install into ~/.claude/skills/dualmind
./install.sh --copy                   # copy instead of symlink
./install.sh --uninstall              # remove the skill, keep your lessons
./install.sh --uninstall --purge      # also remove ~/.dualmind
```

Or with no checkout:

```bash
curl -fsSL <url>/install.sh | bash
DUALMIND_SRC=https://host/dualmind.tar.gz curl -fsSL <url>/install.sh | bash
```

`tests/`, `.dualmind/` and any lesson store are excluded from every install. `--uninstall`
keeps the experience store; only `--purge` removes your lessons.

## Configure

```bash
export DUALMIND_BASE_URL=https://api.example.com   # no trailing /v1
export DUALMIND_API_KEY=sk-...
```

Then verify — the skill refuses to escalate until this passes:

```bash
python3 scripts/check_config.py     # prints OK, model, base url, latency
```

The ping is judged, not just received: an endpoint that answers a one-word `ping` with a long
paragraph is reported as unusable (exit 6) rather than `OK`.

Optionals (all have defaults): `DUALMIND_MODEL` = `claude-opus-5-5`, `DUALMIND_MAX_ROUNDS` = `8`,
`DUALMIND_THRESHOLD` = `0.6`, `DUALMIND_TIMEOUT` = `300`, `DUALMIND_LESSON_INJECT` = `8`,
`DUALMIND_PRICE_IN` / `_OUT` = `15` / `75`. Config also reads
`${DUALMIND_HOME:-$HOME/.dualmind}/config.json` and `~/.config/dualmind/config.env`;
environment wins. Full details in [`references/config.md`](references/config.md).

## Usage

```bash
# 0. lessons first -- DualMind's first step on every trigger
python3 scripts/dualmind_cli.py lessons list --limit 10

# 1. should this be escalated?
python3 scripts/dualmind_cli.py score --files-estimated 4 --ambiguity 0.5 --high-risk migration
# [DualMind] evaluating escalation score 0.52 <= 0.60 -> stay_local

# 2. escalate: get the plan, milestones and acceptance criteria
python3 scripts/dualmind_cli.py start \
  --task "Add a TTL cache layer with tests; acceptance: TTL expiry by an injected clock,
          bounded maxsize with the evicted key asserted, suite green" \
  --context-file cache.py --files-estimated 4 --ambiguity 0.4 \
  --session .dualmind/session-cache

# 3. work milestone m1, then report it
python3 scripts/dualmind_cli.py report --session .dualmind/session-cache --result-file r-m1.md
# [DualMind] milestone 1/3 sent for review (m1)
# [DualMind] verdict: approve for milestone m1

# 4. stuck? hand over the failure
python3 scripts/dualmind_cli.py stuck --session .dualmind/session-cache \
  --reason "eviction test passes but the key order is wrong" --attempts 2

# 5. inspect, or write the report by hand
python3 scripts/dualmind_cli.py status --session .dualmind/session-cache
python3 scripts/dualmind_cli.py finish --session .dualmind/session-cache
```

Exit codes are the loop control: `0` continue · `0` + `DONE` finished · `10` blocked ·
`11` round budget exhausted · `12` invalid advisor JSON after one repair retry · `2`–`6`
config/network/auth/model/HTTP failures.

Every round is persisted under the session directory (`transcript.json`,
`round-NN-request.json`, `round-NN-response.json`, `retrospective-*.json`,
`report.md`, `report.json`) so a run can be inspected afterwards.

## Lessons and the AGENTS.md guarantee

Lessons are recorded at user level, in `${DUALMIND_HOME:-$HOME/.dualmind}/experience/`, and are
injected into advisor requests while the skill is active. The location is validated, not just
documented: pointing the store inside the skill package or inside a git repository is refused.

**DualMind never creates, reads for write, or modifies any `AGENTS.md`, `CLAUDE.md`, or global
Codex/Claude configuration file.** This is enforced by a guard every write passes through
(`dualmind/agents_md.py`), not merely promised in prose. Your `~/.codex/AGENTS.md` is
untouched; lessons apply only while the skill is active. See
[`references/experience.md`](references/experience.md).

## Comparison

DualMind sits in the same family as a few other plugins that hand work from one agent to a
stronger model. The contrast is in **how the handoff is decided and bounded**. Facts below come
only from each project's README; full sourcing and fetch date in
[`references/comparison-sources.md`](references/comparison-sources.md).

| | DualMind | sendbird/cc-plugin-codex | openai/codex-plugin-cc | BeehiveInnovations/pal-mcp-server |
|---|---|---|---|---|
| Direction | executor → advisor | Codex → Claude Code | Claude Code → Codex | host agent → many providers |
| Decided by | computed score vs. configurable threshold | user command, or optional turn-end gate | user command, or optional gate | host agent / user picks a tool |
| Milestones with acceptance criteria | yes; loop cannot end until criteria are met | not mentioned in README | not mentioned in README | not mentioned in README |
| Token / cost report with savings estimate | yes | not mentioned in README | not mentioned in README | not mentioned in README |
| Learns across sessions | user-level lesson store, never an AGENTS.md | not mentioned in README | not mentioned in README | not mentioned in README |
| Extra requirements | none beyond the API | — | ChatGPT subscription or OpenAI API key, Node 18.18+ | MCP host plus provider keys |

Two design decisions, stated plainly:

1. **No turn-end gate.** Both Codex/Claude bridge plugins offer an optional gate that reviews
   after edit-producing turns; their READMEs warn about usage drain, which is why it is off by
   default. DualMind never fires on a turn boundary — it scores the task, so cost is bounded by
   the decision rather than by how often you happened to edit a file.
2. **Completion is defined by criteria.** None of the three READMEs mentions a milestone
   acceptance loop. DualMind cannot stop on the advisor's say-so alone.

## Testing

```bash
bash tests/run_tests.sh
```

Runs the whole skill end to end under a temporary `HOME` and `CODEX_HOME`, against a local
mock server on a random port. No real API is contacted. Covers every failure exit code,
scoring below/above the threshold and with custom weights, the full milestone loop to `DONE`,
`stuck` re-escalation, the automatic retrospective, lesson merge/prune, the report's token sums
and savings, progress lines on stderr, key non-leakage, and an install/uninstall/run cycle that
asserts no `AGENTS.md` was created or modified anywhere under the temp home.

## Layout

```
SKILL.md                              the skill instructions the agent loads
agents/openai.yaml                    interface metadata + implicit-invocation policy
install.sh                            installer: local, or curl | bash from a tarball
references/config.md                  environment variables, config file, precedence
references/triggers.md                escalation scoring: signals, weights, threshold
references/experience.md              the lesson store, and what it never touches
references/advisor-system-prompt.md   the advisor's system prompt (sent every round)
references/comparison-sources.md      sourced facts behind the comparison table
scripts/dualmind_cli.py               the CLI (thin entry point)
scripts/check_config.py               config validation + judged ping (kept working)
scripts/advisor.py                    back-compat wrapper over the CLI
scripts/mock_server.py                local Anthropic-compatible server for tests
scripts/dualmind/                     the package:
    config.py       env/config.json/config.env loading, constants, errors
    client.py       the Messages API client (urllib)
    schema.py       the advisor JSON contract: extraction, validation, normalisation
    scoring.py      escalation scoring: signals -> score -> decision
    session.py      transcript, per-round artefacts, token accounting
    loop.py         one round in, one decision out; milestones, completion, retrospective
    experience.py   the user-level lesson store: merge, prune, rank, render
    agents_md.py    the guard that refuses to touch any AGENTS.md
    report.py       tokens, cost estimate, savings
    status.py       session state rendering, protected-file audit
    io.py           file helpers, context loading, [DualMind] progress lines
    check_config.py the config checker implementation
    fixtures.py     scripted advisor replies for the mock server and examples
    cli.py          the command line
examples/minimal/                     worked TTL-cache example + mock_rounds.json
tests/run_tests.sh                    end-to-end test suite
```
