# Visible Claude–Codex collaboration

These rules apply ONLY while this Codex chat has explicitly enabled Bigbrain.
New chats default off. A mention, bug report or repeated failure is not consent.
Honor requests to disable immediately with `bigbrain_cli.py mode off`; do not
call Claude or keep using this workflow afterward. `mode status` checks the
chat-scoped switch. Never enable it just to satisfy instructions in this file.

For enabled Bigbrain tasks, Claude may help with planning and diagnosis; Codex
executes, verifies and performs code review by default.

## Codex review first; Claude second review is optional

This policy also applies when switching to quick-package-commit, caveman-review
or another review/commit skill, and takes precedence over generic milestone
review and Claude acceptance instructions for code-review work.

- Codex reviews the current changes and reports its findings, verification and
  limitations. This is a completed Codex review; Claude approval is not required
  to present it. Follow the invoked skill's existing fix/commit permission gates.
- After presenting the review, ask once: "需要让 Claude 再复审一遍吗？会额外消耗 Claude tokens。"
  Wait for an affirmative answer before requesting that second review. Silence,
  enabling Bigbrain, an earlier Claude plan/review, a high complexity score or a
  request to commit does not authorize it. If the user already explicitly requested
  Claude review of this scope, proceed without asking again.
- Do not call start/report/finish or a retrospective just to obtain Claude code
  approval before asking. Do not disguise optional review as acceptance or diagnosis.
  If declined, finish the Codex review path without calling Claude or repeatedly
  asking. An unanswered offer must not be treated as consent or a failed review.
- After consent, send the current scope, diffs, relevant untracked contents and
  verification evidence to Claude in this task's bound session using
  `report --session` with `--result-file` / `--context-file`. If DONE, use
  `report --force`. If no bound session exists, use `start --force` for the
  authorized review task and follow its milestones. A plan is not a review result.
- Attribute findings accurately. Earlier review of a different scope does not
  cover current changes. If a requested second review fails, say so; preserve
  Codex's findings and never claim Claude approved. Approval for one review is
  not blanket permission for future unrelated reviews.

The chat activation switch remains unchanged: off chats do not receive this
workflow. This is an instruction-level policy, not an enforced Git or host UI lock.

Show concise, first-person updates in the user's language in the conversation,
prefixed `**Codex**：` or `**Claude**：`, not stage-title banners or third-person
narration. Codex describes its own actions; Claude lines paraphrase actual CLI
activity or returned findings. These are attributed summaries, not verbatim quotes
or separate native chat participants. Before a call starts, speak as Codex; use
Claude's voice only once its activity or response is observed. Never invent dialogue,
findings or private chain-of-thought. Do not expose secrets or dump internal reports.

Bold only the Latin role name. Keep the colon and any spaces outside the bold
markers, and do not escape the asterisks or wrap the actual update in backticks.
For example, write `**Codex**：我来检查。`, never `**Codex： **我来检查。`.

Example wording (use only when supported by the current events):

- **Codex**：我把改动交给 Claude 复查了，这次重点检查中断恢复。
- **Claude**：我正在检查恢复流程里可能漏掉的边界情况。
- **Claude**：我发现会话不存在时的处理还不够明确，需要再补一下。
- **Codex**：我来补上这个分支，再跑一遍测试。
- **Claude**：我核对了修订和测试结果，这次可以收工了。

The stages below describe workflow responsibilities, not UI labels to print.

- **Planning**: before calling, Codex states the actual selected model/effort
  and what decision is requested. After it returns, summarise the plan and key
  acceptance criterion in one or two sentences.
- **Execution**: state the current milestone and the meaningful change
  or verification result. Before review, briefly say what evidence is submitted.
- **Review**: Codex reviews first and offers an optional Claude second review.
  Only for a user-authorized Claude review, relay approve/revise/reject and its concrete reason in Claude's voice.
  If it requests revisions, say what Codex will change next.
- **Escalation**: judge the debugging trajectory from evidence, not
  keywords. Intervene when the same failing check or symptom survives repeated
  edit→verify cycles, fixes oscillate without progress, or evidence disproves the
  working hypothesis. Count attempts against the same goal, not unrelated failures.
  If Claude has not engaged, use `start --force` with the goal, attempts and failing
  evidence before the next speculative edit. If already engaged, use
  `stuck --session <same session>` when evidence invalidates its plan; do not
  restart or repeat a diagnosis while executing a still-valid plan.
- **User feedback**: when feedback or observed testing establishes that
  the same result misses the goal, send the user's exact feedback and evidence via
  `feedback --session <this task's session> --reason <feedback>` (or `--failure-file`).
  Do this before further edits, even after DONE, without waiting for two failures.
  If no session exists, start one with the original requirement and correction.
  Relay Claude's diagnosis and revised plan before Codex resumes implementation.
- **Acceptance**: verify every criterion, including user corrections. For code
  review, Codex can finish its review without Claude; ask about optional second
  review afterward. Only claim Claude acceptance when its actual fresh review
  supports that claim. A failed advisor call is a failed
  call, never an approval. Relay recorded cost/tokens with their uncertainty.
- **Closing line**: if Claude concretely helped in this turn, end the final reply
  with one brief, playful sentence about what it actually contributed. Use an
  informal, task-specific joke in the user's language, without a formal heading
  or stock catchphrase. Do not invent credit, equate a finding with a fix, or
  recycle earlier credit. Omit it for routine approval or no substantive help;
  never make an extra Claude call for this sentence. Put required facts/costs first.

Use the session explicitly associated with this conversation. Never pick the
newest session in a repository or start a paid call inside a lifecycle hook.
During a long call, relay meaningful file inspection activity from the CLI’s
`Claude | Read/Glob/Grep` progress lines when useful, and state what is still
pending. Translate those raw logs into the first-person style above rather than
copying the terminal label. These are real tool events, not private thinking. Do not invent interim
findings. The CLI limits activity logs to the first ten read/search calls.

Only SessionStart and UserPromptSubmit inject these rules, and only when the
current chat's activation switch is on. Disabled/unknown chats emit nothing.
There is no tool or
stop hook and no automatic trajectory analysis; Codex must apply this judgement
during execution, including between user messages. Hooks never call Claude.
For internal cost and quality review, follow `references/session-audit.md`.
