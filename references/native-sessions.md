# Persistent Claude task sessions

One Bigbrain task directory owns one native Claude session. On its first live
call Bigbrain allocates a UUID and passes `--session-id`; later calls, including
repairs and retrospectives, use `--resume` with exactly that UUID. No `--continue`,
fork or automatic replacement is used. This is persistent history, not a resident
process. The CLI still has only Read/Glob/Grep, safe-mode, no custom MCP/skills,
and its own login. The task directory, original workspace, task hash and chat
owner are checked; invoking a command from another directory still uses the
original workspace. Moving/copying a bound task directory is not a supported
migration. `start --force` cannot overwrite a bound task.

The implementation borrows lifecycle ideas from
[claude-session-driver](https://github.com/obra/claude-session-driver) without its
tmux workers or permission bypass, and accounting guidance from Anthropic's
[session-report](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/session-report).
See also the official [session](https://code.claude.com/docs/en/agent-sdk/sessions)
and [cost](https://code.claude.com/docs/en/agent-sdk/cost-tracking) references.

## Context

Native sessions retain conversation and tool results. Subsequent Bigbrain turns
send new evidence and a reasserted task contract (original task, acceptance
criteria, current milestone, user corrections). The old Bigbrain head/tail
truncation is not used for live persistent turns; API/mock behavior is unchanged.
The initial system prompt is pinned. New system-policy/lesson changes need a new
task; they do not silently rewrite an ongoing conversation. Claude handles native
auto-compaction; `compact_boundary` events are counted. Reattach images needed
for a fresh visual comparison: persistence does not guarantee every old image
survives native compaction. Full history still has context/token costs.

Legacy nonpersistent tasks bootstrap a new native session once with their full
stored history. Metadata explicitly records `migrated_from_nonpersistent`; old
ephemeral session IDs are not claimed to be resumable. The old spend remains in
the task total. Mock calls and standalone configuration probes stay separate.

## Recovery

Mutating commands use a nonblocking OS file lock from before transcript reads
through commit. Locks release on process exit; stale lock *files* are harmless.
This implementation targets macOS/Linux (POSIX flock and directory fsync).

`claude-session.json` binds the native ID. `claude-journal.json` contains the
current operation, pre-application snapshot, exact input and terminal receipts.
`claude-receipts/` retains per-operation usage and metadata (including paid
failures and repairs) after the active journal advances, without prompt text.
Files and transcript commits use atomic replacement and fsync. The transcript
commits its usage and operation ID together. These private files contain context;
do not publish them. Do not edit them to bypass a recovery block.

```bash
python3 scripts/bigbrain_cli.py status --session /absolute/task-dir --json
python3 scripts/bigbrain_cli.py recover --session /absolute/task-dir
```

- A captured terminal result can be applied locally without another CLI call.
  Recovery also works if the first turn died before creating transcript.json.
  Repeating recovery after commit does not count the result again.
- Recovery does not automatically launch a retrospective or an unsent repair.
- An unknown outcome (no terminal receipt) blocks ordinary calls and recovery.
  Inspect the native session and retained journal before deciding what to do;
  there is intentionally no automatic resend, reset or replacement shortcut.
- Missing native history or a changed binding is an error, never a fresh start.
  The verified missing-session envelope (`num_turns=0`, `duration_api_ms=0`,
  explicit matching session ID error) is classified separately from unknown
  outcomes: its zero startup cost does not reset the prior cumulative baseline.
  Restore native history to retry that ID. If deliberately abandoning the task,
  use a new task directory; status prints the old ID and an example new path.
- CLI errors with a captured result retain their measured usage. Unknown work
  stays flagged rather than reported as free. Read-only status does not repair
  or mutate state; a later mutating command can finish a local commit marker.

## Accounting

On the verified CLI, `result.total_cost_usd` and `modelUsage` are cumulative across
resumes, while `result.usage` is invocation-local. Record the difference between
successive known cumulative costs, and count invocation usage once per durable
operation. Do not also sum assistant usage blocks or replayed native transcripts.
Missing, decreasing or unanchored cumulative amounts are flagged unknown, not
guessed. Preserve both raw cumulative values and applied deltas in receipt
metadata. The fields are CLI estimates, not subscription billing.

The offline audit flags uncommitted native operations; its recorded totals are
only a lower bound until recovery. UUIDs, compaction counts and migration state
are available in `status --json`. A CLI upgrade should rerun the two-turn canary
to verify the accounting convention before treating totals as complete.
