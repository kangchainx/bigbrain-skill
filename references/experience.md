# Lessons: how Bigbrain learns, and what it never touches

Bigbrain gets better at working with you by recording **lessons** — short, general,
actionable notes about how you like work done and where the executor tends to slip — and
feeding them back into the advisor the next time you escalate.

## What it deliberately never does

**No code path in this skill creates, reads for write, or modifies any `AGENTS.md`
(global or project), `CLAUDE.md`, or any global Codex/Claude configuration file.**

This is enforced, not merely promised. Every write the package makes goes through
`bigbrain/io.py`, which calls `bigbrain/agents_md.py:guard_write` first; a write targeting a
protected instruction file raises instead of succeeding. There is no pin/unpin feature and no
"remember this in AGENTS.md" path, because that is not where lessons belong:

- those files are committed and shared, so a lesson about *you* would leak to everyone
  who clones the repo, and would outlive the session that produced it
- they apply unconditionally, while a lesson learned about one task may be wrong for the
  next one
- they are the user's own configuration, and a skill has no business editing them silently

Your `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md` are **untouched**. Lessons apply only
while the Bigbrain skill is active. An audit surface exists so this is checkable rather than
taken on faith:

```bash
python3 scripts/bigbrain_cli.py status --audit ~/.codex     # names + sha256, read-only
```

## Where lessons live

A **user-level** directory, never inside a repository or inside the skill package:

```
${BIGBRAIN_HOME:-$HOME/.bigbrain}/experience/
    lessons.jsonl    one lesson per line
    lessons.md       a generated digest, grouped by kind (do not edit by hand)
```

Override the directory with `BIGBRAIN_HOME` (the whole user-level tree) or
`BIGBRAIN_EXPERIENCE_DIR` (just the store). The location is **validated, not documented**:
pointing it inside the skill package or inside the current git repository is refused, with an
error telling you to set `BIGBRAIN_HOME`. A lessons file that lands in a repo gets committed;
the whole point is that this store is yours, on this machine.

## The lesson record

```json
{
  "id": "l2610161312451234",
  "text": "When asking for eviction, require the test to name the evicted key.",
  "kind": "codex_shortcoming",
  "source_session": ".bigbrain/session-cache",
  "scope": "global",
  "confidence": 0.9,
  "created_at": "2026-10-16T13:12:45",
  "last_used_at": "2026-10-16T13:12:45",
  "uses": 0
}
```

`kind` is one of:

| Kind | Meaning |
|------|---------|
| `codex_shortcoming` | the executor missed, overclaimed, or needed the same correction twice |
| `user_preference` | something you expressed or implied about how work should be done |
| `workflow` | a process lesson about the loop itself: plan shape, when to demand evidence |

`scope` is `global` or `repo:<name>`. Selection prefers the matching repo scope, then
`global`. `confidence` is 0–1, set by the advisor from how strong the evidence was.

## How lessons get in

1. **`lessons load` is the first step of the skill.** SKILL.md tells the executor to run
   `bigbrain_cli.py lessons list --limit 10` before anything else, and to follow what it
   prints while Bigbrain is active.
2. **Automatic injection.** The top N lessons are appended to the advisor's system prompt on
   every request, so the advisor plans with them in mind. Injected lessons have their `uses`
   counter bumped and `last_used_at` refreshed.
3. **Saved from advisor replies.** The advisor may return `lessons[]` in any round, and the
   retrospective at the end of every run returns them by design. They are merged into the
   store each round.

## Merging, pruning and ranking

- **Merge.** A new lesson whose normalised text is at least 0.85 similar (difflib ratio) to an
  existing one in the same scope merges into it: confidence is bumped by 0.10, the id and
  creation time are kept, and the longer wording wins. So repeatedly noticing the same thing
  makes one strong lesson, not fifty weak ones.
- **Prune.** The store is capped (default 50, `BIGBRAIN_LESSON_CAP`) by
  `confidence × recency`, where recency halves every 30 days since `last_used_at`. Lessons you
  keep seeing stay; lessons that stopped mattering fade out.
- **Rank.** Selection is the same score, so what gets injected is what is both trusted and
  current.

## Commands

```bash
python3 scripts/bigbrain_cli.py lessons list --limit 10        # top lessons, ranked
python3 scripts/bigbrain_cli.py lessons list --json            # machine-readable
python3 scripts/bigbrain_cli.py lessons add "Prefer unittest over pytest here" \
    --kind user_preference --confidence 0.8
python3 scripts/bigbrain_cli.py lessons prune --cap 50         # trim to the cap
python3 scripts/bigbrain_cli.py lessons export --out lessons.md
```

`list` accepts `--limit` (0 = all) and `--scope`; `add` accepts `--from-file FILE` to read the
text from a file. `export` writes the generated Markdown digest somewhere else, or prints it.

## Configuring

| Variable | Default | Meaning |
|----------|---------|---------|
| `BIGBRAIN_HOME` | `~/.bigbrain` | user-level tree containing `config.json` and `experience/` |
| `BIGBRAIN_EXPERIENCE_DIR` | `$BIGBRAIN_HOME/experience` | the lesson store itself |
| `BIGBRAIN_LESSON_INJECT` | `8` | how many top lessons go into each advisor request |
| `BIGBRAIN_LESSON_CAP` | `50` | prune cap |

## Uninstalling

`install.sh --uninstall` removes the skill and **keeps** the experience store, because those
lessons are yours and outlast the skill. `--purge` removes `$BIGBRAIN_HOME` too — that is the
only thing that deletes your lessons, and it has to be asked for explicitly.
