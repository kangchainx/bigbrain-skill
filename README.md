<div align="center">
  <h1>Bigbrain</h1>
  <p><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português (Brasil)</a></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

Bring Claude into your Codex chat for planning and diagnosis. Codex writes the code, runs the checks and reviews the result. You decide when to invite a second opinion.

![Codex builds. Claude helps you think it through.](docs/assets/hero.en.png)

**Off by default, enabled per chat.** After you opt in, difficult tasks can trigger Claude planning or diagnosis. **Claude code review is optional and requires an explicit request.**

## Why Bigbrain

| When you need… | Bigbrain helps by… |
|---|---|
| A plan before a costly change | Turning an unclear task into milestones with checkable acceptance criteria. |
| A way out of repeated failures | Giving Claude the failed attempts and evidence to diagnose the next move. |
| Continuity without losing control | Keeping a task-bound Claude session, local lessons and visible advisor cost estimates. |

## Get started

You need Codex, Python 3 and a signed-in Claude Code CLI that supports `--safe-mode` (tested with 2.1.310). Bigbrain itself uses only the Python standard library. Commands below run from the checkout.

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

If Claude Code is not signed in, run `claude auth login` first. Setup selects the backend; the no-call check verifies login, not model access. The first real advisor request verifies generation.

Then, in your Codex chat, say:

> Use Bigbrain for this chat. Help me plan this change before implementing it.

To stop, say **“Disable Bigbrain for this chat.”** Resuming the same chat preserves the switch; a new or forked chat starts off. Installing the skill does not activate it.

<details>
<summary>Other installation options</summary>

With the skills CLI, choose Codex as the target. Then ask Codex to configure Bigbrain with Claude Code; it should use the installed skill’s path, not assume the checkout exists.

```bash
npx skills add kangchainx/bigbrain-skill
```

From the checkout, `./install.sh --copy` installs a copy instead of a symlink; `--claude` also installs for Claude Code; `--dir PATH` chooses a destination. The default is `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`. Keep a symlinked checkout in place.

</details>

## One task, clear roles

![How the roles fit together · illustrative diagram](docs/assets/flow.en.png)

<p align="center"><a href="docs/assets/demo.en.mp4"><img src="docs/assets/demo.en.gif" alt="Watch the 24-second conversation with music (MP4). Scripted illustration." width="960"></a></p>

[Watch the 24-second conversation with music (MP4). Scripted illustration.](docs/assets/demo.en.mp4)

*How the roles fit together · illustrative diagram*

1. **You opt in.** Complexity alone never enables Bigbrain in an off chat.
2. **Claude advises when needed.** Within an enabled chat, a score above `0.6` escalates planning work; an explicit advisor request can also escalate. Simple work stays with Codex.
3. **Codex executes and reviews.** It edits files, runs checks and performs the first code review. A Claude second review needs your explicit request.
4. **Evidence carries forward.** Feedback can reopen a task for diagnosis and fresh evidence. Advisor runs record tokens and an estimated cost.

## Choose your advisor backend

|  | Claude Code · recommended | Messages API · alternative |
|---|---|---|
| Authentication | Claude Code’s own login | Your provider’s API key |
| Model | `BIGBRAIN_CLAUDE_MODEL` (default: `opus`) | `BIGBRAIN_MODEL` (default: `claude-opus-5-5`) |
| Context | Persistent native session per task; Read/Glob/Grep only | Context supplied by Codex |
| Cost | Claude Code’s reported estimate | Returned usage × configured token prices |

Existing tasks keep their backend and model. Configurations without a backend retain `api` for compatibility. There is **no silent fallback** between backends. Model access depends on your account or endpoint.

<details>
<summary>Configure a Messages API provider</summary>

From the checkout, open the local setup form. Enter the HTTPS endpoint, API key and model there, never in chat. The form lists the endpoint’s models and must pass a real generation check before saving.

```bash
python3 scripts/bigbrain_cli.py setup --web
```

API-only: streaming and transient-error retries. The provider must support the requested model and thinking/effort parameters; Anthropic-shaped JSON alone does not guarantee compatibility. `BIGBRAIN_BASE_URL` omits the trailing `/v1`. Environment variables override saved settings. See [configuration](references/config.md).

</details>

## Your session, your controls

- **Separate responsibilities.** The Claude Code advisor is limited to Read/Glob/Grep and launched with `--safe-mode`, an empty strict MCP configuration and slash commands disabled. Codex owns edits and test execution.
- **Local state.** Lessons live in `~/.bigbrain/experience/`; task records live under `.bigbrain/` in the workspace. Relevant context and attached images are sent to the selected advisor. Local storage does not mean offline inference.
- **No global instruction edits.** Bigbrain does not modify `AGENTS.md`, `CLAUDE.md` or global Codex/Claude configuration. Setup writes Bigbrain’s own config.
- **Visible usage.** Advisor cost is an estimate, not a provider bill or proof of a subscription charge. Missing usage is flagged. Savings comparisons also estimate executor tokens, so they are not a benchmark.

## For hands-on users

Normally Codex runs the workflow for you. From the checkout, these commands inspect the chat switch or an existing task without calling the advisor:

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>Advanced advisor loop</summary>

After explicit opt-in, use one session directory for the task. These commands make advisor calls; `m1.md` must contain your actual results and verification evidence.

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

In the advisor milestone loop, `done` is accepted only when every acceptance criterion is marked met. This does **not** make Claude approval mandatory for a Codex-only code review. Defaults: 8 rounds; reasoning effort `medium`, with `high` and `xhigh` available. Terminal runs normally include a retrospective call. Exit codes: `0` continue / `DONE`; `10` blocked; `11` round budget exhausted; `12` invalid advisor JSON after repair; `2`–`6` configuration or provider errors.

</details>

<details>
<summary>Optional Codex plugin hooks</summary>

The repo includes a local plugin marketplace. From a checkout, register it with the commands below, then review and trust its hooks in Codex. Disable the standalone skill entry to avoid duplicate discovery. The skill installer does not register or trust hooks.

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart and UserPromptSubmit remind Codex of the collaboration rules only in enabled chats. Hooks make no model calls and do not enforce every conversational rule. See [collaboration](references/collaboration.md) and [session recovery](references/native-sessions.md).

</details>

## A few practical questions

**Will it call Claude for every task?**

No. Off means no new workflow advisor calls. In an enabled chat, simple tasks can stay local. Turning it off does not interrupt an already running request.

**Can I try the mechanics without calling a model?**

Run `bash examples/minimal/run.sh` from the checkout. It uses scripted replies: a walkthrough, not a real review.

**How do I check the installation’s code?**

Run `bash tests/run_tests.sh`. The suite uses temporary directories and local mocks, not live provider calls.

**How do I uninstall?**

From the checkout, run `./install.sh --uninstall`. Lessons are kept. Add `--purge` only if you also want to delete the user-level Bigbrain store.

## Go deeper

[Configuration & backends](references/config.md) · [Escalation rules](references/triggers.md) · [Sessions & recovery](references/native-sessions.md) · [Local lessons](references/experience.md) · [Offline cost audit](references/session-audit.md) · [Contributing](CONTRIBUTING.md)

---

Created by **Chris Kang** ([@kangchainx](https://github.com/kangchainx)).

[MIT](LICENSE) · © 2026 Chris Kang. If you build on Bigbrain, a link back to this repository is appreciated.
