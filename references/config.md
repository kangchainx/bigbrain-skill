# bigbrain configuration

The advisor is called over an **Anthropic-compatible Messages API**:
`POST {BIGBRAIN_BASE_URL}/v1/messages`.

Every request sends both auth headers, because relays differ in which one they check:

```
content-type: application/json
anthropic-version: 2023-06-01
x-api-key: <key>
Authorization: Bearer <key>
```

## Required

| Variable | Meaning |
|----------|---------|
| `BIGBRAIN_BASE_URL` | Base URL of the API, **without** a trailing `/v1`. Setup requires `https://` and a host. Example: `https://api.anthropic.com` |
| `BIGBRAIN_API_KEY` | The key, sent as both `x-api-key` and `Authorization: Bearer` |

Without both, the skill refuses to run. `scripts/check_config.py` reports exactly which one is
missing or malformed, prints the setup command below, and refuses to continue until it is fixed.

## Configuration in Codex

Start the built-in local configuration form:

```bash
python3 <skill>/scripts/bigbrain_cli.py setup --web
```

Keep that process running. Its first stdout line is JSON containing `setup_url`.
Open that exact URL in the Codex in-app browser (`open_in_codex`, browser target).
If that UI tool is unavailable, give the user the link to open. This is the skill's
configuration UI, not an external hosted site or a terminal prompt.

The form has three steps:

1. **API address:** a URL input requiring `https://`, with matching server-side
   validation. Credentials, query strings and fragments in the URL are rejected.
   A trailing `/v1` is removed because the client appends API routes itself.
2. **API Key:** a password input, hidden from view. The user types it themselves;
   do not ask for it in chat or a normal Codex question box, and do not inspect
   the populated field through browser automation. It is never returned to the
   browser, put in a URL, logged, or saved to browser storage. The helper keeps
   it in memory until the configuration succeeds, is cancelled, or expires.
3. **Model:** after the full authenticated catalogue query succeeds, show
   **Claude Opus 5.5 (recommended)** only if `claude-opus-5-5` was returned. Other
   models stay under **Other models** until the user expands them. If the preferred
   id is absent, only the actual returned models are offered. Never guess aliases.
   A tiny Messages request validates the selected model before saving.

A public catalogue may return data even for an invalid key. Catalogue discovery
therefore does not prove the key can generate; successful generation is required
before saving. Discovery errors, missing models and failed probes leave the old
configuration intact. No bulk generation requests are needed to build the list.

The page uses a loopback HTTP server on a random port; **provider API URLs require
HTTPS**. The server binds only to `127.0.0.1`, requires the per-launch session token
and matching Origin/Host for writes, serves no external assets, and disables caching.
Credentials are sent only to that local server and the user's chosen HTTPS provider;
API redirects to a different origin or an insecure scheme are refused.
The page closes its configuration session after save/cancel; an unused server expires
after 15 minutes. On expiry, launch a new session instead of reusing the stale link.

The final stdout line reports `saved` plus the selected model and any
`environment_overrides`, never the key. A saved file is not necessarily the effective
configuration when an overriding environment variable is present. Saving only updates
`~/.bigbrain/config.json` (mode `600`, directory `700`), preserving unrelated fields.
No Codex/Claude configuration or `AGENTS.md` is modified.

### Programmatic helpers

`setup --list-models` and `setup --save` are also available for trusted local callers.
They read JSON with explicit `base_url`, `api_key` (and `model` for save) from stdin.
Pass it through a JSON serializer and subprocess stdin, never command-line arguments
or shell interpolation. These helpers do not authorize asking for a key in plain chat.
`--list-models` returns all catalogue ids, `recommended_model` (or null), and
`generation_verified: false`, without saving. `--save` rechecks catalogue membership,
probes that exact model, and only then writes configuration. Errors return nonzero.

## Terminal setup wizard

Available when explicitly requested, or from a manual interactive install:

```bash
python3 scripts/bigbrain_cli.py setup
```

It offers detected configuration with masked keys, or asks for an HTTPS address and
hidden key. After catalogue discovery it recommends Opus 5.5 when present, with other
models behind a separate choice. Failed validation offers retry, edit or abort, never
save-anyway. `install.sh --no-setup` skips the terminal prompt for scripted installs.

## Optional (defaults shown)

### Loop

| Variable | Default | Meaning |
|----------|---------|---------|
| `BIGBRAIN_MODEL` | `claude-opus-5-5` | Advisor model id (provider-specific, see below) |
| `BIGBRAIN_MAX_ROUNDS` | `8` | Round budget before exit `11` |
| `BIGBRAIN_MAX_TOKENS` | `8000` | `max_tokens` per advisor reply |
| `BIGBRAIN_TIMEOUT` | `300` | Per-read socket timeout in seconds (see below) |
| `BIGBRAIN_STREAM` | `1` | Stream the reply as SSE. `0` disables |
| `BIGBRAIN_RETRIES` | `2` | Retries for transient failures. `0` disables |
| `BIGBRAIN_RETRY_BACKOFF` | `1.0` | Base seconds between retries (multiplied by the attempt number) |
| `BIGBRAIN_MAX_TOTAL_TIMEOUT` | `3600` | Overall wall-clock cap for one call |
| `BIGBRAIN_MAX_CONTEXT_CHARS` | `60000` | Total character cap for `--context-file` input |
| `BIGBRAIN_MOCK` | *(unset)* | Path to a scripted-replies JSON list (dry runs) |
| `BIGBRAIN_SYSTEM_PROMPT_FILE` | *(unset)* | Override the advisor system prompt file |

#### Model ids are provider-specific

Model ids are provider-specific. Use the exact id returned by the endpoint;
do not infer aliases or translate punctuation. Inspect its catalogue with:

```bash
scripts/check_config.py --list-models
```

That calls `GET {BIGBRAIN_BASE_URL}/v1/models` and prints the ids the endpoint
serves, marking the one you have configured. If your configured id is not in
that list, the command says so. The setup form requires this catalogue: if the
route fails (including `404`), setup stops without saving. Check the provider's
documentation to correct the endpoint before retrying.

#### Streaming and timeouts

Requests are sent with `"stream": true` by default, and the SSE event stream is
assembled locally. This is not a performance tweak. A non-streaming turn spends
the whole thinking period with **nothing on the wire**, so any proxy in front of
the API can decide the origin has hung and cut the connection — Cloudflare, for
example, answers `HTTP 524` after its 120-second proxy read timeout. Because a
stream emits `ping` and delta events continuously, the same call sails through.

Two timeouts apply, and they do different jobs:

- `BIGBRAIN_TIMEOUT` is the **per-read** budget: how long a single read may
  block waiting for the next chunk. It defaults to `300` seconds precisely
  because a model doing real thinking with a large `max_tokens` can go quiet for
  minutes before its first token. Lowering it to a conventional 30 seconds will
  break long turns.
- `BIGBRAIN_MAX_TOTAL_TIMEOUT` caps one call end to end, so a stream that
  trickles forever still fails instead of hanging the run.

Transient failures — `429`, `500`, `502`, `503`, `504`, `524`, `529`, a reset
connection, a stream that ends without `message_stop` — are retried up to
`BIGBRAIN_RETRIES` times with backoff, printing one line per attempt:

```
[Bigbrain] transient error 524, retry 1/2
```

Token accounting reads the stream's own usage: `input_tokens` is summed with
`cache_creation_input_tokens` and `cache_read_input_tokens` when present, since
a cached prompt is still billed input.

### Escalation scoring

| Variable | Default | Meaning |
|----------|---------|---------|
| `BIGBRAIN_THRESHOLD` | `0.6` | Score above which the task is escalated |
| `BIGBRAIN_WEIGHTS` | *(see below)* | JSON object mapping component → weight |

Default weights: `files` 0.30, `ambiguity` 0.25, `failures` 0.20, `risk` 0.15, `user` 0.10.
They are normalised to sum to 1.0, so it does not matter whether yours do. A malformed
`BIGBRAIN_WEIGHTS` is a **configuration error**, reported rather than ignored. Details in
[`triggers.md`](triggers.md).

### Reporting and cost

| Variable | Default | Meaning |
|----------|---------|---------|
| `BIGBRAIN_PRICE_IN` | `15` | Advisor input price, USD per million tokens |
| `BIGBRAIN_PRICE_OUT` | `75` | Advisor output price, USD per million tokens |
| `BIGBRAIN_BASELINE_PRICE_IN` | `15` | Premium rate used for the comparison baseline |
| `BIGBRAIN_BASELINE_PRICE_OUT` | `75` | Premium rate used for the comparison baseline |
| `BIGBRAIN_EXECUTOR_PRICE_IN` | `1.25` | The executor model's own input price |
| `BIGBRAIN_EXECUTOR_PRICE_OUT` | `10` | The executor model's own output price |
| `BIGBRAIN_EXECUTOR_TOKENS_PER_ROUND` | `25000` | Estimated executor tokens per round, for the savings baseline |

Token counts come from the API's `usage` fields. The executor's own volume is never reported
to this API — it runs outside the skill — so it is estimated, and the report says so.

### Lessons

| Variable | Default | Meaning |
|----------|---------|---------|
| `BIGBRAIN_HOME` | `~/.bigbrain` | User-level tree: `config.json`, `experience/` |
| `BIGBRAIN_EXPERIENCE_DIR` | `$BIGBRAIN_HOME/experience` | The lesson store |
| `BIGBRAIN_LESSON_INJECT` | `8` | Top N lessons injected into each advisor request |
| `BIGBRAIN_LESSON_CAP` | `50` | Prune cap for the store |
| `BIGBRAIN_CONFIG_FILE` | `$BIGBRAIN_HOME/config.json` | Where the JSON config lives |

Details in [`experience.md`](experience.md). The store is refused if it sits inside the skill
package or inside the current git repository.

## Precedence

1. Process environment variables
2. `${BIGBRAIN_HOME:-$HOME/.bigbrain}/config.json`
3. `~/.config/bigbrain/config.env` (simple `KEY=VALUE`, `#` comments, optional `export `
   prefix, optional surrounding quotes)
4. Built-in defaults

Environment always wins. Any `BIGBRAIN_*` variable can also be set as a JSON key in
`config.json`, either under its full name (`BIGBRAIN_MODEL`) or its short lowercase form
(`model`); the full name wins if both are present. `threshold` and `weights` are commonly
set there, since `BIGBRAIN_WEIGHTS` is awkward to quote in a shell.

```json
{
  "model": "claude-opus-5-5",
  "max_rounds": 6,
  "threshold": 0.5,
  "weights": {"files": 0.25, "ambiguity": 0.25, "failures": 0.25, "risk": 0.15, "user": 0.10},
  "lesson_inject": 10,
  "prices": {"advisor_in": 15, "advisor_out": 75}
}
```

```ini
# ~/.config/bigbrain/config.env
BIGBRAIN_BASE_URL=https://api.example.com
BIGBRAIN_API_KEY=sk-relay-...
BIGBRAIN_MODEL=claude-opus-5-5
BIGBRAIN_MAX_ROUNDS=6
```

## Anthropic env fallback (opt-in)

Only when the matching `BIGBRAIN_*` variable is **unset** *and* `BIGBRAIN_USE_ANTHROPIC_ENV`
is truthy (`1`, `true`, `yes`, `on`):

| Falls back from | To |
|-----------------|-----|
| `BIGBRAIN_BASE_URL` | `ANTHROPIC_BASE_URL` |
| `BIGBRAIN_API_KEY` | `ANTHROPIC_AUTH_TOKEN`, then `ANTHROPIC_API_KEY` |

```bash
export BIGBRAIN_USE_ANTHROPIC_ENV=1
export ANTHROPIC_BASE_URL=https://api.anthropic.com
export ANTHROPIC_AUTH_TOKEN=sk-ant-...
```

Without `BIGBRAIN_USE_ANTHROPIC_ENV=1`, the `ANTHROPIC_*` variables are ignored entirely, so
the skill never picks up credentials the user did not intend it to use.

## Verifying

```bash
python3 scripts/check_config.py            # human output, prints OK + latency
python3 scripts/check_config.py --json     # machine output
python3 scripts/check_config.py --no-call  # format checks only, no network
```

The ping is judged, not merely received. An endpoint that answers a one-word `ping` with a
long paragraph of prose is reported as an unusable response (exit `6`) rather than `OK`: that
is not the model you configured, and finding out later wastes a whole run.

Exit codes: `0` OK · `2` missing/malformed config · `3` network/DNS/timeout · `4` auth
(401/403) · `5` model or endpoint not found (404) · `6` other HTTP error or unusable response.

The key is never printed in full — only masked as `****` plus its last 4 characters.
