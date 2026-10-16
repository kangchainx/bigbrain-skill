# Comparison sources

Facts about three neighbouring projects, used only for the comparison table in
[`../README.md`](../README.md). Each entry was taken from the project's GitHub README.

**Fetched: 2026-10-16.**

Where a README does not mention something, the table says *not mentioned in README* rather
than claiming the feature is absent — a README is not a specification, and an omission there
is not proof that a capability does not exist.

## sendbird/cc-plugin-codex

A plugin that runs inside Codex and uses Claude Code / Claude models.

- Commands: `$cc:review`, `$cc:adversarial-review`, `$cc:rescue` (hand a task to Claude Code;
  `--model` defaults to `opus`), `$cc:status` / `$cc:result` / `$cc:cancel`, `$cc:setup`.
- Background tracked jobs.
- Optional turn-end review gate, **disabled by default**; verdicts `ALLOW` / `BLOCK`. The
  README warns that every edit-producing turn can trigger a Claude call and drain usage
  limits, and notes a 15-minute timeout.
- Invocation is user-commanded, or the gate. **Not mentioned in README:** complexity-based
  auto-escalation scoring, a milestone/acceptance-criteria loop, or a token-savings report.

## openai/codex-plugin-cc

The reverse direction: a Claude Code plugin that calls Codex.

- Commands: `/codex:review`, `/codex:adversarial-review`, `/codex:rescue`, `/codex:transfer`,
  status / result / cancel, setup, and an optional review gate.
- Requires a ChatGPT subscription or an OpenAI API key, Node 18.18+.
- Invocation is user-commanded, or the gate. **Not mentioned in README:** auto-escalation
  scoring, a milestone/acceptance-criteria loop, a token-savings report.

## BeehiveInnovations/pal-mcp-server

An MCP server connecting Claude Code / Gemini CLI / Codex CLI to many providers (OpenRouter,
Gemini, OpenAI, Azure, X.AI, Ollama, custom).

- Tools include `clink` (CLI-to-CLI subagents), `chat`, `thinkdeep`, `planner`, `consensus`,
  `debug`, `precommit`, `codereview`, `refactor`, `testgen`, `secaudit`, and others.
- The README lists "Auto model selection — Claude picks the right AI for each task", and
  conversation continuity across tools.
- Consults are tool calls chosen by the host agent or the user. **Not mentioned in README:**
  a configurable weighted escalation threshold, a milestone acceptance loop, or a savings
  report.

## What the table is actually contrasting

DualMind sits in the same family as these three — an agent handing work to a stronger model —
so the table is about **how the handoff is decided and bounded**, not about which is better:

| Axis | DualMind | cc-plugin-codex | codex-plugin-cc | pal-mcp-server |
|------|----------|-----------------|-----------------|----------------|
| Direction | executor → advisor | Codex → Claude Code | Claude Code → Codex | host agent → many providers |
| Decided by | computed score vs. configurable threshold | user command, or turn-end gate | user command, or gate | host agent / user picks a tool |
| Bounded by | milestones with acceptance criteria; loop ends only when criteria are met | not mentioned in README | not mentioned in README | not mentioned in README |
| Reports tokens and cost | yes, with a savings estimate | not mentioned in README | not mentioned in README | not mentioned in README |
| Grows across sessions | user-level lesson store, never an AGENTS.md | not mentioned in README | not mentioned in README | not mentioned in README |

Two differences are worth stating plainly, because they are the design decisions rather than
feature gaps:

1. **The gate is inverted.** cc-plugin-codex and codex-plugin-cc offer an optional turn-end
   gate that fires a review after edit-producing turns; their READMEs warn about usage drain,
   which is why it is off by default. DualMind never fires on a timer or a turn boundary — it
   scores the task and escalates on a threshold, so the cost is bounded by the decision, not
   by how many times you happened to edit a file.
2. **Completion is defined by criteria, not by the advisor's word.** None of the three READMEs
   mentions a milestone loop. DualMind's loop cannot end on `status=done` alone: every
   acceptance criterion must be marked met, and a `done` without that keeps looping.
