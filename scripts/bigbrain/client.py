"""A minimal Anthropic-compatible Messages API client (urllib, stdlib only).

Every failure is mapped to one of the shared exit codes so callers never have
to inspect exception types themselves.  The API key is sent on both auth
headers because relays differ in which one they check, and it is never logged.

Streaming
---------
Requests are sent with ``"stream": true`` by default and the SSE event stream is
assembled locally.  This is not an optimisation, it is a correctness fix: a
non-streaming call spends the whole thinking turn with no bytes on the wire, so
any proxy in front of the API can time it out.  Cloudflare, for example, answers
HTTP 524 ("origin did not return a complete response within the 120-second
Proxy Read Timeout window") on a long non-streamed turn that would have
succeeded instantly as a stream, because a stream keeps emitting ``ping`` and
delta events the whole time.

``BIGBRAIN_STREAM=0`` turns streaming off for endpoints that do not support it.

Two timeouts are in play and they do different jobs:

* ``BIGBRAIN_TIMEOUT`` is the *per-read* socket timeout -- how long a single
  read may block waiting for the next chunk.  It must be generous enough for a
  model that thinks for minutes before its first token, which is why it
  defaults to 300s rather than a conventional 30s.
* ``BIGBRAIN_MAX_TOTAL_TIMEOUT`` caps one call end to end, so a stream that
  trickles forever still eventually fails instead of hanging the run.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import (
    ANTHROPIC_VERSION,
    DEFAULT_MAX_TOTAL_TIMEOUT,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_STREAM,
    DEFAULT_TIMEOUT,
    EXIT_AUTH,
    EXIT_CONFIG,
    EXIT_HTTP,
    EXIT_MODEL,
    EXIT_NETWORK,
    TRANSIENT_HTTP_STATUSES,
    BigbrainError,
    mask_secret,
)
from .io import eprint

#: Written on its own line, and only from here, so the retry trail is greppable
#: without matching ordinary progress output.
PROGRESS_PREFIX = "[Bigbrain]"

#: SSE error types that mean "the request never had a chance" and are worth
#: repeating.  ``overloaded_error`` is the usual one under load.
_TRANSIENT_SSE_ERRORS = ("overloaded_error", "api_error", "timeout_error")


def _is_loopback(url):
    m = re.match(r"^https?://([^/:]+)", url)
    if not m:
        return False
    return m.group(1).lower() in ("127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0")


class CredentialRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward API credentials to another origin or downgrade HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (old.scheme, old.netloc.lower()) != (new.scheme, new.netloc.lower()):
            raise urllib.error.HTTPError(req.full_url, code, "cross-origin API redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(url):
    """Bypass ambient proxy settings for loopback URLs (keeps local mocks sane)."""
    if _is_loopback(url):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), CredentialRedirect())
    return urllib.request.build_opener(CredentialRedirect())


def _short_body(text, limit=400):
    text = (text or "").strip().replace("\n", " ")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


class TransientError(BigbrainError):
    """A failure worth retrying, carrying the label used in the retry line.

    ``label`` is a bare HTTP status (``"524"``) or a short cause
    (``"incomplete stream"``) so the operator-facing message reads
    ``transient error 524, retry 1/2``.
    """

    def __init__(self, message, label, exit_code=EXIT_HTTP, **extra):
        super().__init__(message, exit_code, **extra)
        self.label = str(label)
        self.transient = True


class HttpResponse:
    """One completed API call.

    ``json_body`` is always Messages-shaped, whether the call was streamed or
    not, so callers (:attr:`text`, :attr:`usage`) do not care which transport
    was used.  The extra attributes describe how it was obtained.
    """

    def __init__(
        self,
        status,
        body_text,
        latency_ms,
        json_body=None,
        streamed=False,
        stop_reason=None,
        events=0,
    ):
        self.status = status
        self.body_text = body_text
        self.latency_ms = latency_ms
        self.json_body = json_body
        self.streamed = streamed
        self.stop_reason = stop_reason
        self.events = events

    @property
    def usage(self):
        """The API's ``usage`` object, or an empty mapping.

        Token accounting (item 3) reads this: both the Anthropic
        ``input_tokens``/``output_tokens`` spelling and the OpenAI-ish
        ``prompt_tokens``/``completion_tokens`` spelling are understood.
        """
        return usage_of(self.json_body)

    @property
    def text(self):
        return extract_text(self.json_body)


def usage_of(json_body):
    """Return {input_tokens, output_tokens} from a response body (0s when absent)."""
    empty = {"input_tokens": 0, "output_tokens": 0, "present": False}
    if not isinstance(json_body, dict):
        return empty
    raw = json_body.get("usage")
    if not isinstance(raw, dict):
        return empty

    def number(*keys):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    # ``input_tokens`` is the *uncached* remainder; the cached portions are
    # reported separately.  A real bill counts all three, so the sum is what the
    # cost estimate needs -- otherwise a heavily cached run looks nearly free.
    input_tokens = (
        number("input_tokens", "prompt_tokens")
        + number("cache_creation_input_tokens")
        + number("cache_read_input_tokens")
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": number("output_tokens", "completion_tokens"),
        "cache_creation_input_tokens": number("cache_creation_input_tokens"),
        "cache_read_input_tokens": number("cache_read_input_tokens"),
        "present": True,
    }


def extract_text(json_body):
    """Pull the assistant text out of an Anthropic Messages response body."""
    if not isinstance(json_body, dict):
        raise BigbrainError("response body was not a JSON object", EXIT_HTTP)
    content = json_body.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "".join(parts)
    if isinstance(content, str) and content:
        return content
    if isinstance(json_body.get("completion"), str):
        return json_body["completion"]
    if isinstance(json_body.get("error"), dict):
        err = json_body["error"]
        raise BigbrainError(
            "API returned an error payload: %s: %s"
            % (err.get("type", "error"), _short_body(str(err.get("message", "")))),
            EXIT_HTTP,
        )
    raise BigbrainError(
        "response contained no text content (keys: %s)" % ", ".join(sorted(json_body))[:200],
        EXIT_HTTP,
    )


def messages_url(cfg):
    return (cfg.get("base_url") or "").rstrip("/") + "/v1/messages"


def models_url(cfg):
    return (cfg.get("base_url") or "").rstrip("/") + "/v1/models"


def prompt_cache_enabled(cfg):
    """True unless ``BIGBRAIN_PROMPT_CACHE`` (or cfg ``prompt_cache``) is off."""
    value = cfg.get("prompt_cache")
    if value is None:
        value = os.environ.get("BIGBRAIN_PROMPT_CACHE", "1")
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


def _cache_first_user(messages):
    """Copy of ``messages`` with cache_control on the first user message's last block."""
    out = list(messages)
    if not out or out[0].get("role") != "user":
        return out
    content = out[0].get("content")
    if isinstance(content, str):
        blocks = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        blocks = [dict(b) if isinstance(b, dict) else b for b in content]
    else:
        return out
    if isinstance(blocks[-1], dict):
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    out[0] = {**out[0], "content": blocks}
    return out


def build_payload(cfg, system_prompt, messages, model=None, max_tokens=None):
    """Build the request body for one advisor round.

    ``stream`` is included so the artefact written to the session says exactly
    what went on the wire; ``BIGBRAIN_STREAM=0`` omits it entirely rather than
    sending ``false``, because some relays reject an unknown field.
    """
    payload = {
        "model": model or cfg.get("model"),
        "max_tokens": max_tokens or cfg.get("max_tokens"),
        "system": system_prompt,
        "messages": messages,
    }
    if prompt_cache_enabled(cfg):
        payload["system"] = [
            {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
        ]
        payload["messages"] = _cache_first_user(messages)
    if cfg.get("stream", DEFAULT_STREAM):
        payload["stream"] = True
    return payload


def _headers(cfg):
    return {
        "content-type": "application/json",
        "accept": "text/event-stream",
        "anthropic-version": ANTHROPIC_VERSION,
        "x-api-key": cfg.get("api_key") or "",
        "authorization": "Bearer %s" % (cfg.get("api_key") or ""),
        "user-agent": "bigbrain/1.0 (+stdlib)",
    }


def _classify_http_status(status):
    """Map an HTTP status to ``(exit_code, label)``."""
    if status in (401, 403):
        return EXIT_AUTH, "authentication failed"
    if status == 404:
        return EXIT_MODEL, "not found (model or endpoint)"
    return EXIT_HTTP, "HTTP error"


# --------------------------------------------------------------------------
# SSE
# --------------------------------------------------------------------------


class _StreamAccumulator:
    """Assembles one Anthropic SSE stream into a Messages-shaped result.

    Events understood::

        message_start        model, id, initial usage (incl. cache counters)
        content_block_start  a text block opening (no text of its own)
        content_block_delta  ``text_delta`` carries the reply text
        message_delta        final stop_reason and output_tokens
        message_stop         the stream finished cleanly
        ping                 keep-alive; ignored, but proves the stream is live
        error                a mid-stream error payload; raises

    Anything else is ignored rather than fatal -- relays emit their own event
    types and a stricter parser would break on them for no benefit.
    """

    def __init__(self):
        self.text_parts = []
        self.model = None
        self.message_id = None
        self.stop_reason = None
        self.input_tokens = 0
        self.cache_creation = 0
        self.cache_read = 0
        self.output_tokens = 0
        self.events = 0
        self.saw_message_stop = False
        self.error = None

    def feed(self, name, data):
        """Consume one decoded SSE event.  Returns False on ``message_stop``."""
        self.events += 1
        if name == "ping":
            return True
        if name == "error":
            payload = data.get("error") if isinstance(data.get("error"), dict) else data
            err_type = str(payload.get("type") or "error")
            err_msg = _short_body(str(payload.get("message") or ""))
            self.error = (err_type, err_msg)
            return False
        if not isinstance(data, dict):
            return True

        if name == "message_start":
            message = data.get("message")
            if isinstance(message, dict):
                self.model = message.get("model") or self.model
                self.message_id = message.get("id") or self.message_id
                self._absorb_usage(message.get("usage"))
        elif name == "content_block_start":
            block = data.get("content_block")
            # Some relays inline the whole block instead of streaming deltas.
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                self.text_parts.append(str(block["text"]))
        elif name == "content_block_delta":
            delta = data.get("delta")
            if isinstance(delta, dict):
                dtype = delta.get("type")
                if dtype in (None, "text_delta") and isinstance(delta.get("text"), str):
                    self.text_parts.append(delta["text"])
        elif name == "message_delta":
            delta = data.get("delta")
            if isinstance(delta, dict) and delta.get("stop_reason"):
                self.stop_reason = delta["stop_reason"]
            self._absorb_usage(data.get("usage"))
        elif name == "message_stop":
            self.saw_message_stop = True
            return False
        return True

    def _absorb_usage(self, usage):
        if not isinstance(usage, dict):
            return

        def number(key):
            value = usage.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return 0
            return int(value)

        # Only overwrite what this event actually reports: message_start carries
        # the input side, message_delta the output side, and each must not zero
        # the other.
        if any(k in usage for k in ("input_tokens", "prompt_tokens")):
            self.input_tokens = number("input_tokens") or number("prompt_tokens")
        self.cache_creation += number("cache_creation_input_tokens")
        self.cache_read += number("cache_read_input_tokens")
        if "output_tokens" in usage:
            self.output_tokens = number("output_tokens")
        elif "completion_tokens" in usage:
            self.output_tokens = number("completion_tokens")

    @property
    def usage(self):
        return {
            # Uncached remainder only: usage_of() folds the cache counters in.
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation,
            "cache_read_input_tokens": self.cache_read,
        }

    def body(self, model_fallback=None):
        return {
            "id": self.message_id or "msg_stream",
            "type": "message",
            "role": "assistant",
            "model": self.model or model_fallback,
            "content": [{"type": "text", "text": "".join(self.text_parts)}],
            "stop_reason": self.stop_reason,
            "stop_sequence": None,
            "usage": self.usage,
        }


def _iter_sse(response, deadline):
    """Yield ``(event_name, data)`` pairs from an SSE byte stream.

    Reads a line at a time so the socket timeout applies *per chunk* rather than
    to the whole body -- that is what lets one call run for many minutes while
    still failing fast when a relay goes silent.
    """
    name = None
    data_lines = []
    while True:
        if deadline is not None and time.time() > deadline:
            raise _IncompleteStream("overall time budget exhausted mid-stream")
        raw = response.readline()
        if not raw:
            # EOF: flush any trailing event, then stop.
            if data_lines:
                yield name or "message", _decode_data(data_lines)
            return
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield name or "message", _decode_data(data_lines)
            name, data_lines = None, []
            continue
        if line.startswith(":"):
            continue  # SSE comment / keep-alive
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            name = value.strip()
        elif field == "data":
            data_lines.append(value)


def _decode_data(data_lines):
    """Decode one SSE ``data:`` payload.

    ``[DONE]`` is an OpenAI-ism some relays append; it is a terminator, not
    JSON, so it decodes to an empty mapping rather than raising.
    """
    text = "\n".join(data_lines).strip()
    if not text or text == "[DONE]":
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {}


class _IncompleteStream(Exception):
    """The SSE body ended without ``message_stop``."""


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def _timeouts(cfg, timeout, total_timeout):
    per_read = timeout or cfg.get("timeout") or DEFAULT_TIMEOUT
    if total_timeout is None:
        total_timeout = cfg.get("max_total_timeout") or DEFAULT_MAX_TOTAL_TIMEOUT
    return per_read, total_timeout


def _plain_from_stream_response(response, status, payload, started):
    """Interpret a non-SSE body that came back to a streaming request.

    A JSON object is accepted as an ordinary Messages response -- some relays
    ignore the ``stream`` flag, and there is no reason to fail a call that
    plainly succeeded.  Anything else (HTML from a proxy, an empty body) is a
    hard error naming what arrived, because retrying the same request would
    produce the same bytes.
    """
    text = response.read().decode("utf-8", "replace")
    latency = int((time.time() - started) * 1000)
    try:
        parsed = json.loads(text)
    except ValueError:
        raise BigbrainError(
            "the endpoint returned %s instead of an event stream: %s"
            % (
                (response.headers.get("content-type") or "an unknown content type"),
                _short_body(text),
            ),
            EXIT_HTTP,
        )
    if not isinstance(parsed, dict):
        raise BigbrainError(
            "the endpoint returned %s instead of a Messages object" % type(parsed).__name__,
            EXIT_HTTP,
        )
    if isinstance(parsed.get("error"), dict):
        err = parsed["error"]
        raise BigbrainError(
            "API returned an error payload: %s: %s"
            % (err.get("type", "error"), _short_body(str(err.get("message", "")))),
            EXIT_HTTP,
        )
    return HttpResponse(
        status,
        text,
        latency,
        parsed,
        streamed=False,
        stop_reason=parsed.get("stop_reason"),
    )


def _post_stream(cfg, payload, target, per_read, total_timeout):
    """POST and assemble the SSE stream.  Raises TransientError when retryable."""
    body = json.dumps(payload).encode("utf-8")
    headers = dict(_headers(cfg))
    headers["accept"] = "text/event-stream"
    request = urllib.request.Request(target, data=body, headers=headers, method="POST")
    started = time.time()
    deadline = started + total_timeout
    acc = _StreamAccumulator()
    raw_events = []

    try:
        with _opener(target).open(request, timeout=per_read) as response:
            status = response.status
            content_type = (response.headers.get("content-type") or "").lower()
            if "event-stream" not in content_type:
                # The endpoint ignored `stream: true` and answered with a plain
                # body.  Relays do this, and so do misconfigured base URLs
                # (proxies answer HTML).  Handle it by content, not by hope:
                # a JSON Messages body is usable as-is, anything else is a hard
                # error naming what actually came back -- retrying would be
                # pointless, so this is deliberately not a transient failure.
                return _plain_from_stream_response(response, status, payload, started)
            for name, data in _iter_sse(response, deadline):
                raw_events.append(name)
                if name == "error":
                    err_type, err_msg = _stream_error(data)
                    exit_code = EXIT_HTTP
                    if err_type in _TRANSIENT_SSE_ERRORS:
                        raise TransientError(
                            "the endpoint reported a mid-stream error: %s: %s"
                            % (err_type, err_msg),
                            err_type,
                            exit_code,
                        )
                    raise BigbrainError(
                        "the endpoint reported a mid-stream error: %s: %s" % (err_type, err_msg),
                        exit_code,
                    )
                if not acc.feed(name, data):
                    break
    except _IncompleteStream as exc:
        raise TransientError(
            "the response stream ended early (%s) after %d events" % (exc, len(raw_events)),
            "incomplete stream",
            EXIT_NETWORK,
        )
    except (socket.timeout, TimeoutError) as exc:
        raise TransientError(
            "the response stream stalled for %ss mid-stream (%s)" % (per_read, exc),
            "incomplete stream",
            EXIT_NETWORK,
        )
    except (ConnectionResetError, BrokenPipeError) as exc:
        raise TransientError(
            "the connection dropped mid-stream: %s" % exc, "connection reset", EXIT_NETWORK
        )
    except http.client.HTTPException as exc:
        # IncompleteRead and friends: the proxy hung up before the body ended.
        raise TransientError(
            "the response stream was cut short: %s" % exc, "incomplete stream", EXIT_NETWORK
        )

    latency = int((time.time() - started) * 1000)

    if acc.events == 0:
        raise TransientError(
            "the endpoint returned an empty event stream (no SSE events at all)",
            "incomplete stream",
            EXIT_HTTP,
        )
    if acc.stop_reason is None and not acc.saw_message_stop:
        raise TransientError(
            "the response stream ended without message_stop after %d events" % acc.events,
            "incomplete stream",
            EXIT_HTTP,
        )

    result = HttpResponse(
        status,
        json.dumps(acc.body(payload.get("model")), ensure_ascii=False),
        latency,
        acc.body(payload.get("model")),
        streamed=True,
        stop_reason=acc.stop_reason,
        events=acc.events,
    )
    return result


def _stream_error(data):
    payload = data.get("error") if isinstance(data.get("error"), dict) else data
    return str(payload.get("type") or "error"), _short_body(str(payload.get("message") or ""))


def _post_plain(cfg, payload, target, per_read, total_timeout):
    """Non-streaming POST (``BIGBRAIN_STREAM=0``).  Raises TransientError when retryable."""
    body = json.dumps(payload).encode("utf-8")
    headers = dict(_headers(cfg))
    headers["accept"] = "application/json"
    request = urllib.request.Request(target, data=body, headers=headers, method="POST")
    started = time.time()
    try:
        with _opener(target).open(request, timeout=per_read) as response:
            text = response.read().decode("utf-8", "replace")
            latency = int((time.time() - started) * 1000)
            parsed = None
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            stop_reason = parsed.get("stop_reason") if isinstance(parsed, dict) else None
            return HttpResponse(response.status, text, latency, parsed, stop_reason=stop_reason)
    except (socket.timeout, TimeoutError) as exc:
        # A non-streamed turn that outlives the read timeout is the exact
        # condition streaming exists to avoid, so retrying is worthwhile.
        raise TransientError(
            "network timeout after %ss calling %s (%s)" % (per_read, target, exc),
            "timeout",
            EXIT_NETWORK,
        )
    except (ConnectionResetError, BrokenPipeError) as exc:
        raise TransientError(
            "the connection dropped: %s" % exc, "connection reset", EXIT_NETWORK
        )
    except http.client.HTTPException as exc:
        raise TransientError(
            "the response body was cut short: %s" % exc, "incomplete stream", EXIT_NETWORK
        )


def post_messages(cfg, payload, timeout=None, url=None, total_timeout=None):
    """POST to {base}/v1/messages and return an HttpResponse.

    Streams by default and retries transient failures up to ``BIGBRAIN_RETRIES``
    times, printing a ``[Bigbrain] transient error ..., retry n/N`` line per
    attempt.  Raises BigbrainError with a mapped exit code when the call cannot
    be completed.
    """
    base = cfg.get("base_url") or ""
    target = url or (base.rstrip("/") + "/v1/messages")
    if not base and not url:
        raise BigbrainError("BIGBRAIN_BASE_URL is not set", EXIT_CONFIG)

    stream = bool(payload.get("stream", cfg.get("stream", DEFAULT_STREAM)))
    # Normalise the body to match the transport actually being used.  A caller
    # that built its own request dict (check_config does) would otherwise get a
    # streamed client reading a non-streamed body, which parses as zero events.
    payload = dict(payload)
    if stream:
        payload["stream"] = True
    else:
        payload.pop("stream", None)
    retries = int(cfg.get("retries", DEFAULT_RETRIES))
    backoff = float(cfg.get("retry_backoff", DEFAULT_RETRY_BACKOFF))
    per_read, total = _timeouts(cfg, timeout, total_timeout)

    send = _post_stream if stream else _post_plain
    attempt = 0
    while True:
        attempt += 1
        try:
            return send(cfg, payload, target, per_read, total)
        except TransientError as exc:
            if attempt > retries:
                raise BigbrainError(str(exc), exc.exit_code, **exc.extra)
            eprint(
                "%s transient error %s, retry %d/%d"
                % (PROGRESS_PREFIX, exc.label, attempt, retries)
            )
            if backoff:
                time.sleep(backoff * attempt)
        except urllib.error.HTTPError as exc:
            text = ""
            try:
                text = exc.read().decode("utf-8", "replace")
            except Exception:  # pragma: no cover - defensive
                pass
            status = exc.code
            code, label = _classify_http_status(status)
            detail = "%s: HTTP %d from %s -- %s" % (label, status, target, _short_body(text))
            if status in TRANSIENT_HTTP_STATUSES:
                if attempt > retries:
                    raise BigbrainError(detail, code, http_status=status, body=text)
                eprint(
                    "%s transient error %d, retry %d/%d"
                    % (PROGRESS_PREFIX, status, attempt, retries)
                )
                if backoff:
                    time.sleep(backoff * attempt)
                continue
            raise BigbrainError(detail, code, http_status=status, body=text)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise BigbrainError(
                    "network timeout after %ss calling %s" % (per_read, target), EXIT_NETWORK
                )
            # A reset connection surfaces as ConnectionResetError on Linux and
            # macOS alike; a relay hanging up mid-response lands here too.
            if isinstance(reason, (ConnectionResetError, BrokenPipeError)):
                if attempt > retries:
                    raise BigbrainError(
                        "network error calling %s: %s" % (target, reason), EXIT_NETWORK
                    )
                eprint(
                    "%s transient error connection reset, retry %d/%d"
                    % (PROGRESS_PREFIX, attempt, retries)
                )
                if backoff:
                    time.sleep(backoff * attempt)
                continue
            raise BigbrainError(
                "network error calling %s: %s (DNS failure, connection refused, or proxy problem)"
                % (target, reason),
                EXIT_NETWORK,
            )
        except OSError as exc:
            raise BigbrainError("network error calling %s: %s" % (target, exc), EXIT_NETWORK)


# --------------------------------------------------------------------------
# Model catalogue (GET /v1/models)
# --------------------------------------------------------------------------


def _read_catalogue(response, deadline):
    """Stop even a continuously trickling body when its total budget expires."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("model catalogue time budget exhausted")
    # urllib exposes the HTTPResponse's buffered socket here. Shutdown interrupts
    # an active read; closing the buffered response from another thread can block.
    sock = response.fp.raw._sock

    def interrupt():
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # The response may have already closed the socket at EOF.

    timer = threading.Timer(remaining, interrupt)
    timer.daemon = True
    timer.start()
    try:
        return response.read().decode("utf-8", "replace")
    finally:
        timer.cancel()
        timer.join()
        if time.monotonic() >= deadline:
            raise TimeoutError("model catalogue time budget exhausted")


def list_models(cfg, timeout=None, after_id=None, total_timeout=None):
    """GET ``{base}/v1/models`` and return the decoded body.

    Relays expose the model ids they actually serve here, which is the reliable
    way to translate an Anthropic-style dotted id (``claude-opus-5.5``) into the
    hyphenated form a relay expects (``claude-opus-5-5``).
    """
    base = cfg.get("base_url") or ""
    if not base:
        raise BigbrainError("BIGBRAIN_BASE_URL is not set", EXIT_CONFIG)
    target = models_url(cfg)
    if after_id is not None:
        target += "?" + urllib.parse.urlencode({"after_id": after_id})
    headers = dict(_headers(cfg))
    headers["accept"] = "application/json"
    request = urllib.request.Request(target, headers=headers, method="GET")
    per_read = timeout or cfg.get("timeout") or DEFAULT_TIMEOUT
    total = total_timeout if total_timeout is not None else cfg.get("max_total_timeout") or DEFAULT_MAX_TOTAL_TIMEOUT
    deadline = time.monotonic() + total
    try:
        try:
            response = _opener(target).open(request, timeout=min(per_read, total))
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.fp if isinstance(response, urllib.error.HTTPError) else response
            text = _read_catalogue(raw, deadline)
            # Redact the complete body before any diagnostic truncation. JSON
            # escaping must not let a quoted/backslashed key evade replacement.
            safe_text = text
            key = cfg.get("api_key")
            if key:
                for spelling in (json.dumps(key)[1:-1], key):
                    safe_text = safe_text.replace(spelling, mask_secret(key))
            if isinstance(response, urllib.error.HTTPError):
                code, label = _classify_http_status(response.code)
                raise BigbrainError(
                    "%s: HTTP %d from GET %s -- %s" % (label, response.code, target, _short_body(safe_text)),
                    code, http_status=response.code, body=safe_text,
                )
            try:
                return json.loads(text)
            except ValueError:
                raise BigbrainError(
                    "GET %s did not return JSON: %s" % (target, _short_body(safe_text)), EXIT_HTTP
                )
    except (socket.timeout, TimeoutError):
        raise BigbrainError("network timeout calling %s (read limit %ss, total budget %ss)"
                            % (target, per_read, total), EXIT_NETWORK) from None
    except urllib.error.URLError as exc:
        raise BigbrainError(
            "network error calling %s: %s" % (target, getattr(exc, "reason", exc)), EXIT_NETWORK
        )
    except OSError as exc:
        raise BigbrainError("network error calling %s: %s" % (target, exc), EXIT_NETWORK)
    except http.client.HTTPException:
        raise BigbrainError("incomplete model catalogue from %s" % target, EXIT_NETWORK) from None


def model_ids(body):
    """Pull the id strings out of a ``/v1/models`` body.

    Accepts the Anthropic shape (``{"data": [{"id": ...}]}``) and the
    OpenAI shape (``{"data": [...], "object": "list"}``), since relays serve
    either.  Unknown shapes yield an empty list rather than an exception.
    """
    items = body
    if isinstance(body, dict):
        items = body.get("data", body.get("models"))
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key in ("id", "name", "model"):
                if isinstance(item.get(key), str):
                    out.append(item[key])
                    break
    return out


__all__ = [
    "HttpResponse",
    "TransientError",
    "build_payload",
    "extract_text",
    "list_models",
    "mask_secret",
    "messages_url",
    "model_ids",
    "models_url",
    "post_messages",
    "usage_of",
]
