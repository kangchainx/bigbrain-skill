# Escalation: scoring, weights and the decision

Escalate to the advisor when the work is likely to need architectural judgement, or when a
wrong first move would be expensive to unwind. Rather than a mental checklist that drifts
toward whatever is convenient, Bigbrain computes the decision:

```bash
python3 scripts/bigbrain_cli.py score --files-estimated 4 --ambiguity 0.5 --high-risk migration
# [Bigbrain] evaluating escalation score 0.52 <= 0.60 -> stay_local
# decision: stay_local
# score   : 0.52 (threshold 0.60)
# signals : 4 file(s) changed; ambiguity 0.50; high-risk: migration
```

Add `--explain` for the per-signal breakdown, `--json` for machine output.

## Signals

| Flag | Meaning | Raw value → component |
|------|---------|----------------------|
| `--files-changed N` | files actually changed | `min(1, N/5)` |
| `--files-estimated N` | files you expect to change (same component) | `min(1, N/5)` |
| `--ambiguity X` | 0–1, how ambiguous the requirement is | used as-is, clamped to 0–1 |
| `--consecutive-failures N` | prior failed attempts at this task | `min(1, N/3)` |
| `--high-risk TAG[,TAG]` | risky domain; repeatable | `1.0` if any tag is given, else `0.0` |
| `--user-request` | the user explicitly asked for the advisor | `1.0` if set, else `0.0` |

`--files-changed` and `--files-estimated` are the same component; passing both is an error.
Recognised `--high-risk` tags: `migration`, `delete`, `auth`, `infra`, `schema`, `secrets`,
`security`, `concurrency`, `payments`, `deploy`. An unrecognised tag still counts as
high-risk — the list documents intent, it does not gate the signal.

## Weights and the decision

Each component is multiplied by its weight; the weights are normalised to sum to 1.0, so
the score is always between 0 and 1 regardless of what you configure.

| Component | Default weight | Contributes at most |
|-----------|---------------|---------------------|
| `files` | 0.30 | 0.30 |
| `ambiguity` | 0.25 | 0.25 |
| `failures` | 0.20 | 0.20 |
| `risk` | 0.15 | 0.15 |
| `user` | 0.10 | 0.10 |

**Escalate when `score > threshold`**, default threshold `0.60`.

Without an explicit user request, the strict `>` matters: a task sitting exactly on
the threshold stays local. For example, five files, ambiguity 1.0 and a high-risk tag
score 0.30 + 0.25 + 0.15 = 0.70 and escalate. Four files alone score 0.24 and stay local.

`--user-request` alone scores 0.10 but forces an `escalate` decision in both `score`
and `start`, regardless of the threshold. It also records that the user requested the advisor.

## Configuration

Set these in `${BIGBRAIN_HOME:-$HOME/.bigbrain}/config.json`, in
`~/.config/bigbrain/config.env`, or in the environment. Environment wins.

```json
{
  "threshold": 0.5,
  "weights": {"files": 0.25, "ambiguity": 0.25, "failures": 0.25, "risk": 0.15, "user": 0.10}
}
```

```bash
export BIGBRAIN_THRESHOLD=0.45
export BIGBRAIN_WEIGHTS='{"files":0.5,"ambiguity":0.2,"failures":0.1,"risk":0.1,"user":0.1}'
```

A malformed `BIGBRAIN_WEIGHTS` is a configuration error, reported by `check_config.py` and by
the CLI, not silently ignored. All-zero weights fall back to the defaults with a warning.

Per-invocation overrides: `score --threshold 0.4`, `score --weights '{"files":1}'`.

## Using it from `start`

`start` scores the task before opening the session:

```bash
python3 scripts/bigbrain_cli.py start --task "..." --files-estimated 4 --ambiguity 0.6
```

Below the threshold it refuses (exit `2`) and says so, rather than spending advisor tokens
on a task you should just do. Override with `--user-request` or `--force`, or skip scoring
entirely with `--no-score`. The score, threshold, weights and reasons are recorded in the
transcript and printed in the end-of-run report.

## The old manual checklist, kept as guidance

The score encodes these; use them to pick the signal values honestly.

| Criterion | Signal |
|-----------|--------|
| Files touched >= 3 | `--files-estimated` |
| New module, package, endpoint, CLI or user-visible feature | `--ambiguity 0.5` at least, plus files |
| Refactor across module/package/layer boundaries, or moving public API | `--ambiguity 0.6` or `--high-risk infra` |
| Ambiguous requirements, or acceptance criteria unstated | `--ambiguity` |
| Risky domain: migration, schema, auth, secrets, concurrency, caching, performance | `--high-risk` |
| A prior attempt already failed twice | `--consecutive-failures 2` |
| The user asked for the advisor | `--user-request` |

## Never escalate

These stay local — no scoring needed, they score low anyway:

- one-line fixes and single-expression bug fixes
- typos, comments, docstring wording, formatting, lint or import ordering
- renaming a local variable, adding a log line
- explain-only questions ("what does this function do?", "why does this fail?")
- running a command the user already specified, or reading a file they named
- continued work inside an open session — that is a `report`, not a new `start`
- routine test runs, builds, `git status` / `log` / `diff`

## Borderline cases

- **Two files, one of them a test** → 0.12. Local.
- **One file, but concurrency or migration semantics** → high-risk only, 0.15. Escalate only
  if you are genuinely unsure of the correct semantics.
- **Mechanical refactor across 10 files, fully specified** → files 0.30. Local; the advisor
  adds nothing to a rename.
- **Spec is one sentence but implies a subsystem** → high ambiguity plus high-risk, easily
  over 0.60. Escalate.
- **You disagree with the user's requested approach and it is a large change** → escalate, and
  have the advisor argue the trade-off so the user gets a considered answer, not a refusal.

Record the score in the `start --task` text when you escalate — it helps the advisor
calibrate how much planning is warranted.
