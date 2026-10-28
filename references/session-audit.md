# Internal collaboration audit

Run weekly (the user selected this cadence). Scheduling is handled by the host's
thread automation, not by the plugin hooks or this script. The script itself is
offline, read-only and does not call Claude, load credentials or change settings.

```bash
python3 scripts/audit_sessions.py <session-directory-or-root> [more-paths ...]
```

Paths are explicit. A root scans only direct children containing transcript.json or native session/journal files.
Resolved paths are deduplicated. Mock sessions are excluded, including rounds
marked mock. Invalid/missing data is flagged; partial recorded spend is separate
from the complete total, which is null when unknown. API sessions have unknown
CLI cost: the audit does not guess API prices. Cache tokens are already included
in input tokens; do not add them again. No task text, prompts or credentials are
printed. Exit 0 means the audit ran, not that all records were complete.

These are lifetime snapshots of selected sessions, not spend during a date range
or the account's bill. A weekly reviewer may save a private snapshot under
`${BIGBRAIN_HOME:-$HOME/.bigbrain}/audits/` outside the skill source/install tree.
Compare successive snapshots by resolved session path; count
only increments for existing sessions, and identify newly discovered historical
sessions separately. Never sum cumulative snapshots. Flag missing/reset/deleted
sessions and incomplete totals. Coverage is limited to explicitly selected roots;
do not call a partial sample the user's total Claude spend.

Review cost, input/output and cache tokens, calls by kind (including repairs and
retrospectives), recorded done status, unmet criteria, feedback events and
revise/reject reviews. Feedback count is not a true reopen count; done status is
not proof of user acceptance. Historical records do not reliably measure when
Claude should have intervened. Sample the available task evidence for repeated
failed attempts and whether Claude engaged before another speculative edit.

Optimise in this order: remove duplicate/stale context, focus repo inspection on
the needed decision, batch related evidence into a review, and choose effort for
the difficulty of that decision. Preserve original requirements, failing evidence,
current diff, necessary visual evidence and fresh acceptance checks. Never save
tokens by delaying a necessary diagnosis or treating an unreviewed task as done.

Use comparable tasks and examine acceptance and feedback/return-to-debugging
alongside cost. Do not claim savings from a cheaper run alone. Each proposed
change records its hypothesis, sample, quality guardrail and measured before/after
results; small samples remain inconclusive. Do not automatically change the model,
effort, escalation or acceptance rules. Weekly statistics do not require Claude;
request a focused Claude review only when there is a concrete collaboration
problem to diagnose, and include that call in the next cost snapshot.

Persistent CLI sessions use cumulative cost deltas and operation receipts; see
[native session accounting](native-sessions.md). An unsettled native journal
makes the total unknown until safely recovered, even if older rounds are complete.

Sessions with native state/journals but no transcript (for example, a crash after
the first paid result) are included as unsettled, unknown-cost sessions. Their
presence makes the aggregate total unknown until local recovery completes.
