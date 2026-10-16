#!/usr/bin/env python3
"""A tiny, local, Anthropic-compatible Messages API server for testing bigbrain.

It implements just enough of POST /v1/messages -- plus GET /v1/models -- to
exercise the whole skill offline: scripted multi-round advisor replies, auth
failures, missing models, server errors, unparseable garbage, proxy timeouts
and truncated streams.

Streaming is supported: when the request body carries ``"stream": true`` the
reply is written as Anthropic SSE events (``message_start``, ``ping``,
``content_block_delta``, ``message_delta``, ``message_stop``).  Otherwise the
same reply is returned as one JSON body.  That means the mock exercises both
client transports from a single script.

Usage:
  mock_server.py [--host 127.0.0.1] [--port 0] [--api-key test-key]
                 [--mode ok|401|404model|404path|500|garbage|prose|524|524once|incomplete]
                 [--fail-count N] [--script NAME_OR_FILE] [--port-file FILE]
                 [--requests-out FILE] [--quiet]

--port 0 picks a free port; the chosen port is written to --port-file (and the
URL is printed on the first stdout line) so callers can read it.

--script accepts either a named built-in scenario or a path to a JSON list:

  milestones            the full 5-round milestone run + retrospective (default)
  continue-forever      one reply that never finishes -> max-rounds path
  blocked               a real blocker
  stuck                 a reply for a `stuck` re-escalation
  done-without-criteria done with no criteria_status -> must keep looping

Once a script runs out, its final entry repeats, so a "continue forever" script
reliably drives the max-rounds path.

--mode extras for the transport layer:

  524        every request answers HTTP 524 (proxy read timeout), never OK
  524once    the first --fail-count requests answer 524, then the script runs
  524once    (default --fail-count 1) -- proves retry-then-success
  incomplete the stream ends without message_stop -- proves the client notices
  404path    a plain 404 that names no model -- a wrong base URL, not a wrong model
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bigbrain import fixtures  # noqa: E402  (path setup must come first)

DEFAULT_API_KEY = "test-key"
DEFAULT_SCENARIO = "milestones"

#: Chunks per streamed reply.  More than one so the client's delta assembly is
#: genuinely exercised rather than trivially satisfied by a single event.
STREAM_CHUNKS = 3

MODELS = [
    {"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5"},
    {"id": "claude-sonnet-5-5", "type": "model", "display_name": "Claude Sonnet 5.5"},
    {"id": "claude-haiku-5-5", "type": "model", "display_name": "Claude Haiku 5.5"},
]


class State:
    def __init__(self, args):
        self.lock = threading.Lock()
        self.sequence = load_sequence(args.script)
        self.index = 0
        self.requests = []
        self.mode = args.mode
        self.api_key = args.api_key
        self.fail_524 = args.fail_count
        if self.fail_524 is None:
            self.fail_524 = 1 if args.mode == "524once" else 0

    def next_entry(self):
        with self.lock:
            index = min(self.index, len(self.sequence) - 1)
            self.index += 1
            return self.sequence[index]

    def record(self, entry):
        with self.lock:
            self.requests.append(entry)

    def take_524(self):
        """True when this request should be answered with a proxy timeout."""
        with self.lock:
            if self.mode == "524":
                return True
            if self.fail_524 > 0:
                self.fail_524 -= 1
                return True
            return False


def load_sequence(spec):
    """Resolve --script: a named fixture, or a path to a JSON list."""
    if spec is None:
        return fixtures.scenario(DEFAULT_SCENARIO)

    named = fixtures.scenario(spec)
    if named is not None:
        return named

    try:
        data = json.loads(Path(spec).read_text(encoding="utf-8"))
    except OSError as exc:
        sys.exit("mock_server: cannot read --script %s: %s\nknown scenarios: %s"
                 % (spec, exc, ", ".join(sorted(fixtures.SCENARIOS))))
    except ValueError as exc:
        sys.exit("mock_server: --script %s is not valid JSON: %s" % (spec, exc))
    if isinstance(data, dict):
        data = data.get("responses", data.get("rounds"))
    if not isinstance(data, list) or not data:
        sys.exit("mock_server: --script %s must be a non-empty JSON list" % spec)
    return data


def text_and_usage(entry):
    """Split a scripted entry into (reply text, usage or None, stop_reason or None).

    The third element lets a script reproduce the failure that costs a real run
    a whole extra call: a reply whose JSON is cut off mid-object because the
    model hit its output ceiling.  See fixtures.truncated_script.
    """
    if isinstance(entry, str):
        return entry, None, None
    if isinstance(entry, dict):
        if set(entry) <= {"text", "reply", "usage", "note", "stop_reason"} and (
            "text" in entry or "reply" in entry or "usage" in entry
        ):
            text = entry.get("text", entry.get("reply", ""))
            return str(text), entry.get("usage"), entry.get("stop_reason")
        if "text" in entry and "status" not in entry and "lessons" not in entry:
            return str(entry["text"]), entry.get("usage"), entry.get("stop_reason")
    return json.dumps(entry, ensure_ascii=False), None, None


def message_response(text, model, max_tokens, usage=None, stop_reason="end_turn"):
    """Build an Anthropic-shaped response, with a realistic usage block.

    Token counts matter now that the report sums them (item 3), so the mock
    reports plausible numbers rather than a constant: roughly four characters
    per token, which is what the estimator the loop falls back on assumes.
    """
    if usage is None:
        usage = {
            "input_tokens": 512,
            "output_tokens": max(1, len(str(text or "")) // 4),
        }
    return {
        "id": "msg_mock_0001",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0)),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0)),
        },
    }


def sse_frame(event, data):
    """One SSE event, encoded exactly as the Anthropic API writes it."""
    return ("event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))).encode("utf-8")


def sse_events(text, model, usage, stop_reason="end_turn"):
    """Yield the SSE frames for one complete streamed reply.

    The reply text is split across several ``content_block_delta`` events and a
    ``ping`` is interleaved, so a client that only reads the first chunk, or
    that mishandles keep-alives, fails the tests rather than passing by luck.
    """
    text = str(text or "")
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))

    yield sse_frame("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_mock_stream",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            # A cached prompt: the client must fold these into input tokens.
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 64)),
                "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 128)),
                "output_tokens": 1,
            },
        },
    })
    yield sse_frame("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    yield sse_frame("ping", {"type": "ping"})

    size = max(1, (len(text) + STREAM_CHUNKS - 1) // STREAM_CHUNKS) if text else 0
    for start in range(0, len(text), size):
        yield sse_frame("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text[start:start + size]},
        })
        yield sse_frame("ping", {"type": "ping"})

    yield sse_frame("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield sse_frame("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })
    yield sse_frame("message_stop", {"type": "message_stop"})


class Handler(BaseHTTPRequestHandler):
    server_version = "bigbrain-mock/2.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write("mock_server: %s\n" % (fmt % args))

    # -- helpers ---------------------------------------------------------
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, err_type, message):
        self._send_json(status, {"type": "error", "error": {"type": err_type, "message": message}})

    def _send_524(self):
        """A Cloudflare-style proxy read timeout: HTML body, no JSON."""
        body = (b"<html><head><title>524: A timeout occurred</title></head>"
                b"<body><h1>Error 524: A timeout occurred</h1>"
                b"<p>The origin web server did not return a complete response within the "
                b"120-second Proxy Read Timeout window.</p></body></html>")
        self.send_response(524)
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    def _auth_ok(self):
        key = self.headers.get("x-api-key") or ""
        if not key:
            auth = self.headers.get("authorization") or ""
            if auth.lower().startswith("bearer "):
                key = auth[7:].strip()
        return key == self.server.state.api_key

    def _respond(self, text, model, usage, stream, complete=True, stop_reason="end_turn"):
        """Send one reply, streamed or not.

        ``complete=False`` truncates the stream before ``message_stop``, which is
        what a proxy that gives up mid-turn looks like on the wire.
        ``stop_reason="max_tokens"`` is a different failure: a complete, well-formed
        response whose text stops mid-JSON because the model hit its output
        ceiling.  The client must tell those apart, because only the second one
        is worth retrying with a bigger budget.
        """
        if not stream:
            self._send_json(200, message_response(text, model, 0, usage, stop_reason))
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        # No content-length: the body is delimited by EOF.  Closing the
        # connection is also how the truncated case is signalled.
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True

        events = list(sse_events(text, model, usage, stop_reason=stop_reason))
        if not complete:
            # Drop message_delta/message_stop, keep the deltas: a partial reply.
            events = events[: max(1, len(events) - 2)]
        for frame in events:
            try:
                self.wfile.write(frame)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            if stream and not complete:
                time.sleep(0.001)

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/health", "/healthz"):
            self._send_json(200, {"ok": True})
        elif path == "/requests":
            # Live introspection, so a test can assert on what went on the wire
            # without waiting for the server to shut down.
            self._send_json(200, {"requests": list(self.server.state.requests)})
        elif path.endswith("/v1/models"):
            if not self._auth_ok():
                self._error(401, "authentication_error", "missing or wrong API key")
                return
            self._send_json(200, {
                "data": MODELS,
                "has_more": False,
                "first_id": MODELS[0]["id"],
                "last_id": MODELS[-1]["id"],
            })
        else:
            self._error(404, "not_found_error", "no GET route %s" % self.path)

    def do_POST(self):
        state = self.server.state
        path = self.path.split("?", 1)[0].rstrip("/")
        if not path.endswith("/v1/messages"):
            self._error(404, "not_found_error", "unknown path %s" % self.path)
            return

        body = self._read_body()
        if body is None:
            self._error(400, "invalid_request_error", "body was not JSON")
            return

        stream = bool(body.get("stream"))
        has_cache = "cache_control" in json.dumps([body.get("system"), body.get("messages")])
        state.record(
            {
                "list_system": isinstance(body.get("system"), list),
                "cache_control": has_cache,
                "model": body.get("model"),
                "max_tokens": body.get("max_tokens"),
                "messages": body.get("messages"),
                "system_chars": len(str(body.get("system") or "")),
                "has_milestone_contract": "milestones" in str(body.get("system") or ""),
                "stream": stream,
            }
        )

        # The proxy-timeout simulation comes first: a 524 never reaches the
        # script, and the retry that follows hits a healthy server.
        if state.take_524():
            self._send_524()
            return

        if state.mode == "401":
            self._error(401, "authentication_error", "invalid x-api-key (mode=401)")
            return
        if state.mode == "404model":
            self._error(404, "not_found_error",
                        "model: %s not found (mode=404model)" % body.get("model"))
            return
        if state.mode == "404path":
            # A wrong base URL: the route does not exist, and nothing mentions a model.
            self._error(404, "not_found_error", "Not Found (mode=404path)")
            return
        if state.mode == "500":
            self._error(500, "api_error", "internal server error (mode=500)")
            return

        model = body.get("model") or "mock-model"

        if state.mode == "prose":
            # A 200 that is not the model we asked for: a paragraph of prose in
            # answer to any prompt.  check_config must warn about this.
            self._respond(
                "Sure! Here is my assessment:\n\nI think you should probably not do that, "
                "because the requirements are unclear and you should ask the user first.",
                model, {"input_tokens": 512, "output_tokens": 40}, stream,
            )
            return

        if not self._auth_ok():
            self._error(401, "authentication_error", "missing or wrong API key")
            return

        if state.mode == "garbage":
            self._respond(
                "Sure! Here is my assessment:\n\nI think you should probably "
                "not-json at all {{ broken",
                model, {"input_tokens": 512, "output_tokens": 30}, stream,
            )
            return

        if state.mode == "html":
            # A 200 with an HTML body: a misconfigured base URL pointing at a
            # web page, not an API.  check_config must reject the envelope.
            body = (b"<!doctype html><html><head><title>Welcome</title></head>"
                    b"<body><h1>Hello</h1><p>This is a website, not an API.</p></body></html>")
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # A real minimal call (the check_config ping) gets a plain pong.
        messages = body.get("messages") or []
        only = messages[-1].get("content") if messages else ""
        if len(messages) == 1 and isinstance(only, str) and only.strip().lower() == "ping":
            self._respond("pong", model, {"input_tokens": 8, "output_tokens": 2}, stream)
            return

        entry = state.next_entry()
        text, usage, stop_reason = text_and_usage(entry)
        if usage is None:
            usage = {
                "input_tokens": 512,
                "output_tokens": max(1, len(str(text or "")) // 4),
            }
        if has_cache and "cache_read_input_tokens" not in usage:
            # Mimic a caching relay: the first call writes the prefix, later calls read it.
            usage = dict(usage)
            if getattr(state, "cache_calls", 0) > 0:
                usage["cache_creation_input_tokens"] = 0
                usage["cache_read_input_tokens"] = 256
            else:
                usage["cache_creation_input_tokens"] = 256
                usage["cache_read_input_tokens"] = 0
            state.cache_calls = getattr(state, "cache_calls", 0) + 1
        self._respond(
            text, model, usage, stream, complete=(state.mode != "incomplete"),
            stop_reason=stop_reason or "end_turn",
        )


def serve(args):
    state = State(args)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.state = state
    server.verbose = not args.quiet
    host, port = server.server_address[0], server.server_address[1]
    url = "http://%s:%d" % (host, port)

    if args.port_file:
        Path(args.port_file).write_text(str(port), encoding="utf-8")
    print(url, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if args.requests_out:
            Path(args.requests_out).write_text(
                json.dumps(state.requests, indent=2), encoding="utf-8"
            )
        server.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mock_server.py")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--mode", default="ok",
                        choices=["ok", "401", "404model", "404path", "500", "garbage", "prose", "html",
                                 "524", "524once", "incomplete"])
    parser.add_argument("--fail-count", type=int, default=None,
                        help="with --mode 524once: how many requests answer 524 first")
    parser.add_argument("--script", default=None,
                        help="scenario name (%s) or a path to a JSON list"
                             % ", ".join(sorted(fixtures.SCENARIOS)))
    parser.add_argument("--port-file", default=None, help="write the chosen port here")
    parser.add_argument("--requests-out", default=None,
                        help="write the received requests here on shutdown")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.quiet:
        print("scenario: %s (%d scripted replies)"
              % (args.script or DEFAULT_SCENARIO, len(load_sequence(args.script) or [])),
              file=sys.stderr)
    return serve(args)


if __name__ == "__main__":
    sys.exit(main())
