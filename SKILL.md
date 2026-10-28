---
name: bigbrain
license: MIT
description: Opt-in Claude collaboration for the current chat. Use only when the user explicitly requests Bigbrain for this chat or task. New chats default off. Discussing Bigbrain, complex work or repeated failures does not authorize activation.
---

# Bigbrain

## Chat activation comes first

Bigbrain is OFF by default in every Codex chat. Only an explicit request to use
Bigbrain authorizes `python3 <skill>/scripts/bigbrain_cli.py mode on`. A question
about Bigbrain, a bug report about it, complexity or repeated failures is NOT
opt-in. Check with `mode status`; on "disable Bigbrain for this chat", run
`mode off` immediately and stop applying its workflow, role labels and cost footer.
Do not make a final advisor call just to turn it off. Ordinary Codex behavior resumes.

The switch uses CODEX_THREAD_ID, not repository cwd or the native Claude session
ID. Resume/compaction of the same chat preserves it; a new/forked chat defaults off.
Missing/corrupt state is off, and missing chat identity must never select another
chat. In a terminal without CODEX_THREAD_ID, `mode --chat-id ID` can inspect/set
an explicit chat; regular standalone CLI use remains explicit manual invocation.
The hook reads this switch and emits nothing when off. Live workflow commands in
Codex also reject disabled chats, even if old hook instructions remain in context.
Disabling does not delete task history or interrupt an already running process.

All workflow instructions below, including automatic escalation within the task,
apply ONLY after this chat has opted in. Enabling here never enables another chat.

You are the **executor**. Claude Code CLI (selected with `setup --claude-code`, default model alias `opus`) plans,
helps with planning and diagnosis. Codex reviews code by default; after reporting
its review, ask whether the user wants an optional Claude second review. Only an
explicit yes (or an already explicit request for that review) authorizes the call.
This policy overrides generic Claude review/acceptance steps below for code-review
work; enabling Bigbrain alone does not authorize second review. Escalate complex work to it in a milestone loop, act on each
instruction, and report back — instead of stopping to ask the user for every decision.

## Everyday interaction

Bigbrain is part of doing the user's task, not a report-producing task of its own.
Keep advisor plans, milestone evidence and session reports internal. Do not create,
open, attach or link a separate report unless the user explicitly asks for one.
The `report` command sends evidence to the advisor; it does not ask the user to read it.
Finish with the result, relevant verification, any remaining blocker, and the
task's Claude advisor cost and token usage, briefly. Always relay the terminal `cost_summary`
or `[Bigbrain] Claude Code advisor cost` / `Claude advisor API cost` line in the final user-facing reply,
including on failure. State input tokens (including cache), output tokens, and
total tokens alongside cost. Use the backend-reported counts, not the executor's
estimated tokens; label mock counts as simulated. Sum advisor costs and tokens
across sessions used for the same task;
do not sum repeated cumulative summaries from one session. Include the currency
and label it **estimated**: the CLI backend uses Claude Code’s reported cost, which
is not proof of an actual subscription charge. The legacy API backend uses configured
token prices. Neither reads the provider’s bill.
Use advisor cost only, not the executor estimate or savings comparison. Preserve
warnings about missing usage; unknown totals are not $0 or zero tokens. Mock/dry-run
calls have no provider charge. If no advisor call was made, say so (cost $0,
0 provider tokens).

Show short progress messages in the conversation when the advisor starts (include
the actual model), a meaningful milestone changes, a review requests revisions,
or the run completes or fails. Command stderr may be collapsed by the host UI,
so do not rely on `[Bigbrain]` logs alone. Use actual tool results, not invented
progress or private reasoning. Do not repeat unchanged status or expose the full plan.

Read and follow [visible collaboration](references/collaboration.md): use short,
first-person progress updates prefixed `**Codex**：` or `**Claude**：` in the conversation.
For example, Codex reports "我把改动交给 Claude 复查了"; after a real review result,
Claude's finding can be paraphrased as "我发现恢复流程还漏了一个边界情况".
These are attributed status summaries, not verbatim quotes or independent chat
messages. Replace stage-title banners such as "Claude | 最终验收通过。他……" with
natural first-person sentences. Include concrete reasons and verification evidence;
never invent activity, findings, private reasoning or simulated back-and-forth.

When closing a user-facing turn, if Claude made a concrete contribution during
that turn (for example, found an extra defect or supplied a diagnosis that helped
resolve the problem), end with one short, playful sentence naming that contribution.
Use the user's language and an informal, task-specific image or joke, not a formal
"collaboration summary" heading or a fixed catchphrase. Ground it in actual replies
and results: distinguish finding a problem from fixing it, and do not invent credit,
claim hypothetical savings, or repeat an earlier turn's credit as new. A routine
approval alone does not need a punchline. If there was no substantive contribution,
omit the sentence; never call Claude just to generate it. Keep required outcomes,
limitations and cost information before this closing line.

User testing and feedback are instructions to improve the experience, not a reason
to ask them to manage the advisor loop or inspect diagnostic files.

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

When selecting Claude Code CLI for the first time, use the existing Claude Code
login; do not ask for an API key. On later tasks, only the no-call check is needed:

```bash
python3 <skill>/scripts/bigbrain_cli.py setup --claude-code
python3 <skill>/scripts/check_config.py --no-call --json
```

Setup verifies login and saves only Bigbrain's backend selection. A no-call check
verifies login, not generation. A real start/review verifies model access. If login
is missing, ask the user to run `claude auth login`; never collect credentials in chat.
Use `BIGBRAIN_CLAUDE_MODEL` for an explicit CLI model; the default is `opus`.
Show the actual model ID from request metadata when it is available.
Do not silently fall back to the API if CLI execution fails.

The CLI advisor has only Read/Glob/Grep tools, with custom hooks, skills and MCP
servers disabled. Codex runs tests and sends diffs/output. Bigbrain binds one persistent Claude session to each task and resumes its explicit
ID, sending only new evidence plus the task contract. It never resumes the latest
session by directory. Follow [native session recovery](references/native-sessions.md);
use `status` then `recover` for a captured result, and never blindly resend an unknown outcome.
Always reuse this chat's explicit Bigbrain session directory. Existing sessions
retain their original backend/model even if the user's configuration changes.

**The following API setup flow applies only to the legacy `api` backend.**

If the user asks to configure or replace credentials, enter the configuration
flow below directly; do not probe the old endpoint first.

When installing/reinstalling this skill or handling its first activation after
installation, run `python3 <skill>/scripts/check_config.py --no-call --json` first.
If a local configuration exists, show only its provider, exact model and source,
then offer **reuse this configuration** or **configure again** before sending a
provider request. Installation alone is not consent to silently reuse an old model.
Do not show the key, including its masked suffix. If no configuration exists, open
the setup form. An explicit configuration choice already made in the conversation
satisfies this step; do not ask again on each task, turn or milestone.

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

**Code-review exception:** Codex performs the review and reports its findings
first, then asks whether the user wants Claude to review again. Do not automatically
escalate code review based on scoring, an enabled chat, a prior Claude plan, or a
commit skill. Follow [the optional second-review policy](references/collaboration.md#codex-review-first-claude-second-review-is-optional).
Only after explicit consent, reuse the bound session (`report --force` if DONE),
or use `start --force` if there is no bound session. Do not run paid acceptance
or retrospective calls merely to finish a Codex-only review.

Score it:

```bash
python3 <skill>/scripts/bigbrain_cli.py score \
  --files-estimated 4 --ambiguity 0.4 --high-risk migration
```

Prints `[Bigbrain] evaluating escalation score 0.49 <= 0.60 -> stay_local`. Escalate when the
decision is `escalate`; do the work locally when it is `stay_local`. `--user-request` forces
escalation when the user explicitly asked for the advisor. Weights and the threshold are
configurable — see `references/triggers.md`.

## Step 3 — the milestone loop

Choose reasoning effort yourself from the task and current evidence; do not ask
the user to choose a level. Default to **medium (中)** for clear, bounded work.
Use **high (高)** for difficult diagnosis, cross-module tradeoffs, or security,
concurrency and migration reasoning. Reserve **xhigh (超高)** for unusually
complex, tightly coupled problems or unresolved failures after a high-effort
attempt. File count alone and an explicit request for Bigbrain do not justify
raising effort. Never use `low` or `max`; **xhigh is the ceiling**.

Pass the selected level with `--effort medium|high|xhigh` on `start`, and on
`report` or `stuck` when the difficulty changes. Omission on a new session means
medium; later commands retain the session level. Mention the selected level
briefly when starting or changing it. Repair retries and retrospective use that
level too. The CLI backend passes `--effort` explicitly. The API backend sends
`thinking.type=adaptive` and `output_config.effort` explicitly; `max_tokens` is an API-backend output cap; CLI output limits are managed by Claude Code. If a provider rejects
these parameters, report the incompatibility rather than silently dropping them,
changing models, or claiming that the requested effort took effect.

**1. Open the session.** Round 1 returns the global acceptance criteria, the milestones
(3-ish, each with its own steps and acceptance criteria), and any questions.

```bash
python3 <skill>/scripts/bigbrain_cli.py start \
  --task "<what must change, and the acceptance criteria>" \
  --context-file path/to/relevant.py --context-file path/to/design.md \
  --effort medium \
  --session .bigbrain/session-<name>
```

**Answer its questions with evidence.** Claude Code can inspect the tree; the legacy
API backend sees only supplied context. Codex still runs all checks. Never
bounce those questions to the user unless they are genuinely about intent.

**2. Work one milestone at a time.** Do its steps in order, run every step's `verify`
command, and record the real output.

### Visual tasks: send pixels

For animation, video, UI or image work with visual acceptance criteria, attach
reference images during planning and current rendered screenshots/frames during
each visual milestone review. Use repeatable `--image-file path.png` on `start`,
`report` or `stuck`. A path inside prose, code, or `--context-file` does not show
the advisor the image. The CLI embeds actual image bytes in Messages image blocks.

For videos, extract timestamped keyframes and ordered frames around motion,
transitions and state changes; label reference versus output and timestamps in
the report. Attach readable full-resolution frames when contact sheets obscure
details. Do not pass an MP4 or animated GIF as proof of motion: only static images
are reviewed (GIF/WebP animation contributes only its first frame). A useful report:

```bash
python3 <skill>/scripts/bigbrain_cli.py report \
  --session .bigbrain/session-animation --result-file visual-review.md \
  --image-file reference-22s.png --image-file output-22s.png \
  --image-file output-21s.png --image-file output-23s.png
```

The original reference images and the current round's attachments survive history
compression; intermediate rounds' images may be omitted. Reattach older output
frames when a comparison needs them. Images are stored in local request/transcript
artifacts and sent to the configured provider. Keep each image under 5 MB after
base64 encoding (3.75 MB file size) and the full request under 30 MB; resize or
select fewer frames when needed. Do not silently omit rejected images or fall back
to text-only approval. If pixels cannot be sent, report visual review as unverified.
API-reported input usage includes image tokens; do not add a guessed image count
on top of it or claim sampled frames prove complete video playback.

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

**5. Repeated debugging or missed goals:** judge the trajectory and evidence, not
keywords. If the same goal remains unmet across edit/verify cycles and Claude has
not engaged, `start --force` with the attempts and evidence before another speculative
edit. If its current plan is disproven, use `stuck` in the same session. A user
correction that invalidates acceptance uses `feedback`, even after DONE:

```bash
python3 <skill>/scripts/bigbrain_cli.py feedback --session .bigbrain/session-<name> \
  --reason "<user's exact correction>" --failure-file observed-evidence.txt
```

This invalidates previous acceptance evidence, retains the correction across
history compression and opens a new bounded round budget. The diagnosis round
cannot complete the task. Follow the returned plan, then submit fresh evidence
with `report` for Claude's review. If diagnosis fails, retry feedback after
resolving the failure; do not edit first or claim approval. Do not wait for two
failed fixes. New unrelated requests are new tasks, not corrections.

**6. Repeat** from step 2 until the loop ends.

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
session directory for internal diagnostics. Do not surface these files by default.
The terminal JSON includes a compact `cost_summary`, also printed on stderr,
after the retrospective so its usage is included. Always relay that cost to the
user, without opening the report. On an interrupted/failed run, use the cost line
or `finish --session DIR --no-retrospective --json` to read recorded spend without
making another advisor call. Use the detailed report only when the user asks.

## Example

```bash
python3 scripts/check_config.py                                  # OK
python3 scripts/bigbrain_cli.py lessons list --limit 10          # step 0
python3 scripts/bigbrain_cli.py score --files-estimated 4 --ambiguity 0.4 --user-request
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

`--dry-run` prints the prepared context/settings (CLI backend) or exact API payload
without launching Claude, sending a request or writing the session.
`--mock FILE` (or `BIGBRAIN_MOCK`) replays scripted advisor replies from a JSON list. Both
are for testing only — never present a mock run as a real advisor review.

## Files

- `references/config.md` — every environment variable and the config file
- `references/triggers.md` — escalation scoring: signals, weights, threshold
- `references/experience.md` — the lessons store, and what it deliberately never touches
- `references/advisor-system-prompt.md` — the advisor's system prompt (sent each round)
- `scripts/bigbrain_cli.py` — the CLI: `score`, `start`, `report`, `stuck`, `feedback`, `finish`, `status`, `lessons`, `setup`
- `scripts/setup.py` — the setup wizard on its own (same as `bigbrain_cli.py setup`)
- `scripts/check_config.py`, `scripts/advisor.py` — kept working; thin wrappers over the CLI
- `scripts/bigbrain/` — the package: config, client, schema, scoring, session, loop,
  experience, agents_md, report, status, cli
