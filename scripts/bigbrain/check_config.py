"""Configuration validation plus a real ping of the advisor endpoint.

Three things are being proved, and they are different:

1. the configuration is present and well-formed,
2. ``{BIGBRAIN_BASE_URL}/v1/messages`` really answers as a Messages API for the
   configured model, and
3. ``{BIGBRAIN_BASE_URL}/v1/models`` lists the ids that endpoint actually
   serves, so a wrong model spelling can be corrected rather than guessed at.

The ping is judged by *shape*, not by content.  The question is whether the
endpoint speaks the Messages API: a well-formed body (``type: message``, an
assistant role, text content, a ``model`` field) means the transport and the
credentials are fine and the run can proceed.  Whether the model chose to answer
"ping" with a word or a sentence is a prompting matter, not a configuration
fault, so prose is a warning at most.  Only a body that is not a Messages
response at all -- HTML from a proxy, an error envelope, some other API's JSON --
is a hard failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

from .client import list_models, model_ids, post_messages
from .config import (
    DEFAULT_MODEL,
    EXIT_CONFIG,
    EXIT_HTTP,
    EXIT_MODEL,
    EXIT_OK,
    BigbrainError,
    config_problems,
    load_config,
    mask_secret,
    setup_command,
)
from .io import eprint

PING_PROMPT = "ping"
PING_MAX_TOKENS = 16
#: A reply longer than this to a one-word prompt is *suspicious* -- it suggests
#: the endpoint ignored the prompt -- but a model that thinks out loud is not a
#: broken configuration, so this is reported as a warning and the exit stays 0.
MAX_PING_REPLY_CHARS = 64


def build_parser():
    parser = argparse.ArgumentParser(
        prog="check_config.py",
        description="Validate bigbrain configuration and ping the advisor endpoint.",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable JSON report")
    parser.add_argument("--no-call", action="store_true",
                        help="validate configuration only, do not call the API")
    parser.add_argument("--list-models", action="store_true",
                        help="call GET {base}/v1/models and print the model ids it serves")
    parser.add_argument("--timeout", type=int, default=None,
                        help="override BIGBRAIN_TIMEOUT for the ping")
    parser.add_argument("--quiet", action="store_true", help="suppress progress lines")
    return parser


def report(payload, as_json, ok):
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif not ok:
        eprint("FAIL: %s" % payload.get("error", "unknown error"))
        if payload.get("hint"):
            eprint("hint: %s" % payload["hint"])
    return payload["exit_code"] if "exit_code" in payload else (0 if ok else 1)


def classify_reply(text):
    """Return ``(usable, warning, reason)`` for a ping reply's *text*.

    Only an empty body is unusable here.  Length is not evidence of a wrong
    endpoint -- a model is free to answer "ping" with a sentence -- so a long
    reply yields a warning and still passes.  Judging the *envelope* is
    :func:`classify_body`'s job, and that is where a non-Messages response
    (HTML, an error document) is caught.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False, "", "the endpoint returned an empty message body"
    if len(stripped) > MAX_PING_REPLY_CHARS:
        return True, (
            "the endpoint answered a one-word ping with %d characters of prose; "
            "the response is a valid Messages reply, but check that the model and "
            "endpoint are the ones you expect" % len(stripped)
        ), ""
    return True, "", ""


def classify_body(json_body):
    """Return ``(ok, reason)`` for a ping response *envelope*.

    A usable Messages body has an assistant role and either a text block or a
    recognised ``stop_reason``.  Anything else -- a proxy's HTML error page, a
    bare ``{"error": ...}``, an unrelated JSON shape -- is not this API.
    """
    if not isinstance(json_body, dict):
        return False, "the endpoint did not return a JSON object"
    if isinstance(json_body.get("error"), dict):
        err = json_body["error"]
        return False, "the endpoint returned an error envelope: %s: %s" % (
            err.get("type", "error"), str(err.get("message", ""))[:200],
        )
    kind = json_body.get("type")
    if kind is not None and kind != "message":
        return False, "the response `type` was %r, not 'message'" % kind
    role = json_body.get("role")
    if role is not None and role != "assistant":
        return False, "the response `role` was %r, not 'assistant'" % role
    content = json_body.get("content")
    has_text = (
        isinstance(content, str)
        or (
            isinstance(content, list)
            and any(
                isinstance(b, dict) and b.get("type") == "text"
                for b in content
            )
        )
    )
    if not has_text and not json_body.get("stop_reason"):
        return False, (
            "the response had neither text content nor a stop_reason "
            "(keys: %s)" % ", ".join(sorted(json_body))[:200]
        )
    return True, ""


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config()
    base_url = cfg["base_url"]
    model = cfg["model"] or DEFAULT_MODEL

    problems = config_problems(cfg)
    if problems:
        payload = {
            "ok": False,
            "stage": "config",
            "exit_code": EXIT_CONFIG,
            "error": "; ".join(problems),
            "hint": "run the setup wizard: %s  (or set BIGBRAIN_BASE_URL and "
                    "BIGBRAIN_API_KEY; see references/config.md)" % setup_command(),
            "setup_command": setup_command(),
            "base_url": base_url,
            "model": model,
            "api_key": mask_secret(cfg["api_key"]),
            "config_file": cfg["config_file"],
        }
        return report(payload, args.json, False)

    payload = {
        "ok": True,
        "stage": "config",
        "exit_code": EXIT_OK,
        "base_url": base_url,
        "model": model,
        "api_key": mask_secret(cfg["api_key"]),
        "api_key_source": cfg["sources"].get("api_key", "?"),
        "max_tokens": cfg["max_tokens"],
        "max_rounds": cfg["max_rounds"],
        "timeout": cfg["timeout"],
        "threshold": cfg["threshold"],
        "config_file": cfg["config_file"],
        "config_file_present": cfg["config_file_present"],
        "json_config_file": cfg["json_config_file"],
        "json_config_present": cfg["json_config_present"],
    }

    if args.no_call:
        payload["pinged"] = False
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("OK (config only, no API call)")
            print("  base url  : %s" % base_url)
            print("  model     : %s" % model)
            print("  api key   : %s" % mask_secret(cfg["api_key"]))
        return EXIT_OK

    if args.list_models:
        return list_models_command(cfg, args, payload)

    request = {
        "model": model,
        "max_tokens": PING_MAX_TOKENS,
        "messages": [{"role": "user", "content": PING_PROMPT}],
    }
    try:
        response = post_messages(cfg, request, timeout=args.timeout)
    except BigbrainError as exc:
        payload.update(
            {
                "ok": False,
                "stage": "ping",
                "exit_code": exc.exit_code,
                "error": str(exc),
                "pinged": True,
            }
        )
        if exc.exit_code == 3:
            payload["hint"] = "check DNS, VPN, proxy settings and BIGBRAIN_BASE_URL reachability"
        elif exc.exit_code == 4:
            payload["hint"] = ("the API key was rejected; verify BIGBRAIN_API_KEY (it is sent as "
                               "both x-api-key and Authorization: Bearer)")
        elif exc.exit_code == EXIT_MODEL:
            payload["hint"] = ("the endpoint returned 404; check BIGBRAIN_MODEL and that "
                               "{base}/v1/messages is correct")
        return report(payload, args.json, False)

    # The envelope decides.  A body that is not a Messages response is fatal;
    # a Messages response whose prose is longer than we'd like is only a warning.
    warning = ""
    try:
        text = response.text
    except BigbrainError as exc:
        payload.update(
            {
                "ok": False,
                "stage": "ping",
                "exit_code": exc.exit_code,
                "error": "endpoint answered but the response was not a Messages payload: %s" % exc,
                "pinged": True,
                "http_status": response.status,
                "latency_ms": response.latency_ms,
            }
        )
        return report(payload, args.json, False)

    ok, reason = classify_body(response.json_body)
    if not ok:
        payload.update(
            {
                "ok": False,
                "stage": "ping",
                "exit_code": EXIT_HTTP,
                "error": reason,
                "hint": ("the request reached something that is not a Messages API endpoint; check "
                         "BIGBRAIN_BASE_URL points at the API root (no trailing /v1) and that "
                         "BIGBRAIN_MODEL is a model that endpoint serves "
                         "(see scripts/check_config.py --list-models)"),
                "pinged": True,
                "http_status": response.status,
                "latency_ms": response.latency_ms,
                "body_preview": _short(response.body_text),
            }
        )
        return report(payload, args.json, False)

    usable, warning, reason = classify_reply(text)
    if not usable:
        payload.update(
            {
                "ok": False,
                "stage": "ping",
                "exit_code": EXIT_HTTP,
                "error": reason,
                "pinged": True,
                "http_status": response.status,
                "latency_ms": response.latency_ms,
            }
        )
        return report(payload, args.json, False)

    payload.update(
        {
            "ok": True,
            "stage": "ping",
            "exit_code": EXIT_OK,
            "pinged": True,
            "streamed": bool(getattr(response, "streamed", False)),
            "http_status": response.status,
            "latency_ms": response.latency_ms,
            "reply_preview": (text or "").strip()[:80],
            "usage": response.usage,
        }
    )
    if warning:
        payload["warning"] = warning
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("OK")
        print("  base url : %s" % base_url)
        print("  model    : %s" % model)
        print("  api key  : %s" % mask_secret(cfg["api_key"]))
        print("  latency  : %d ms" % response.latency_ms)
        print("  reply    : %s" % ((text or "").strip()[:60] or "(empty)"))
        if warning:
            print("  warning  : %s" % warning)
    return EXIT_OK


def _short(text, limit=300):
    text = (text or "").strip().replace("\n", " ")
    return text[:limit] + "..." if len(text) > limit else text


def list_models_command(cfg, args, payload):
    """``--list-models``: print the ids served by GET {base}/v1/models.

    This is how a model spelling gets settled.  Anthropic's own ids are dotted
    (``claude-opus-5.5``) while many relays hyphenate them
    (``claude-opus-5-5``), and only the endpoint knows which it accepts.
    """
    try:
        body = list_models(cfg, timeout=args.timeout)
    except BigbrainError as exc:
        payload.update(
            {"ok": False, "stage": "models", "exit_code": exc.exit_code, "error": str(exc)}
        )
        if exc.exit_code == EXIT_MODEL:
            payload["hint"] = ("this endpoint does not expose /v1/models; set BIGBRAIN_MODEL from "
                               "the provider's documentation instead")
        else:
            payload["hint"] = ("GET {base}/v1/models failed; check BIGBRAIN_BASE_URL and "
                               "BIGBRAIN_API_KEY")
        return report(payload, args.json, False)

    ids = model_ids(body)
    configured = payload.get("model")
    payload.update(
        {
            "ok": True,
            "stage": "models",
            "exit_code": EXIT_OK,
            "models": ids,
            "count": len(ids),
            "configured_model_present": configured in ids if ids else None,
        }
    )
    if not ids:
        payload["warning"] = "the endpoint returned no recognizable model ids"
    elif configured not in ids:
        payload["warning"] = (
            "BIGBRAIN_MODEL=%s is not in the list this endpoint reports; pick one of the ids above"
            % configured
        )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif not ids:
        print("OK (no model ids reported by %s/v1/models)" % (cfg["base_url"] or ""))
    else:
        print("models served by %s/v1/models:" % (cfg["base_url"] or ""))
        for model_id in ids:
            marker = "  (configured)" if model_id == configured else ""
            print("  %s%s" % (model_id, marker))
        if payload.get("warning"):
            print("warning: %s" % payload["warning"])
    return EXIT_OK


def run(argv=None):
    try:
        return main(argv)
    except BigbrainError as exc:  # pragma: no cover - defensive
        eprint("FAIL: %s" % exc)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        eprint("interrupted")
        return 1
    except Exception:  # pragma: no cover
        traceback.print_exc()
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
