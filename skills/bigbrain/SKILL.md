---
name: bigbrain
license: MIT
description: Opt-in Claude collaboration for this chat only. Use only on explicit user request to enable or use Bigbrain. New chats default off; discussing Bigbrain, complex tasks and repeated failures do not authorize activation.
---

Read [the Bigbrain workflow](../../SKILL.md), starting with its chat activation
gate. Only after explicit opt-in, run `python3 ../../scripts/bigbrain_cli.py mode on`
(resolve this path against this skill directory). To disable, use `mode off`.
Never enable automatically while answering questions about Bigbrain itself.
The plugin root is two directories above this file. In that workflow, `<skill>`
means the plugin root: scripts are at `../../scripts/` and references at
`../../references/`. Keep workflow instructions in that single source.

While enabled, Codex reviews code first, including when another review or commit
skill is invoked. After reporting findings, ask whether the user wants an optional
Claude second review; call Claude only after explicit consent for that review.
Follow [visible collaboration](../../references/collaboration.md#codex-review-first-claude-second-review-is-optional).
