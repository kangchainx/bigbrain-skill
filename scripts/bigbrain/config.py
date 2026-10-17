"""Configuration for the bigbrain skill.

Python 3 standard library only -- no third-party dependencies.

Precedence for every setting: process environment > ``~/.bigbrain/config.json``
> ``~/.config/bigbrain/config.env`` > built-in defaults.

Nothing in this module ever prints an API key.  Use :func:`mask_secret` for any
diagnostic output that needs to identify one.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

ANTHROPIC_VERSION = "2023-06-01"
#: Model ids are provider-specific.  Relays spell Anthropic ids with hyphens
#: (``claude-opus-5-5``), not the dotted form -- and every provider lists its
#: own catalogue at ``GET {base}/v1/models``.  See references/config.md.
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_ROUNDS = 8
#: Output budget for one advisor reply.  A real round-1 plan (3 milestones plus
#: global criteria) runs to several thousand tokens, and a reply that hits the
#: ceiling is cut off mid-JSON -- which costs a whole extra call to repair.  16k
#: leaves room for the plan *and* the thinking that precedes it.
DEFAULT_MAX_TOKENS = 16000

#: Ceiling for the automatic second attempt after a max_tokens truncation, when
#: the budget is doubled (see loop.run_round).  Stopping at 32k keeps a runaway
#: reply from costing an unbounded amount: past this, the answer is a *shorter*
#: reply, not a bigger budget.
DEFAULT_MAX_TOKENS_CAP = 32000
#: Socket read timeout.  This is a *per-read* budget, not a total-call budget:
#: a long thinking turn on a large max_tokens streams for minutes, and every
#: individual read between SSE events must be allowed to take this long.
DEFAULT_TIMEOUT = 300
DEFAULT_MAX_CONTEXT_CHARS = 60000

# Streaming (see client.post_messages).  A non-streaming call to a relay that
# sits behind a proxy read timeout can be cut off at 120s (HTTP 524) before the
# model finishes thinking, so streaming is on by default.
DEFAULT_STREAM = True
#: Retries for transient failures (429/5xx/524/529, resets, truncated streams).
DEFAULT_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 1.0
#: Overall wall-clock cap for one streamed call, on top of the per-read timeout.
DEFAULT_MAX_TOTAL_TIMEOUT = 3600

#: HTTP statuses worth retrying: rate limits and gateway/proxy failures.  A
#: 524 is Cloudflare's "origin did not respond in time" -- the request may well
#: succeed on a second attempt with streaming.
TRANSIENT_HTTP_STATUSES = (429, 500, 502, 503, 504, 524, 529)

# Escalation scoring (item 1).
DEFAULT_THRESHOLD = 0.6
DEFAULT_WEIGHTS = {
    "files": 0.30,
    "ambiguity": 0.25,
    "failures": 0.20,
    "risk": 0.15,
    "user": 0.10,
}
# Signal saturation points: the raw value at which the component reaches 1.0.
FILES_SATURATION = 5
FAILURES_SATURATION = 3
# Risk tags that count as high-risk, grouped for documentation.
RISK_TAGS = (
    "migration",
    "delete",
    "auth",
    "infra",
    "schema",
    "secrets",
    "security",
    "concurrency",
    "payments",
    "deploy",
)

# Report pricing (item 3), USD per million tokens.
DEFAULT_PRICE_IN = 15.0
DEFAULT_PRICE_OUT = 75.0
# "Everything to a single premium model" baseline used for the savings estimate.
DEFAULT_BASELINE_PRICE_IN = 15.0
DEFAULT_BASELINE_PRICE_OUT = 75.0
DEFAULT_EXECUTOR_PRICE_IN = 1.25
DEFAULT_EXECUTOR_PRICE_OUT = 10.0
# Tokens the executor plausibly spends per round on work the advisor never sees.
DEFAULT_EXECUTOR_TOKENS_PER_ROUND = 25000

# Top-N lessons injected into advisor requests (item 5).
DEFAULT_LESSON_INJECT = 8
DEFAULT_LESSON_CAP = 50
#: Two ways a new lesson is folded into an existing one.  ``LESSON_MERGE_RATIO``
#: is wording similarity (difflib) and applies within a scope; the lower
#: ``LESSON_JACCARD_RATIO`` compares the *token sets* and applies within a kind,
#: which catches reordered or padded restatements that difflib scores too low --
#: the same lesson written twice in different words is the common duplicate.
LESSON_MERGE_RATIO = 0.85
LESSON_JACCARD_RATIO = 0.6

CONFIG_ENV_FILE = Path(os.path.expanduser("~/.config/bigbrain/config.env"))

# Exit codes shared by every bigbrain entry point.
EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NETWORK = 3
EXIT_AUTH = 4
EXIT_MODEL = 5
EXIT_HTTP = 6
EXIT_BLOCKED = 10
EXIT_MAX_ROUNDS = 11
EXIT_BAD_JSON = 12

ADVISOR_STATUSES = ("continue", "done", "blocked")
ADVISOR_VERDICTS = ("approve", "revise", "reject", "n/a")
CRITERIA_STATES = ("met", "unmet", "unknown")
LESSON_KINDS = ("codex_shortcoming", "user_preference", "workflow")

_TRUEY = ("1", "true", "yes", "on")


class BigbrainError(Exception):
    """Fatal error carrying the process exit code that should be returned."""

    def __init__(self, message, exit_code=EXIT_HTTP, **extra):
        super().__init__(message)
        self.exit_code = exit_code
        self.extra = extra


class AdvisorParseError(BigbrainError):
    """The advisor reply could not be parsed or did not match the schema."""

    def __init__(self, message, errors=None):
        super().__init__(message, EXIT_BAD_JSON)
        self.errors = list(errors or [])


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------


def mask_secret(value):
    """Return a diagnostic-safe rendering of a secret.

    Never returns more than the last 4 characters (``****abcd``).  Short values
    reveal nothing at all, not even their length.
    """
    if not value:
        return "(unset)"
    text = str(value)
    if len(text) < 12:
        return "****"
    return "****%s" % text[-4:]


# --------------------------------------------------------------------------
# Small parsers
# --------------------------------------------------------------------------


def _strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_env_file(path):
    """Parse a simple KEY=VALUE file.  Missing files yield an empty mapping."""
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())
        if key:
            out[key] = value
    return out


def parse_json_file(path, problems=None, label="config"):
    """Read a JSON object from ``path``; return {} when absent or unusable."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        if problems is not None:
            problems.append("cannot read %s %s: %s" % (label, path, exc))
        return {}
    except ValueError as exc:
        if problems is not None:
            problems.append("%s %s is not valid JSON: %s" % (label, path, exc))
        return {}
    if not isinstance(data, dict):
        if problems is not None:
            problems.append("%s %s must contain a JSON object" % (label, path))
        return {}
    return data


def _as_bool(raw, name, problems, default):
    if raw is None or str(raw).strip() == "":
        return default
    text = str(raw).strip().lower()
    if text in _TRUEY:
        return True
    if text in ("0", "false", "no", "off"):
        return False
    problems.append("%s must be a boolean (0/1, true/false), got %r" % (name, raw))
    return default


def _as_int(raw, name, problems, default, minimum=1):
    """Parse an integer setting.

    ``minimum`` is 1 by default (counts, sizes); pass 0 for settings where zero
    is a meaningful value, like ``BIGBRAIN_RETRIES=0`` meaning "never retry".
    """
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        problems.append("%s must be an integer, got %r" % (name, raw))
        return default
    if value < minimum:
        problems.append("%s must be >= %d, got %d" % (name, minimum, value))
        return default
    return value


def _as_float(raw, name, problems, default, low=None, high=None):
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        problems.append("%s must be a number, got %r" % (name, raw))
        return default
    if low is not None and value < low:
        problems.append("%s must be >= %s, got %s" % (name, low, value))
        return default
    if high is not None and value > high:
        problems.append("%s must be <= %s, got %s" % (name, high, value))
        return default
    return value


# --------------------------------------------------------------------------
# Escalation scoring configuration (item 1)
# --------------------------------------------------------------------------


def parse_weights(raw, problems, source="BIGBRAIN_WEIGHTS"):
    """Parse a weights mapping from a JSON string or a dict.

    Unknown keys are ignored; missing keys keep their default.  Values are
    normalised so the component maxima sum to 1.0, which keeps the final score
    inside 0..1 no matter what the user configured.
    """
    weights = dict(DEFAULT_WEIGHTS)
    if raw is None or raw == "":
        return weights
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            problems.append("%s must be a JSON object: %s" % (source, exc))
            return weights
    if not isinstance(raw, dict):
        problems.append("%s must be a JSON object mapping component -> weight" % source)
        return weights
    for key in DEFAULT_WEIGHTS:
        if key in raw and raw[key] is not None and str(raw[key]).strip() != "":
            try:
                value = float(raw[key])
            except (TypeError, ValueError):
                problems.append("%s.%s must be a number, got %r" % (source, key, raw[key]))
                continue
            if value < 0:
                problems.append("%s.%s must be >= 0, got %s" % (source, key, value))
                continue
            weights[key] = value
    total = sum(weights.values())
    if total <= 0:
        problems.append("%s: all weights are zero; falling back to defaults" % source)
        return dict(DEFAULT_WEIGHTS)
    if abs(total - 1.0) > 1e-9:
        weights = {key: value / total for key, value in weights.items()}
    return weights


def bigbrain_home_dir(env=None):
    """The user-level bigbrain directory (default ``~/.bigbrain``)."""
    env = os.environ if env is None else env
    raw = (env.get("BIGBRAIN_HOME") or "").strip()
    return Path(raw).expanduser() if raw else Path(os.path.expanduser("~/.bigbrain"))


def json_config_path(env=None):
    """``~/.bigbrain/config.json`` (or ``$BIGBRAIN_HOME/config.json``)."""
    env = os.environ if env is None else env
    raw = (env.get("BIGBRAIN_CONFIG_FILE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return bigbrain_home_dir(env) / "config.json"


def json_keys(name):
    """The keys ``name`` may appear under in config.json: as-is, then short form."""
    if name.startswith("BIGBRAIN_"):
        return (name, name[len("BIGBRAIN_"):].lower())
    return (name,)


def setup_command(argv0=None):
    """The exact command that runs the setup wizard for *this* install.

    Built from the script actually being run when that is one of ours, so the
    hint shows ``~/.codex/skills/bigbrain/scripts/...`` rather than the symlink
    target of a checkout.
    """
    argv0 = sys.argv[0] if argv0 is None else argv0
    scripts = None
    if argv0 and Path(argv0).name in ("bigbrain_cli.py", "check_config.py", "advisor.py", "setup.py"):
        scripts = Path(os.path.abspath(argv0)).parent
    if scripts is None or not (scripts / "bigbrain_cli.py").is_file():
        scripts = skill_root() / "scripts"
    path = str(scripts / "bigbrain_cli.py")
    home = os.path.expanduser("~")
    if home not in ("", "/") and path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    return "python3 %s setup" % path


# --------------------------------------------------------------------------
# Main loader
# --------------------------------------------------------------------------


def load_config(env=None, config_file=None, json_file=None):
    """Load bigbrain configuration.

    Returns a dict; problems are collected under the ``problems`` key rather
    than raised, so callers can decide whether they are fatal.
    """
    env = os.environ if env is None else env
    env_path = CONFIG_ENV_FILE if config_file is None else Path(config_file)
    file_vals = parse_env_file(env_path) if Path(env_path).is_file() else {}

    problems = []
    sources = {}

    json_path = json_config_path(env) if json_file is None else Path(json_file)
    json_vals = parse_json_file(json_path, problems, label="bigbrain config")
    sources["json_file"] = str(json_path)
    sources["json_file_present"] = json_path.is_file()

    def raw(name, fallback=None):
        """Environment > JSON config > env-file > default.

        ``config.json`` accepts both the variable name (``BIGBRAIN_MODEL``) and
        its short lowercase form (``model``), which is what ``setup`` writes.
        """
        if env.get(name):
            return env[name], "env"
        for key in json_keys(name):
            if key in json_vals and json_vals[key] not in (None, ""):
                value = json_vals[key]
                return (json.dumps(value) if isinstance(value, (dict, list)) else str(value)), "json"
        if file_vals.get(name):
            return file_vals[name], "file"
        return fallback, "default"

    use_anthropic_raw, _ = raw("BIGBRAIN_USE_ANTHROPIC_ENV", "")
    use_anthropic = str(use_anthropic_raw).strip().lower() in _TRUEY

    base_url, src = raw("BIGBRAIN_BASE_URL")
    if not base_url and use_anthropic:
        base_url, src = raw("ANTHROPIC_BASE_URL")
        if src != "default":
            src = "anthropic-env"
    sources["base_url"] = src

    api_key, src = raw("BIGBRAIN_API_KEY")
    if not api_key and use_anthropic:
        for alt in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            api_key, src = raw(alt)
            if api_key:
                src = "anthropic-env:%s" % alt
                break
    sources["api_key"] = src

    model, src = raw("BIGBRAIN_MODEL", DEFAULT_MODEL)
    sources["model"] = src

    max_rounds_raw, _ = raw("BIGBRAIN_MAX_ROUNDS")
    max_tokens_raw, _ = raw("BIGBRAIN_MAX_TOKENS")
    max_tokens_cap_raw, _ = raw("BIGBRAIN_MAX_TOKENS_CAP", str(DEFAULT_MAX_TOKENS_CAP))
    timeout_raw, _ = raw("BIGBRAIN_TIMEOUT")
    total_timeout_raw, _ = raw("BIGBRAIN_MAX_TOTAL_TIMEOUT")
    stream_raw, _ = raw("BIGBRAIN_STREAM")
    retries_raw, _ = raw("BIGBRAIN_RETRIES", str(DEFAULT_RETRIES))
    backoff_raw, _ = raw("BIGBRAIN_RETRY_BACKOFF", str(DEFAULT_RETRY_BACKOFF))
    context_raw, _ = raw("BIGBRAIN_MAX_CONTEXT_CHARS")
    threshold_raw, _ = raw("BIGBRAIN_THRESHOLD")
    weights_raw, weights_src = raw("BIGBRAIN_WEIGHTS")

    cfg = {
        "base_url": (base_url or "").strip().rstrip("/"),
        "api_key": (api_key or "").strip(),
        "model": (model or DEFAULT_MODEL).strip(),
        "max_rounds": _as_int(max_rounds_raw, "BIGBRAIN_MAX_ROUNDS", problems, DEFAULT_MAX_ROUNDS),
        "max_tokens": _as_int(max_tokens_raw, "BIGBRAIN_MAX_TOKENS", problems, DEFAULT_MAX_TOKENS),
        "max_tokens_cap": _as_int(
            max_tokens_cap_raw, "BIGBRAIN_MAX_TOKENS_CAP", problems, DEFAULT_MAX_TOKENS_CAP
        ),
        "timeout": _as_int(timeout_raw, "BIGBRAIN_TIMEOUT", problems, DEFAULT_TIMEOUT),
        "max_total_timeout": _as_int(
            total_timeout_raw, "BIGBRAIN_MAX_TOTAL_TIMEOUT", problems, DEFAULT_MAX_TOTAL_TIMEOUT
        ),
        "stream": _as_bool(stream_raw, "BIGBRAIN_STREAM", problems, DEFAULT_STREAM),
        # ``retries`` counts *retries*, not attempts: 0 disables retrying.
        "retries": _as_int(
            retries_raw, "BIGBRAIN_RETRIES", problems, DEFAULT_RETRIES, minimum=0
        ),
        "retry_backoff": _as_float(
            backoff_raw, "BIGBRAIN_RETRY_BACKOFF", problems, DEFAULT_RETRY_BACKOFF, low=0.0
        ),
        "max_context_chars": _as_int(
            context_raw, "BIGBRAIN_MAX_CONTEXT_CHARS", problems, DEFAULT_MAX_CONTEXT_CHARS
        ),
        "threshold": _as_float(
            threshold_raw, "BIGBRAIN_THRESHOLD", problems, DEFAULT_THRESHOLD, low=0.0, high=1.0
        ),
        "weights": parse_weights(weights_raw, problems, source="BIGBRAIN_WEIGHTS"),
        "weights_source": weights_src,
        "use_anthropic_env": use_anthropic,
        "config_file": str(env_path),
        "config_file_present": Path(env_path).is_file(),
        "json_config_file": str(json_path),
        "json_config_present": json_path.is_file(),
        "bigbrain_home": str(bigbrain_home_dir(env)),
        "sources": sources,
        "problems": problems,
    }

    # Report pricing (item 3).
    price_in, _ = raw("BIGBRAIN_PRICE_IN")
    price_out, _ = raw("BIGBRAIN_PRICE_OUT")
    base_in, _ = raw("BIGBRAIN_BASELINE_PRICE_IN")
    base_out, _ = raw("BIGBRAIN_BASELINE_PRICE_OUT")
    exec_in, _ = raw("BIGBRAIN_EXECUTOR_PRICE_IN")
    exec_out, _ = raw("BIGBRAIN_EXECUTOR_PRICE_OUT")
    exec_tokens, _ = raw(
        "BIGBRAIN_EXECUTOR_TOKENS_PER_ROUND", str(DEFAULT_EXECUTOR_TOKENS_PER_ROUND)
    )
    cfg["prices"] = {
        "advisor_in": _as_float(price_in, "BIGBRAIN_PRICE_IN", problems, DEFAULT_PRICE_IN),
        "advisor_out": _as_float(price_out, "BIGBRAIN_PRICE_OUT", problems, DEFAULT_PRICE_OUT),
        "baseline_in": _as_float(
            base_in, "BIGBRAIN_BASELINE_PRICE_IN", problems, DEFAULT_BASELINE_PRICE_IN
        ),
        "baseline_out": _as_float(
            base_out, "BIGBRAIN_BASELINE_PRICE_OUT", problems, DEFAULT_BASELINE_PRICE_OUT
        ),
        # The executor model's own price, used to size the "what it would have
        # cost to send all of this to the premium model" comparison.
        "executor_in": _as_float(
            exec_in, "BIGBRAIN_EXECUTOR_PRICE_IN", problems, DEFAULT_EXECUTOR_PRICE_IN
        ),
        "executor_out": _as_float(
            exec_out, "BIGBRAIN_EXECUTOR_PRICE_OUT", problems, DEFAULT_EXECUTOR_PRICE_OUT
        ),
    }
    cfg["executor_tokens_per_round"] = _as_int(
        exec_tokens,
        "BIGBRAIN_EXECUTOR_TOKENS_PER_ROUND",
        problems,
        DEFAULT_EXECUTOR_TOKENS_PER_ROUND,
    )

    lesson_inject, _ = raw("BIGBRAIN_LESSON_INJECT", str(DEFAULT_LESSON_INJECT))
    lesson_cap, _ = raw("BIGBRAIN_LESSON_CAP", str(DEFAULT_LESSON_CAP))
    cfg["lesson_inject"] = _as_int(
        lesson_inject, "BIGBRAIN_LESSON_INJECT", problems, DEFAULT_LESSON_INJECT
    )
    cfg["lesson_cap"] = _as_int(lesson_cap, "BIGBRAIN_LESSON_CAP", problems, DEFAULT_LESSON_CAP)

    cfg["mock_path"] = (
        env.get("BIGBRAIN_MOCK") or json_vals.get("mock_file") or file_vals.get("BIGBRAIN_MOCK") or None
    )
    cfg["problems"].extend(validate_config(cfg))
    return cfg


def validate_config(cfg):
    """Return a list of human-readable configuration problems (may be empty)."""
    problems = []
    base = cfg.get("base_url") or ""
    if not base:
        problems.append(
            "BIGBRAIN_BASE_URL is not set (the API base URL, e.g. https://api.example.com)"
        )
    elif not re.match(r"^https?://[^/\s]+", base):
        problems.append(
            "BIGBRAIN_BASE_URL must start with http:// or https:// and include a host, got %r" % base
        )
    if not cfg.get("api_key"):
        key_hint = "BIGBRAIN_API_KEY"
        if cfg.get("use_anthropic_env"):
            key_hint += " (or ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY)"
        problems.append("%s is not set (the API key sent as x-api-key and Authorization: Bearer)" % key_hint)
    if not (cfg.get("model") or "").strip():
        problems.append("BIGBRAIN_MODEL must not be empty (default: %s)" % DEFAULT_MODEL)
    return problems


def config_problems(cfg):
    return list(cfg.get("problems") or [])


# --------------------------------------------------------------------------
# Skill paths
# --------------------------------------------------------------------------


def skill_root():
    """Directory containing SKILL.md (the skill root).

    ``scripts/bigbrain/config.py`` -> ``scripts/bigbrain`` -> ``scripts`` ->
    the skill root.
    """
    return Path(__file__).resolve().parent.parent.parent


def default_system_prompt_path():
    override = os.environ.get("BIGBRAIN_SYSTEM_PROMPT_FILE")
    if override:
        return Path(override).expanduser()
    return skill_root() / "references" / "advisor-system-prompt.md"


def load_system_prompt(path=None):
    path = Path(path) if path else default_system_prompt_path()
    if not path.is_file():
        raise BigbrainError(
            "advisor system prompt not found at %s (set BIGBRAIN_SYSTEM_PROMPT_FILE to override)" % path,
            EXIT_CONFIG,
        )
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        raise BigbrainError("advisor system prompt at %s is empty" % path, EXIT_CONFIG)
    return text
