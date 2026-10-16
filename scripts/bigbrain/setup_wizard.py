"""``bigbrain setup`` -- an interactive wizard that writes ``~/.bigbrain/config.json``.

The flow:

1. **Detect** an existing configuration, read-only, in this order: ``BIGBRAIN_*``
   environment variables, ``ANTHROPIC_*`` environment variables, an existing
   ``config.json``, and the ``env`` block of ``~/.claude/settings.json``.  Each
   one found is shown (key masked) with its source and offered: "Use this?".
2. Otherwise, **ask**: provider (Anthropic, OpenRouter or a custom URL), the API
   key (hidden input) and the model, with a per-provider default.
3. **Validate** with one tiny real request.  Failures are explained (bad key,
   wrong URL, unknown model, network) and the user chooses: retry, edit, save
   anyway, or abort.
4. **Save** to ``config.json`` -- mode 600, directory 700.  That file is the
   only thing this module ever writes.

Reading ``~/.claude/settings.json`` is the one place bigbrain looks inside an
agent configuration file, and it is strictly read-only: the file is parsed for
its ``env`` block and nothing else.  Writes go through
:func:`bigbrain.agents_md.guard_write`, so the wizard cannot be pointed at an
AGENTS.md or an agent config directory either.

The API key is never printed: every message that could carry it goes through
:func:`mask_secret` or :func:`_scrub`.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import time
from pathlib import Path

from .agents_md import guard_write, is_inside_protected_dir
from .check_config import PING_MAX_TOKENS, PING_PROMPT, classify_body
from .client import post_messages
from .config import (
    DEFAULT_MODEL,
    EXIT_AUTH,
    EXIT_CONFIG,
    EXIT_MODEL,
    EXIT_NETWORK,
    EXIT_OK,
    BigbrainError,
    bigbrain_home_dir,
    json_config_path,
    json_keys,
    mask_secret,
    parse_json_file,
)

ANTHROPIC_URL = "https://api.anthropic.com"
OPENROUTER_URL = "https://openrouter.ai/api"

#: (label, base url or None for "ask", default model).  OpenRouter spells
#: Anthropic models ``anthropic/<id>`` with a dotted version.
PROVIDERS = (
    ("Anthropic (official)", ANTHROPIC_URL, DEFAULT_MODEL),
    ("OpenRouter", OPENROUTER_URL, "anthropic/claude-opus-5.5"),
    ("Custom URL (any Anthropic-compatible Messages API)", None, DEFAULT_MODEL),
)

#: The validation call is a one-word ping: it should answer in seconds, so it
#: gets a short budget instead of the 300s a real advisor turn needs.
VALIDATE_TIMEOUT = 20
VALIDATE_TOTAL_TIMEOUT = 45

#: The three settings the wizard owns, as written to config.json.
SAVED_KEYS = ("base_url", "api_key", "model")

EXIT_ABORTED = 1


class Aborted(Exception):
    """The user aborted, or input ran out.  Nothing has been saved."""


# --------------------------------------------------------------------------
# Detection (read-only)
# --------------------------------------------------------------------------


def default_model_for(base_url):
    for _, url, model in PROVIDERS:
        if url and (base_url or "").rstrip("/") == url:
            return model
    return DEFAULT_MODEL


def _candidate(source, base_url, api_key, model, notes=()):
    base_url = (base_url or "").strip().rstrip("/")
    notes = list(notes)
    if not base_url:
        base_url = ANTHROPIC_URL
        notes.append("no base URL set; assuming Anthropic official")
    if not (model or "").strip():
        model = default_model_for(base_url)
        notes.append("no model set; using the default")
    return {
        "source": source,
        "base_url": base_url,
        "api_key": (api_key or "").strip(),
        "model": model.strip(),
        "notes": notes,
    }


def _anthropic_key(values):
    """``(key, variable name)`` from an ANTHROPIC_* mapping, token first."""
    for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        value = str(values.get(name) or "").strip()
        if value:
            return value, name
    return "", ""


def claude_settings_path(env=None, home=None):
    env = os.environ if env is None else env
    raw = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser() / "settings.json"
    home = Path(home) if home else Path(os.path.expanduser("~"))
    return home / ".claude" / "settings.json"


def detect(env=None, home=None):
    """Every usable existing configuration, in precedence order, de-duplicated.

    A candidate needs at least an API key; a missing base URL means Anthropic
    official and a missing model means the provider default.
    """
    env = os.environ if env is None else env
    found = []

    if (env.get("BIGBRAIN_API_KEY") or "").strip():
        found.append(_candidate(
            "environment (BIGBRAIN_*)",
            env.get("BIGBRAIN_BASE_URL"), env.get("BIGBRAIN_API_KEY"), env.get("BIGBRAIN_MODEL"),
        ))

    key, key_name = _anthropic_key(env)
    if key:
        names = (["ANTHROPIC_BASE_URL"] if env.get("ANTHROPIC_BASE_URL") else []) + [key_name]
        found.append(_candidate(
            "environment (%s)" % ", ".join(names),
            env.get("ANTHROPIC_BASE_URL"), key, env.get("BIGBRAIN_MODEL"),
        ))

    json_path = json_config_path(env)
    data = parse_json_file(json_path)

    def from_json(name):
        for k in json_keys(name):
            if data.get(k) not in (None, ""):
                return str(data[k])
        return ""

    if from_json("BIGBRAIN_API_KEY"):
        found.append(_candidate(
            _display_path(json_path),
            from_json("BIGBRAIN_BASE_URL"), from_json("BIGBRAIN_API_KEY"), from_json("BIGBRAIN_MODEL"),
        ))

    settings_path = claude_settings_path(env, home)
    settings = parse_json_file(settings_path)
    block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    key, key_name = _anthropic_key(block)
    if key:
        found.append(_candidate(
            "%s (env block: %s)" % (_display_path(settings_path), key_name),
            block.get("ANTHROPIC_BASE_URL"), key, None,
        ))

    unique, seen = [], set()
    for cand in found:
        ident = (cand["base_url"], cand["api_key"], cand["model"])
        if ident not in seen:
            seen.add(ident)
            unique.append(cand)
    return unique


def _display_path(path):
    text = str(path)
    home = os.path.expanduser("~")
    if home not in ("", "/") and text.startswith(home + os.sep):
        return "~" + text[len(home):]
    return text


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _scrub(text, api_key):
    """Remove the key from any text that might be shown (error bodies echo headers)."""
    text = str(text or "")
    if api_key and len(api_key) >= 4:
        text = text.replace(api_key, mask_secret(api_key))
    return text


def _host(url):
    match = re.match(r"^https?://([^/]+)", url or "")
    return match.group(1) if match else (url or "?")


def _mentions_model(text):
    return bool(re.search(r"\bmodel", text or "", re.IGNORECASE))


def validate(base_url, api_key, model, timeout=VALIDATE_TIMEOUT):
    """One tiny real request.  Returns ``(ok, message)``; the message never holds the key."""
    if not re.match(r"^https?://[^/\s]+", base_url or ""):
        return False, "the base URL must start with http:// or https:// and include a host"
    cfg = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model,
        "stream": True,
        "retries": 0,
        "retry_backoff": 0,
        "timeout": timeout,
        "max_total_timeout": max(timeout, VALIDATE_TOTAL_TIMEOUT),
    }
    request = {
        "model": model,
        "max_tokens": PING_MAX_TOKENS,
        "messages": [{"role": "user", "content": PING_PROMPT}],
    }
    host = _host(base_url)
    try:
        response = post_messages(cfg, request)
    except BigbrainError as exc:
        status = exc.extra.get("http_status")
        body = _scrub(exc.extra.get("body") or "", api_key)
        detail = _scrub(str(exc), api_key)
        if exc.exit_code == EXIT_AUTH:
            return False, (
                "authentication failed (HTTP %s): %s rejected the API key. Check that the key "
                "is correct, not expired, and belongs to this provider." % (status, host)
            )
        if exc.exit_code == EXIT_MODEL:
            if _mentions_model(body):
                return False, (
                    "model not found (HTTP 404): %s does not serve %r. Check the spelling -- "
                    "ids are provider-specific -- or pick another model." % (host, model)
                )
            return False, (
                "endpoint not found (HTTP 404) at %s/v1/messages. Check the base URL: it should "
                "be the API root, without a trailing /v1." % cfg["base_url"]
            )
        if status == 400 and _mentions_model(body):
            return False, (
                "model not accepted (HTTP 400): %s rejected %r -- %s"
                % (host, model, _short(body))
            )
        if exc.exit_code == EXIT_NETWORK:
            errno_text = re.search(r"\[Errno -?\d+\]\s*([^()]+?)\s*(?:\(|$)", detail)
            if "timeout" in detail.lower() or "timed out" in detail.lower():
                why = "timed out after %ss" % timeout
            elif errno_text:
                why = errno_text.group(1).rstrip(" .")
            else:
                why = _short(detail)
            return False, (
                "network error: could not reach %s (%s). Check the URL, your connection, "
                "DNS, and any VPN or proxy." % (host, why)
            )
        if exc.exit_code == EXIT_CONFIG:
            return False, detail
        if status is None:
            # A 200 whose body could not be read as a Messages reply: HTML from
            # a web server or proxy, usually -- the base URL points elsewhere.
            return False, (
                "%s answered, but not as an Anthropic Messages API (%s). Check the base URL."
                % (host, _short(detail))
            )
        return False, "the request failed (HTTP %s): %s" % (status, _short(detail))

    ok, reason = classify_body(response.json_body)
    if not ok:
        return False, (
            "%s answered, but not as an Anthropic Messages API (%s). Check the base URL."
            % (host, _scrub(reason, api_key))
        )
    return True, "%s answered in %d ms" % (host, response.latency_ms)


def _short(text, limit=200):
    text = " ".join(str(text or "").split())
    return text[:limit] + "..." if len(text) > limit else text


# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------


def save_config(values, env=None):
    """Merge ``values`` into config.json, written 600 inside a 700 directory.

    Other keys already in the file (threshold, weights, ...) are kept.  The
    wizard's own settings are written in their short form and any long-form
    duplicate is dropped, since the long form would otherwise win on load.
    """
    env = os.environ if env is None else env
    path = json_config_path(env)
    guard_write(path)
    if is_inside_protected_dir(path):
        raise BigbrainError(
            "refusing to write %s: it is inside an agent configuration directory" % path,
            EXIT_CONFIG,
        )

    parent = path.parent
    created = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if created or parent.resolve() == bigbrain_home_dir(env).resolve():
        os.chmod(parent, 0o700)

    problems = []
    data = parse_json_file(path, problems)
    if problems:
        # Unreadable or not an object: keep the old bytes rather than lose them.
        backup = path.with_name("%s.invalid-%d" % (path.name, int(time.time())))
        os.replace(path, backup)
        os.chmod(backup, 0o600)
    for name in SAVED_KEYS:
        data.pop("BIGBRAIN_%s" % name.upper(), None)
        data[name] = values[name]

    tmp = parent / (".%s.%d.tmp" % (path.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    os.chmod(path, 0o600)
    return path


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


class Prompter:
    """Thin wrapper over input()/getpass so EOF and Ctrl-C mean "abort"."""

    def __init__(self, ask=input, secret=None, out=None):
        self._ask = ask
        if secret is None:
            # getpass opens /dev/tty even when stdin is a pipe, which would make
            # scripted input hang on whatever terminal launched it.  A piped key
            # is not echoed anyway, so plain stdin is the right source there.
            secret = getpass.getpass if sys.stdin.isatty() else ask
        self._secret = secret
        self.out = out or (lambda text="": print(text, flush=True))

    def ask(self, prompt, default=""):
        suffix = " [%s]" % default if default else ""
        try:
            answer = self._ask("%s%s: " % (prompt, suffix))
        except EOFError:
            raise Aborted("no more input")
        return answer.strip() or default

    def secret(self, prompt):
        try:
            return self._secret(prompt).strip()
        except EOFError:
            raise Aborted("no more input")

    def confirm(self, prompt, default=True):
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                answer = self._ask("%s %s " % (prompt, hint)).strip().lower()
            except EOFError:
                raise Aborted("no more input")
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.out("Please answer y or n.")

    def choose(self, prompt, options, default):
        while True:
            answer = self.ask(prompt, default).lower()
            if answer in options:
                return answer
            self.out("Please answer one of: %s" % ", ".join(options))


def show_summary(io, cand, heading):
    io.out(heading)
    io.out("  base url : %s" % cand["base_url"])
    io.out("  api key  : %s" % mask_secret(cand["api_key"]))
    io.out("  model    : %s" % cand["model"])
    for note in cand.get("notes") or ():
        io.out("  note     : %s" % note)


def guided(io, prefill=None):
    """Ask for provider, key and model.  ``prefill`` supplies the defaults."""
    prefill = prefill or {}
    io.out("")
    io.out("Provider:")
    old_url = prefill.get("base_url") or ""
    preset_urls = [url for _, url, _ in PROVIDERS]
    if old_url in preset_urls:
        current = preset_urls.index(old_url) + 1
    else:
        current = len(PROVIDERS) if old_url else 1
    for index, (label, url, _) in enumerate(PROVIDERS, 1):
        io.out("  %d) %s%s" % (index, label, "  %s" % url if url else ""))
    choice = io.choose("Choose", [str(i) for i in range(1, len(PROVIDERS) + 1)], str(current))
    _, base_url, model_default = PROVIDERS[int(choice) - 1]

    if base_url is None:
        custom_default = "" if old_url in preset_urls else old_url
        while True:
            base_url = io.ask("Base URL (the API root, e.g. https://relay.example.com)",
                              custom_default).rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[: -len("/v1")]
                io.out("  (dropped the trailing /v1 -- Bigbrain appends /v1/messages itself)")
            if re.match(r"^https?://[^/\s]+", base_url):
                break
            io.out("  The URL must start with http:// or https:// and include a host.")

    old_key = prefill.get("api_key") or ""
    while True:
        if old_key:
            key = io.secret("API key (input hidden; Enter keeps %s): " % mask_secret(old_key))
            key = key or old_key
        else:
            key = io.secret("API key (input hidden): ")
        if key:
            break
        io.out("  An API key is required.")

    if prefill.get("model") and prefill.get("base_url") == base_url:
        model_default = prefill["model"]
    model = io.ask("Model", model_default)
    return {"source": "entered", "base_url": base_url, "api_key": key, "model": model, "notes": []}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def run_wizard(env=None, io=None, timeout=VALIDATE_TIMEOUT, home=None):
    env = os.environ if env is None else env
    io = io or Prompter()
    path = json_config_path(env)
    io.out("Bigbrain setup")
    io.out("This writes %s and nothing else." % _display_path(path))
    if not sys.stdin.isatty():
        io.out("(stdin is not a terminal: reading answers from stdin)")
    io.out("")

    try:
        chosen = None
        candidates = detect(env, home)
        for cand in candidates:
            show_summary(io, cand, "Found an existing configuration in %s:" % cand["source"])
            if io.confirm("Use this?", default=True):
                chosen = cand
                break
            io.out("")
        if chosen is None:
            if candidates:
                io.out("Let's enter one by hand.")
            else:
                io.out("No existing configuration found. Let's set one up.")
            chosen = guided(io)

        while True:
            io.out("")
            io.out("Validating: one tiny request to %s/v1/messages (model %s) ..."
                   % (chosen["base_url"], chosen["model"]))
            ok, message = validate(chosen["base_url"], chosen["api_key"], chosen["model"], timeout)
            if ok:
                io.out("OK: %s" % message)
                return _save_and_report(io, chosen, env)
            io.out("FAILED: %s" % message)
            choice = io.choose(
                "[r]etry, [e]dit settings, [s]ave anyway, or [a]bort?", ["r", "e", "s", "a"], "r"
            )
            if choice == "e":
                chosen = guided(io, chosen)
            elif choice == "s":
                io.out("Saving without a successful validation.")
                return _save_and_report(io, chosen, env)
            elif choice == "a":
                raise Aborted()
    except Aborted as exc:
        io.out("")
        io.out("Setup aborted%s. Nothing was saved." % (": %s" % exc if str(exc) else ""))
        return EXIT_ABORTED
    except KeyboardInterrupt:
        io.out("")
        io.out("Setup interrupted. Nothing was saved.")
        return EXIT_ABORTED


def _save_and_report(io, chosen, env):
    path = save_config({name: chosen[name] for name in SAVED_KEYS}, env)
    io.out("Saved %s (mode 600)." % _display_path(path))
    overridden = [
        var for var in ("BIGBRAIN_%s" % name.upper() for name in SAVED_KEYS)
        if env.get(var) and env[var] != chosen[var[len("BIGBRAIN_"):].lower()]
    ]
    if overridden:
        io.out("note: environment variables override config.json; still set: %s"
               % ", ".join(overridden))
    return EXIT_OK


__all__ = [
    "PROVIDERS",
    "Prompter",
    "detect",
    "run_wizard",
    "save_config",
    "validate",
]
