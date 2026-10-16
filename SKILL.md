---
name: bigbrain
description: Escalate complex or large coding work to an Opus advisor that plans, reviews and keeps pushing until the acceptance criteria are met. Use for large features, multi-file changes, refactors across module boundaries, ambiguous requirements, migrations, security or concurrency work, or when a previous attempt failed twice. Do NOT use for one-line fixes, typos, formatting, or explain-only questions.
---

# Bigbrain

You are the **executor**. A separate advisor model (default `claude-opus-5-5`) plans,
reviews and directs. Escalate complex work to it in a milestone loop, act on each
instruction, and report back — instead of stopping to ask the user for every decision.

## Step 0 — always, before anything else: load your lessons

```bash
python3 <skill>/scripts/bigbrain_cli.py lessons list --limit 10
```

This prints the highest-ranked lessons from your previous sessions **on this machine**.
Read them and follow them while Bigbrain is active. They are how this skill learns: a
correction you needed last week should not need to be made again.

Lessons live in a user-level store (`~/.bigbrain/experience/`) and are injected into every
advisor request automatically. **No code path in this skill ever creates, reads for write,
or modifies any `AGENTS.md`, `CLAUDE.md`, or global Codex/Claude configuration file.** Your
own global `~/.codex/AGENTS.md` is untouched by design; lessons apply only while this skill
is active. See `references/experience.md`.

## Step 1 — hard prerequisite: configuration must pass

If the user asks to configure or replace credentials, enter the configuration
flow below directly; do not probe the old endpoint first.

```bash
python3 <skill>/scripts/check_config.py
```

- Exit `0` and prints `OK` → proceed.
- Exit `2` (not configured), or the user asks to configure/change the API → follow
  [configuration](references/config.md#configuration-in-codex). Start
  `python3 <skill>/scripts/bigbrain_cli.py setup --web` and keep the process running.
  It prints a `setup_url`; open that exact URL in the Codex in-app browser using
  `open_in_codex` (browser target), or provide the link if that tool is unavailable.
- Configuration is part of the skill's local form, **one step at a time**:
  HTTPS API address → API key in a **password input** → model choice. Never collect
  keys through Codex's ordinary question tool or chat text; it has no password field.
  Do not launch the terminal wizard unless the user specifically requests it.
- The form fetches the endpoint's complete model catalogue before offering a model.
  When the exact id `claude-opus-5-5` is present, recommend **Claude Opus 5.5** and put
  the remaining ids under **Other models**. If absent, let the user choose from the
  catalogue; never invent, map or substitute an Opus id. Do not dump every model
  into the initial choice screen.
- A catalogue is not proof of successful generation. The form validates the selected
  model with one tiny real Messages request; only success saves configuration. Never
  save after a failed validation or silently switch providers/keys/models.
- Let the user fill the password field themselves. Do not inspect its value, take DOM
  snapshots while it contains a real key, or echo credentials into messages/logs.
  The browser sends them only to the local helper, which uses the chosen HTTPS API.
  No key is put in the page URL or browser storage. The helper exits after save/cancel
  or 15 minutes; if it expires, start it again and open the new URL.
- Wait for the helper's final `saved` result, or inspect only non-secret config fields
  after the user reports completion. Report any `environment_overrides`; do not claim
  the saved file is effective when environment variables still override it.
- Any other exit code → **do not escalate**. Tell the user which variable is wrong (the
  checker names it) and what to set. Never invent, guess or echo an API key, and never
  continue with a partially configured advisor.

If the check fails, finish the task yourself as best you can, or report the blocker.

## Step 2 — should this be escalated at all?

Score it:

```bash
python3 <skill>/scripts/bigbrain_cli.py score \
  --files-estimated 4 --ambiguity 0.4 --high-risk migration
```

Prints `[Bigbrain] evaluating escalation score 0.72 > 0.60 -> escalate`. Escalate when the
decision is `escalate`; do the work locally when it is `stay_local`. `--user-request` forces
escalation when the user explicitly asked for the advisor. Weights and the threshold are
configurable — see `references/triggers.md`.

## Step 3 — the milestone loop

**1. Open the session.** Round 1 returns the global acceptance criteria, the milestones
(3-ish, each with its own steps and acceptance criteria), and any questions.

```bash
python3 <skill>/scripts/bigbrain_cli.py start \
  --task "<what must change, and the acceptance criteria>" \
  --context-file path/to/relevant.py --context-file path/to/design.md \
  --session .bigbrain/session-<name>
```

**Answer its questions by reading the repository yourself** — it cannot see your tree. Never
bounce those questions to the user unless they are genuinely about intent.

**2. Work one milestone at a time.** Do its steps in order, run every step's `verify`
command, and record the real output.

**3. Report each milestone for review** — not the whole task:

```bash
python3 <skill>/scripts/bigbrain_cli.py report \
  --session .bigbrain/session-<name> --result-file report-m1.md
```

Include: steps completed, files changed with a diff summary, the **verbatim** test/verify
output, answers to `questions_for_executor`, and anything that failed. The advisor returns
one verdict for that milestone: `approve`, `revise` or `reject`.

**4. If you cannot make progress**, re-escalate with the failure rather than retrying blindly:

```bash
python3 <skill>/scripts/bigbrain_cli.py stuck --session .bigbrain/session-<name> \
  --reason "the eviction test passes but the key order is wrong" \
  --failure-file failing-output.txt --attempts 2
```

**5. Repeat** from step 2 until the loop ends.

## How the loop ends

Read the **exit code** — that is the control signal:

| Exit | Meaning | Do this |
|------|---------|---------|
| `0` with `"status":"continue"` | Normal round | Do the plan, then `report` again |
| `0` and the word `DONE` printed | `status=done` **and every acceptance criterion met** | Stop and summarise for the user |
| `10` | Blocked; `blocked_reason` on stderr | Stop and tell the user — this is a real blocker |
| `11` | Round budget exhausted | Stop, summarise progress and what remains, ask the user |
| `12` | Advisor returned invalid JSON twice | Stop, report the malformed reply |
| `2`–`6` | Config/network/auth/model/HTTP failure | Report it; do not retry blindly |

`status=done` alone does **not** end the loop: the advisor must also mark every criterion
met in `criteria_status`. A `done` with unproven criteria continues, with a note on stderr.

When the loop ends for any reason, Bigbrain runs a **retrospective** automatically (one more
advisor call), saves the lessons it returns, and writes `report.md` + `report.json` into the
session directory. You do not need to trigger it; to do it by hand, use `finish`.

## Example

```bash
python3 scripts/check_config.py                                  # OK
python3 scripts/bigbrain_cli.py lessons list --limit 10          # step 0
python3 scripts/bigbrain_cli.py score --files-estimated 4 --ambiguity 0.4
# -> escalate
python3 scripts/bigbrain_cli.py start \
  --task "Add a TTL cache layer to cache.py with tests; acceptance: TTL expiry by an \
          injected clock, bounded maxsize with the evicted key asserted, suite green" \
  --context-file cache.py --session .bigbrain/session-cache
# -> milestones m1/m2/m3 + global criteria
python3 scripts/bigbrain_cli.py report --session .bigbrain/session-cache --result-file r-m1.md
# -> verdict approve for m1
# ... continue per milestone; on a revise, fix exactly what it named ...
python3 scripts/bigbrain_cli.py report --session .bigbrain/session-cache --result-file r-m3.md
# -> status=done, all criteria met -> DONE, retrospective, report written
```

Fuller walkthrough: `examples/minimal/README.md`.

## Offline / dry-run

`--dry-run` prints the exact request payload without sending it or writing the session.
`--mock FILE` (or `BIGBRAIN_MOCK`) replays scripted advisor replies from a JSON list. Both
are for testing only — never present a mock run as a real advisor review.

## Files

- `references/config.md` — every environment variable and the config file
- `references/triggers.md` — escalation scoring: signals, weights, threshold
- `references/experience.md` — the lessons store, and what it deliberately never touches
- `references/advisor-system-prompt.md` — the advisor's system prompt (sent each round)
- `scripts/bigbrain_cli.py` — the CLI: `score`, `start`, `report`, `stuck`, `finish`, `status`, `lessons`, `setup`
- `scripts/setup.py` — the setup wizard on its own (same as `bigbrain_cli.py setup`)
- `scripts/check_config.py`, `scripts/advisor.py` — kept working; thin wrappers over the CLI
- `scripts/bigbrain/` — the package: config, client, schema, scoring, session, loop,
  experience, agents_md, report, status, cli
