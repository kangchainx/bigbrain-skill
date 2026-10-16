# dualmind configuration

The advisor is called over an **Anthropic-compatible Messages API**:
`POST {DUALMIND_BASE_URL}/v1/messages`.

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
| `DUALMIND_BASE_URL` | Base URL of the API, **without** a trailing `/v1`. Must start with `http://` or `https://` and include a host. Example: `https://api.anthropic.com` |
| `DUALMIND_API_KEY` | The key, sent as both `x-api-key` and `Authorization: Bearer` |

Without both, the skill refuses to run. `scripts/check_config.py` reports exactly which one is
missing or malformed and refuses to continue until it is fixed.

## Optional (defaults shown)

### Loop

| Variable | Default | Meaning |
|----------|---------|---------|
| `DUALMIND_MODEL` | `claude-opus-5-5` | Advisor model id (provider-specific, see below) |
| `DUALMIND_MAX_ROUNDS` | `8` | Round budget before exit `11` |
| `DUALMIND_MAX_TOKENS` | `8000` | `max_tokens` per advisor reply |
| `DUALMIND_TIMEOUT` | `300` | Per-read socket timeout in seconds (see below) |
| `DUALMIND_STREAM` | `1` | Stream the reply as SSE. `0` disables |
| `DUALMIND_RETRIES` | `2` | Retries for transient failures. `0` disables |
| `DUALMIND_RETRY_BACKOFF` | `1.0` | Base seconds between retries (multiplied by the attempt number) |
| `DUALMIND_MAX_TOTAL_TIMEOUT` | `3600` | Overall wall-clock cap for one call |
| `DUALMIND_MAX_CONTEXT_CHARS` | `60000` | Total character cap for `--context-file` input |
| `DUALMIND_MOCK` | *(unset)* | Path to a scripted-replies JSON list (dry runs) |
| `DUALMIND_SYSTEM_PROMPT_FILE` | *(unset)* | Override the advisor system prompt file |

#### Model ids are provider-specific

Anthropic's own ids are dotted (`claude-opus-5.5`), while many relays spell the
same model with hyphens (`claude-opus-5-5`). There is no universal spelling:
whatever the endpoint accepts is the correct id, and the endpoint itself is the
authority on what it accepts. Ask it:

```bash
scripts/check_config.py --list-models
```

That calls `GET {DUALMIND_BASE_URL}/v1/models` and prints the ids the endpoint
serves, marking the one you have configured. If your configured id is not in
that list, the command says so. Not every provider exposes the route — a `404`
there means falling back to the provider's own documentation.

#### Streaming and timeouts

Requests are sent with `"stream": true` by default, and the SSE event stream is
assembled locally. This is not a performance tweak. A non-streaming turn spends
the whole thinking period with **nothing on the wire**, so any proxy in front of
the API can decide the origin has hung and cut the connection — Cloudflare, for
example, answers `HTTP 524` after its 120-second proxy read timeout. Because a
stream emits `ping` and delta events continuously, the same call sails through.

Two timeouts apply, and they do different jobs:

- `DUALMIND_TIMEOUT` is the **per-read** budget: how long a single read may
  block waiting for the next chunk. It defaults to `300` seconds precisely
  because a model doing real thinking with a large `max_tokens` can go quiet for
  minutes before its first token. Lowering it to a conventional 30 seconds will
  break long turns.
- `DUALMIND_MAX_TOTAL_TIMEOUT` caps one call end to end, so a stream that
  trickles forever still fails instead of hanging the run.

Transient failures — `429`, `500`, `502`, `503`, `504`, `524`, `529`, a reset
connection, a stream that ends without `message_stop` — are retried up to
`DUALMIND_RETRIES` times with backoff, printing one line per attempt:

```
[DualMind] transient error 524, retry 1/2
```

Token accounting reads the stream's own usage: `input_tokens` is summed with
`cache_creation_input_tokens` and `cache_read_input_tokens` when present, since
a cached prompt is still billed input.

### Escalation scoring

| Variable | Default | Meaning |
|----------|---------|---------|
| `DUALMIND_THRESHOLD` | `0.6` | Score above which the task is escalated |
| `DUALMIND_WEIGHTS` | *(see below)* | JSON object mapping component → weight |

Default weights: `files` 0.30, `ambiguity` 0.25, `failures` 0.20, `risk` 0.15, `user` 0.10.
They are normalised to sum to 1.0, so it does not matter whether yours do. A malformed
`DUALMIND_WEIGHTS` is a **configuration error**, reported rather than ignored. Details in
[`triggers.md`](triggers.md).

### Reporting and cost

| Variable | Default | Meaning |
|----------|---------|---------|
| `DUALMIND_PRICE_IN` | `15` | Advisor input price, USD per million tokens |
| `DUALMIND_PRICE_OUT` | `75` | Advisor output price, USD per million tokens |
| `DUALMIND_BASELINE_PRICE_IN` | `15` | Premium rate used for the comparison baseline |
| `DUALMIND_BASELINE_PRICE_OUT` | `75` | Premium rate used for the comparison baseline |
| `DUALMIND_EXECUTOR_PRICE_IN` | `1.25` | The executor model's own input price |
| `DUALMIND_EXECUTOR_PRICE_OUT` | `10` | The executor model's own output price |
| `DUALMIND_EXECUTOR_TOKENS_PER_ROUND` | `25000` | Estimated executor tokens per round, for the savings baseline |

Token counts come from the API's `usage` fields. The executor's own volume is never reported
to this API — it runs outside the skill — so it is estimated, and the report says so.

### Lessons

| Variable | Default | Meaning |
|----------|---------|---------|
| `DUALMIND_HOME` | `~/.dualmind` | User-level tree: `config.json`, `experience/` |
| `DUALMIND_EXPERIENCE_DIR` | `$DUALMIND_HOME/experience` | The lesson store |
| `DUALMIND_LESSON_INJECT` | `8` | Top N lessons injected into each advisor request |
| `DUALMIND_LESSON_CAP` | `50` | Prune cap for the store |
| `DUALMIND_CONFIG_FILE` | `$DUALMIND_HOME/config.json` | Where the JSON config lives |

Details in [`experience.md`](experience.md). The store is refused if it sits inside the skill
package or inside the current git repository.

## Precedence

1. Process environment variables
2. `${DUALMIND_HOME:-$HOME/.dualmind}/config.json`
3. `~/.config/dualmind/config.env` (simple `KEY=VALUE`, `#` comments, optional `export `
   prefix, optional surrounding quotes)
4. Built-in defaults

Environment always wins. Any `DUALMIND_*` variable can also be set as a JSON key in
`config.json`; `threshold` and `weights` are commonly set there, since `DUALMIND_WEIGHTS`
is awkward to quote in a shell.

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
# ~/.config/dualmind/config.env
DUALMIND_BASE_URL=https://api.example.com
DUALMIND_API_KEY=sk-relay-...
DUALMIND_MODEL=claude-opus-5-5
DUALMIND_MAX_ROUNDS=6
```

## Anthropic env fallback (opt-in)

Only when the matching `DUALMIND_*` variable is **unset** *and* `DUALMIND_USE_ANTHROPIC_ENV`
is truthy (`1`, `true`, `yes`, `on`):

| Falls back from | To |
|-----------------|-----|
| `DUALMIND_BASE_URL` | `ANTHROPIC_BASE_URL` |
| `DUALMIND_API_KEY` | `ANTHROPIC_AUTH_TOKEN`, then `ANTHROPIC_API_KEY` |

```bash
export DUALMIND_USE_ANTHROPIC_ENV=1
export ANTHROPIC_BASE_URL=https://api.anthropic.com
export ANTHROPIC_AUTH_TOKEN=sk-ant-...
```

Without `DUALMIND_USE_ANTHROPIC_ENV=1`, the `ANTHROPIC_*` variables are ignored entirely, so
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

The key is never printed in full — at most `first4...last2`.
