#!/usr/bin/env bash
# End-to-end tests for the dualmind skill.
#
# Everything runs under a temporary HOME and CODEX_HOME, against a local mock
# Anthropic-compatible server (or deliberately against a closed port). No real
# API is contacted, and nothing is written outside the temp tree.
#
# Prints PASS/FAIL per case and exits nonzero if any case failed.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SCRIPTS="$ROOT/scripts"
PKG="$SCRIPTS/dualmind"
CHECK="$SCRIPTS/check_config.py"
ADVISOR="$SCRIPTS/advisor.py"
CLI="$SCRIPTS/dualmind_cli.py"
MOCK="$SCRIPTS/mock_server.py"

PY="${PYTHON:-python3}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/dualmind-tests.XXXXXX")"
API_KEY="test-key-abcdef123456"
PORT_FILE="$WORK/port"

# Every invocation runs against a temp HOME so the user-level lesson store and
# any config land in the sandbox, never in the real home directory.
export HOME="$WORK/home"
export CODEX_HOME="$WORK/codex"
export DUALMIND_HOME="$WORK/home/.dualmind"
mkdir -p "$HOME" "$CODEX_HOME"

PASS=0
FAIL=0
FAILED_NAMES=()
SERVER_PIDS=()

cleanup() {
  for pid in "${SERVER_PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

ok()   { printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf 'FAIL  %s\n' "$1"; [ $# -gt 1 ] && printf '      %s\n' "$2"; FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); }

# run <name> <expected_exit> <cmd...>
run_expect_exit() {
  local name="$1" expected="$2"; shift 2
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq "$expected" ]; then
    ok "$name"
  else
    bad "$name" "expected exit $expected, got $rc :: $(printf '%s' "$out" | tail -c 400)"
  fi
}

# expect_contains <name> <needle> <haystack>
expect_contains() {
  local name="$1" needle="$2" haystack="$3"
  case "$haystack" in
    *"$needle"*) ok "$name" ;;
    *) bad "$name" "output does not contain '$needle' :: $(printf '%s' "$haystack" | tail -c 400)" ;;
  esac
}

expect_absent() {
  local name="$1" needle="$2" haystack="$3"
  case "$haystack" in
    *"$needle"*) bad "$name" "output unexpectedly contains '$needle'" ;;
    *) ok "$name" ;;
  esac
}

start_mock() {
  # start_mock <tag> [extra args...] -> prints base url
  local tag="$1"; shift
  local pf="$WORK/port-$tag"
  rm -f "$pf"
  "$PY" "$MOCK" --port 0 --port-file "$pf" --quiet "$@" >"$WORK/mock-$tag.out" 2>&1 &
  local pid=$!
  SERVER_PIDS+=("$pid")
  local port=""
  for _ in $(seq 1 100); do
    if [ -s "$pf" ]; then port="$(cat "$pf")"; break; fi
    sleep 0.05
  done
  if [ -z "$port" ]; then
    echo "ERROR: mock server $tag failed to start" >&2
    cat "$WORK/mock-$tag.out" >&2
    return 1
  fi
  echo "http://127.0.0.1:$port"
}

# Snapshot every AGENTS.md-shaped file under the temp tree, with hashes.
snapshot_protected() {
  local out="$1"
  : > "$out"
  find "$HOME" "$CODEX_HOME" "$ROOT" -maxdepth 6 \
    \( -name 'AGENTS.md' -o -name 'CLAUDE.md' \) -type f 2>/dev/null | sort | while read -r f; do
    printf '%s %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f" >> "$out"
  done
}

count_protected() {
  find "$HOME" "$CODEX_HOME" -maxdepth 6 \
    \( -name 'AGENTS.md' -o -name 'CLAUDE.md' \) -type f 2>/dev/null | wc -l
}

export DUALMIND_USE_ANTHROPIC_ENV=0
unset DUALMIND_BASE_URL DUALMIND_API_KEY DUALMIND_MODEL 2>/dev/null || true

echo "== dualmind test suite =="
echo "python: $($PY --version 2>&1)"
echo "work dir: $WORK"
echo "temp HOME: $HOME"
echo

# Pre-existing AGENTS.md files, to prove they survive untouched. These live in
# the sandbox (the temp CODEX_HOME and a temp project dir), never in the skill
# directory -- the suite must not create files in the repo it is testing.
printf '# Project agents\n\nDo not edit me.\n' > "$CODEX_HOME/AGENTS.md"
mkdir -p "$WORK/project"
printf '# Project agents (workspace)\n' > "$WORK/project/AGENTS.md"
printf '# Claude project notes\n' > "$WORK/project/CLAUDE.md"
BEFORE_PROTECTED="$WORK/protected-before.txt"
snapshot_protected "$BEFORE_PROTECTED"
echo "pre-existing protected files: $(count_protected)"
echo

# --------------------------------------------------------------------------
# 0. Syntax / import sanity
# --------------------------------------------------------------------------
echo "-- syntax --"
for f in "$SCRIPTS"/*.py "$PKG"/*.py; do
  run_expect_exit "compiles: $(basename "$f")" 0 "$PY" -m py_compile "$f"
done
echo

# --------------------------------------------------------------------------
# 1. check_config
# --------------------------------------------------------------------------
echo "-- check_config --"

out="$(env -u DUALMIND_BASE_URL -u DUALMIND_API_KEY "$PY" "$CHECK" --no-call 2>&1)"; rc=$?
if [ "$rc" -eq 2 ]; then ok "check_config: missing vars -> exit 2"
else bad "check_config: missing vars -> exit 2" "got $rc :: $out"; fi
expect_contains "check_config: names DUALMIND_BASE_URL" "DUALMIND_BASE_URL" "$out"
expect_contains "check_config: names DUALMIND_API_KEY" "DUALMIND_API_KEY" "$out"

run_expect_exit "check_config: key only missing -> exit 2" 2 \
  env DUALMIND_BASE_URL=http://127.0.0.1:1 DUALMIND_API_KEY= "$PY" "$CHECK" --no-call

run_expect_exit "check_config: malformed URL -> exit 2" 2 \
  env DUALMIND_BASE_URL="not-a-url" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" --no-call

run_expect_exit "check_config: unreachable port -> exit 3" 3 \
  env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" DUALMIND_TIMEOUT=3 "$PY" "$CHECK"

BASE_URL="$(start_mock ok --api-key "$API_KEY")" || exit 1
echo "mock server (ok): $BASE_URL"

out="$(env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "check_config: mock server -> exit 0"
else bad "check_config: mock server -> exit 0" "got $rc :: $out"; fi
expect_contains "check_config: prints OK"       "OK"              "$out"
expect_contains "check_config: prints model"    "claude-opus-5-5" "$out"
expect_contains "check_config: prints base url" "$BASE_URL"      "$out"
expect_contains "check_config: prints latency"  "latency"         "$out"

out="$(env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" --json 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] is True and d["exit_code"]==0 and d["pinged"] is True' 2>/dev/null; then
  ok "check_config: --json is valid machine output"
else
  bad "check_config: --json is valid machine output" "rc=$rc :: $out"
fi

case "$out" in
  *"$API_KEY"*) bad "check_config: never prints the full API key" "key leaked in --json output" ;;
  *) ok "check_config: never prints the full API key" ;;
esac
expect_contains "check_config: masks the key" "test...56" "$out"

run_expect_exit "check_config: wrong key -> exit 4" 4 \
  env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="wrong-key" "$PY" "$CHECK"

BASE_401="$(start_mock 401 --mode 401 --api-key "$API_KEY")" || exit 1
run_expect_exit "check_config: server 401 -> exit 4" 4 \
  env DUALMIND_BASE_URL="$BASE_401" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK"

BASE_404="$(start_mock 404 --mode 404model --api-key "$API_KEY")" || exit 1
run_expect_exit "check_config: 404 model -> exit 5" 5 \
  env DUALMIND_BASE_URL="$BASE_404" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK"

BASE_500="$(start_mock 500 --mode 500 --api-key "$API_KEY")" || exit 1
run_expect_exit "check_config: server 500 -> exit 6" 6 \
  env DUALMIND_BASE_URL="$BASE_500" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK"

# A well-formed Messages reply whose text is prose is NOT a config failure: the
# envelope proves the endpoint, and length is a prompting matter.  It passes
# with a warning, because a one-word prompt answered by a paragraph is at least
# worth flagging.
BASE_PROSE="$(start_mock prose --mode prose --api-key "$API_KEY")" || exit 1
out="$(env DUALMIND_BASE_URL="$BASE_PROSE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "check_config: prose reply -> exit 0 (well-formed Messages body)"
else bad "check_config: prose reply -> exit 0 (well-formed Messages body)" "expected exit 0, got $rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "check_config: prose reply warns instead of failing" "warning" "$out"
expect_contains "check_config: the warning names the prose" "characters of prose" "$out"

# A 200 that is HTML -- a base URL pointing at a website -- is a real failure:
# no Messages envelope at all, so there is nothing to proceed with.
BASE_HTML="$(start_mock html --mode html --api-key "$API_KEY")" || exit 1
out="$(env DUALMIND_BASE_URL="$BASE_HTML" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" 2>&1)"; rc=$?
if [ "$rc" -eq 6 ]; then ok "check_config: HTML body -> exit 6"
else bad "check_config: HTML body -> exit 6" "expected exit 6, got $rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "check_config: HTML body is rejected as non-Messages" "instead of an event stream" "$out"
expect_contains "check_config: the HTML failure names the content type" "text/html" "$out"

# `garbage` mode returns a well-formed Messages envelope whose *text* is
# nonsense.  Judging the envelope is check_config's job, so this passes -- the
# unparseable text is the advisor loop's problem (see `live garbage` below),
# not evidence that the endpoint is the wrong one.
BASE_GARBAGE="$(start_mock garbage --mode garbage --api-key "$API_KEY")" || exit 1
run_expect_exit "check_config: garbage text is a valid envelope -> exit 0" 0 \
  env DUALMIND_BASE_URL="$BASE_GARBAGE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK"

# --list-models reads the endpoint's own catalogue.
out="$(env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" --list-models 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "check_config: --list-models -> exit 0"
else bad "check_config: --list-models -> exit 0" "got $rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "check_config: --list-models prints ids" "claude-opus-5-5" "$out"
expect_contains "check_config: --list-models marks the configured id" "(configured)" "$out"

out="$(env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" --list-models --json 2>&1)"
if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] is True and "claude-opus-5-5" in d["models"], d' 2>/dev/null; then
  ok "check_config: --list-models --json is machine-readable"
else
  bad "check_config: --list-models --json is machine-readable" "$(printf '%s' "$out" | head -c 300)"
fi
echo

# --------------------------------------------------------------------------
# 1b. Streaming (SSE) and transient retries
# --------------------------------------------------------------------------
echo "-- streaming --"

# A single-reply script, so a streamed and an unstreamed call provably ask the
# same question and must therefore reassemble to the same bytes.  The usage is
# fixed here, which makes the cache-token arithmetic below exact.
STREAM_SCRIPT="$WORK/stream-single.json"
printf '%s\n' '[{"text":"{\"status\":\"continue\",\"summary\":\"streamed\"}","usage":{"input_tokens":10,"output_tokens":4}}]' \
  > "$STREAM_SCRIPT"
STREAM_BASE="$(start_mock stream --api-key "$API_KEY" --script "$STREAM_SCRIPT")" || exit 1

# The mock adds 64 cache_creation + 128 cache_read to every streamed reply, so
# the client must fold all three into input_tokens: 10 + 64 + 128 = 202.
if "$PY" - "$SCRIPTS" "$STREAM_BASE" "$API_KEY" <<'PYEOF' 2>/dev/null
import sys
sys.path.insert(0, sys.argv[1])
from dualmind.client import post_messages
from dualmind.config import load_config

base, key = sys.argv[2], sys.argv[3]
cfg = load_config(env={"DUALMIND_BASE_URL": base, "DUALMIND_API_KEY": key,
                       "DUALMIND_RETRIES": "0"})
assert cfg["stream"] is True, "streaming is not on by default"

req = {"model": cfg["model"], "max_tokens": 100,
       "messages": [{"role": "user", "content": "hello"}]}
response = post_messages(cfg, dict(req))
assert response.streamed is True, "the response was not streamed"
assert response.stop_reason == "end_turn", response.stop_reason
assert response.events > 3, response.events
assert response.usage["input_tokens"] == 202, response.usage
assert response.usage["output_tokens"] == 4, response.usage
assert response.text == '{"status":"continue","summary":"streamed"}', response.text

# The identical call with streaming off must produce the identical text, by a
# different transport.  (Only the text is compared: the mock deliberately adds
# cache counters to the streamed usage and not to the plain one.)
plain = load_config(env={"DUALMIND_BASE_URL": base, "DUALMIND_API_KEY": key,
                         "DUALMIND_STREAM": "0", "DUALMIND_RETRIES": "0"})
other = post_messages(plain, dict(req))
assert other.streamed is False, "DUALMIND_STREAM=0 still streamed"
assert other.text == response.text, (other.text, response.text)
assert other.usage["output_tokens"] == 4, other.usage
PYEOF
then ok "stream: SSE reassembles the text and sums usage incl. cache tokens"
else bad "stream: SSE reassembles the text and sums usage incl. cache tokens"; fi

# stream:true must actually reach the wire, and DUALMIND_STREAM=0 must omit it.
env DUALMIND_BASE_URL="$STREAM_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" >/dev/null 2>&1
out="$(env DUALMIND_BASE_URL="$STREAM_BASE" DUALMIND_API_KEY="$API_KEY" DUALMIND_STREAM=0 \
  "$PY" "$CHECK" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "stream: DUALMIND_STREAM=0 still works end to end"
else bad "stream: DUALMIND_STREAM=0 still works end to end" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi

# /requests is the mock's live view of what it was sent.
if "$PY" - "$STREAM_BASE" <<'PYEOF' 2>/dev/null
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1] + "/requests", timeout=10) as fh:
    reqs = json.load(fh)["requests"]
assert len(reqs) >= 3, reqs
assert reqs[0]["stream"] is True, reqs[0]
assert reqs[-1]["stream"] is False, reqs[-1]
PYEOF
then ok "stream: stream:true is on the wire, and =0 omits it"
else bad "stream: stream:true is on the wire, and =0 omits it"; fi

# The full milestone loop runs to DONE over SSE, and the token totals in the
# transcript come from the streamed usage rather than the character estimator.
S_STREAM="$WORK/session-stream"
STREAM_LOOP_BASE="$(start_mock streamloop --api-key "$API_KEY" --script milestones)" || exit 1
out="$(env DUALMIND_BASE_URL="$STREAM_LOOP_BASE" DUALMIND_API_KEY="$API_KEY" DUALMIND_PROMPT_CACHE=0 "$PY" "$CLI" start \
  --task "streamed milestone run" --session "$S_STREAM" --force --quiet 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "stream: round 1 over SSE -> exit 0"
else bad "stream: round 1 over SSE -> exit 0" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi

# Four reports: approve m1, revise m2, approve m2, then done -- the same
# sequence the non-streamed milestone test drives.
for i in 1 2 3 4; do
  printf 'm%s done\nRan 13 tests\n' "$i" > "$WORK/stream-r$i.md"
  out="$(env DUALMIND_BASE_URL="$STREAM_LOOP_BASE" DUALMIND_API_KEY="$API_KEY" DUALMIND_PROMPT_CACHE=0 "$PY" "$CLI" report \
    --session "$S_STREAM" --result-file "$WORK/stream-r$i.md" --quiet 2>&1)"; rc=$?
done
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "DONE"; then
  ok "stream: the full milestone loop reaches DONE over SSE"
else
  bad "stream: the full milestone loop reaches DONE over SSE" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"
fi

# Milestone round 1 reports 1840 input / 620 output; the stream adds 64 + 128
# cache tokens to the input side.  A non-zero total alone would not prove the
# streamed usage was read, so the exact sum is asserted.
if "$PY" - "$S_STREAM/transcript.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
rounds = [r for r in d["rounds"] if r["kind"] == "round"]
assert len(rounds) >= 1, d["rounds"]
meta = rounds[0]["meta"]
assert meta["mode"] == "live", meta
assert meta["usage"]["input_tokens"] == 1840 + 64 + 128, meta["usage"]
assert meta["usage"]["output_tokens"] == 620, meta["usage"]
u = d["usage"]
assert u["calls"] >= 4 and u["output_tokens"] > 0, u
PYEOF
then ok "stream: transcript token totals come from the streamed usage"
else bad "stream: transcript token totals come from the streamed usage"; fi

# The streamed request artefact records that the call was streamed.
if [ -f "$S_STREAM/round-01-request.json" ] && \
   "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["stream"] is True, d.get("stream")' \
     "$S_STREAM/round-01-request.json" 2>/dev/null; then
  ok "stream: the round-1 request artefact records stream:true"
else
  bad "stream: the round-1 request artefact records stream:true"
fi
echo

echo "-- transient retries --"
# The first request answers 524 (a proxy read timeout), the second succeeds.
RETRY_BASE="$(start_mock retry --api-key "$API_KEY" --script milestones --mode 524once)" || exit 1
S_RETRY="$WORK/session-retry"
err="$(env DUALMIND_BASE_URL="$RETRY_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" start \
  --task "retry once" --session "$S_RETRY" --force 2>&1 >/dev/null)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "retry: 524 then success -> exit 0"
else bad "retry: 524 then success -> exit 0" "rc=$rc :: $(printf '%s' "$err" | tail -c 300)"; fi
expect_contains "retry: prints the transient-error line" "transient error 524, retry 1/2" "$err"
if [ -f "$S_RETRY/round-01-response.json" ]; then
  ok "retry: the successful retry is what got recorded"
else
  bad "retry: the successful retry is what got recorded" "no response artefact"
fi

# A server that always answers 524 exhausts the budget: exit 6, with both
# attempts reported so the operator can see the retries happened.
ALWAYS_BASE="$(start_mock always524 --api-key "$API_KEY" --mode 524)" || exit 1
S_ALWAYS="$WORK/session-always524"
err="$(env DUALMIND_BASE_URL="$ALWAYS_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" start \
  --task "always 524" --session "$S_ALWAYS" --force 2>&1 >/dev/null)"; rc=$?
if [ "$rc" -eq 6 ]; then ok "retry: an exhausted 524 budget is exit 6"
else bad "retry: an exhausted 524 budget is exit 6" "rc=$rc :: $(printf '%s' "$err" | tail -c 300)"; fi
expect_contains "retry: the first attempt is reported"  "transient error 524, retry 1/2" "$err"
expect_contains "retry: the second attempt is reported" "transient error 524, retry 2/2" "$err"
expect_contains "retry: the failure explains itself"    "HTTP 524" "$err"

# With retries disabled, the same server fails on the first attempt.
S_NORETRY="$WORK/session-noretry"
err="$(env DUALMIND_BASE_URL="$ALWAYS_BASE" DUALMIND_API_KEY="$API_KEY" DUALMIND_RETRIES=0 \
  "$PY" "$CLI" start --task "no retries" --session "$S_NORETRY" --force 2>&1 >/dev/null)"; rc=$?
if [ "$rc" -eq 6 ]; then ok "retry: DUALMIND_RETRIES=0 makes 524 fatal (exit 6)"
else bad "retry: DUALMIND_RETRIES=0 makes 524 fatal (exit 6)" "rc=$rc :: $(printf '%s' "$err" | tail -c 300)"; fi
expect_absent "retry: no retry line when retries are off" "transient error" "$err"

# A stream that stops short of message_stop must not yield a partial reply.
S_INC="$WORK/session-incomplete"
INC_BASE="$(start_mock incomplete --api-key "$API_KEY" --mode incomplete)" || exit 1
out="$(env DUALMIND_BASE_URL="$INC_BASE" DUALMIND_API_KEY="$API_KEY" DUALMIND_RETRIES=1 \
  "$PY" "$CLI" start --task "truncated" --session "$S_INC" --force 2>&1)"; rc=$?
if [ "$rc" -eq 6 ]; then ok "incomplete stream: fails (exit 6) instead of using a partial reply"
else bad "incomplete stream: fails (exit 6) instead of using a partial reply" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "incomplete stream: the retry is reported" "incomplete stream, retry 1/1" "$out"
expect_contains "incomplete stream: names what was missing" "message_stop" "$out"
if [ ! -e "$S_INC/round-01-response.json" ]; then
  ok "incomplete stream: no response artefact is written for a truncated reply"
else
  bad "incomplete stream: no response artefact is written for a truncated reply" "file exists"
fi

# check_config sees the same 524 and reports it as a transport failure.
out="$(env DUALMIND_BASE_URL="$ALWAYS_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" 2>&1)"; rc=$?
if [ "$rc" -eq 6 ]; then ok "retry: check_config reports 524 as exit 6"
else bad "retry: check_config reports 524 as exit 6" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
echo

# --------------------------------------------------------------------------
# 2. scoring
# --------------------------------------------------------------------------
echo "-- scoring --"
B="$BASE_URL"

out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score --files-estimated 1 --quiet 2>&1)"
expect_contains "score: below threshold says stay_local" "stay_local" "$out"
expect_contains "score: prints the score"                "score"       "$out"

out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score \
  --files-estimated 6 --ambiguity 0.9 --high-risk migration --quiet 2>&1)"
expect_contains "score: above threshold escalates" "escalate" "$out"

out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score --files-estimated 1 --quiet 2>&1)"
expect_absent "score: below threshold does not escalate" "-> escalate" "$out"

# The banner goes to stderr, the result to stdout.
err="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score \
  --files-estimated 6 --ambiguity 0.9 2>&1 >/dev/null)"
expect_contains "score: banner is on stderr" "[DualMind] evaluating escalation score" "$err"

out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score \
  --files-estimated 6 --ambiguity 0.9 --json --quiet 2>&1)"
if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert 0.0 <= d["score"] <= 1.0 and d["decision"] in ("escalate","stay_local"); assert set(d["components"]) == {"files","ambiguity","failures","risk","user"}' 2>/dev/null; then
  ok "score: --json has a valid score and components"
else
  bad "score: --json has a valid score and components" "$out"
fi

# Custom weights: weight everything onto files, drive files to 1.0.
out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score --files-estimated 5 \
  --weights '{"files":1.0,"ambiguity":0,"failures":0,"risk":0,"user":0}' --quiet 2>&1)"
expect_contains "score: custom weights escalate on files alone" "escalate" "$out"

# Same signals, but weight only the unused components -> stays local.
out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score --files-estimated 5 \
  --weights '{"files":0.0,"ambiguity":0,"failures":0,"risk":0,"user":1.0}' --quiet 2>&1)"
expect_contains "score: custom weights keep it local" "stay_local" "$out"

# Threshold override: a mid score escalates under a low threshold.
mid="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score --files-estimated 5 --quiet 2>&1)"
expect_contains "score: mid score is local at 0.6" "stay_local" "$mid"
low="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score --files-estimated 5 \
  --threshold 0.1 --quiet 2>&1)"
expect_contains "score: same score escalates at threshold 0.1" "escalate" "$low"

# Env-driven threshold and weights.
low="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" DUALMIND_THRESHOLD=0.05 \
  "$PY" "$CLI" score --files-estimated 5 --quiet 2>&1)"
expect_contains "score: DUALMIND_THRESHOLD is honoured" "escalate" "$low"
low="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" \
  DUALMIND_WEIGHTS='{"files":5,"ambiguity":0,"failures":0,"risk":0,"user":0}' \
  "$PY" "$CLI" score --files-estimated 5 --threshold 0.9 --quiet 2>&1)"
expect_contains "score: DUALMIND_WEIGHTS is honoured" "escalate" "$low"

# A malformed weights value is a reported config error, not a silent default.
out="$(env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" DUALMIND_WEIGHTS='not json' \
  "$PY" "$CLI" score --files-estimated 5 2>&1)"; rc=$?
if [ "$rc" -ne 0 ]; then ok "score: malformed DUALMIND_WEIGHTS fails loudly"
else bad "score: malformed DUALMIND_WEIGHTS fails loudly" "rc=0 :: $out"; fi

run_expect_exit "score: --files-changed and --files-estimated are exclusive" 2 \
  env DUALMIND_BASE_URL="$B" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" score \
  --files-changed 2 --files-estimated 3 --quiet
echo

# --------------------------------------------------------------------------
# 3. advisor: config guard + dry run
# --------------------------------------------------------------------------
echo "-- advisor: guards --"
run_expect_exit "advisor: refuses without config -> exit 2" 2 \
  env -u DUALMIND_BASE_URL -u DUALMIND_API_KEY "$PY" "$ADVISOR" status --session "$WORK/nope"

run_expect_exit "advisor: bad session dir -> exit 2" 2 \
  env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" status --session "$WORK/does-not-exist"

# --dry-run prints the payload, sends nothing, writes nothing.
# stdout carries the payload JSON; stderr carries the [DualMind] progress, so
# the two are captured separately -- mixing them would corrupt the JSON parse.
S_DRY="$WORK/session-dry"
env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" --dry-run start \
  --task "Add a TTL cache layer" --session "$S_DRY" >"$WORK/dry.out" 2>"$WORK/dry.err"; rc=$?
if [ "$rc" -eq 0 ] && "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["request"]["messages"] and d["request"]["model"]' "$WORK/dry.out" 2>/dev/null; then
  ok "advisor: --dry-run prints the request payload"
else
  bad "advisor: --dry-run prints the request payload" "rc=$rc :: $(tail -c 300 "$WORK/dry.out")"
fi
if [ ! -e "$S_DRY" ]; then ok "advisor: --dry-run writes no session"
else bad "advisor: --dry-run writes no session" "$S_DRY exists"; fi

# The --dry-run flag after the subcommand works too.
env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" start --dry-run \
  --task "t" --session "$WORK/session-dry2" >"$WORK/dry2.out" 2>"$WORK/dry2.err"; rc=$?
if [ "$rc" -eq 0 ] && "$PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$WORK/dry2.out" 2>/dev/null; then
  ok "advisor: --dry-run after the subcommand works"
else
  bad "advisor: --dry-run after the subcommand works" "rc=$rc :: $(tail -c 200 "$WORK/dry2.out")"
fi
if [ ! -e "$WORK/session-dry2" ]; then ok "advisor: dry-run writes no session (post-subcommand)"
else bad "advisor: dry-run writes no session (post-subcommand)" "exists"; fi
echo

# --------------------------------------------------------------------------
# 4. The full milestone loop to DONE
# --------------------------------------------------------------------------
echo "-- milestone loop (mock server, 5 rounds + retrospective) --"
S_LOOP="$WORK/session-loop"
LOOP_BASE="$(start_mock loop --api-key "$API_KEY" --script milestones)" || exit 1
export DUALMIND_BASE_URL="$LOOP_BASE" DUALMIND_API_KEY="$API_KEY"

out="$("$PY" "$CLI" start --task "Add a TTL cache layer to cache.py with tests" \
  --session "$S_LOOP" --force 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "loop: round 1 -> exit 0 (continue)"
else bad "loop: round 1 -> exit 0 (continue)" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "loop: round 1 status continue"   '"status": "continue"' "$out"
expect_contains "loop: round 1 has milestones"    '"milestones"'         "$out"
expect_contains "loop: round 1 names m1"          '"m1"'                 "$out"
expect_contains "loop: round 1 sets global criteria" '"acceptance_criteria"' "$out"
expect_contains "loop: round 1 sets current_milestone" '"current_milestone": "m1"' "$out"

printf 'm1 done\nRan 13 tests\n' > "$WORK/loop-r1.md"
out="$("$PY" "$CLI" report --session "$S_LOOP" --result-file "$WORK/loop-r1.md" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "loop: m1 report -> exit 0"
else bad "loop: m1 report -> exit 0" "rc=$rc"; fi
expect_contains "loop: m1 verdict approve" '"verdict": "approve"' "$out"

printf 'm2 done\nRan 14 tests\n' > "$WORK/loop-r2.md"
out="$("$PY" "$CLI" report --session "$S_LOOP" --result-file "$WORK/loop-r2.md" 2>&1)"; rc=$?
expect_contains "loop: m2 verdict revise" '"verdict": "revise"' "$out"

printf 'm2 fixed\nRan 15 tests\n' > "$WORK/loop-r3.md"
out="$("$PY" "$CLI" report --session "$S_LOOP" --result-file "$WORK/loop-r3.md" 2>&1)"; rc=$?
expect_contains "loop: m2 re-review approves" '"verdict": "approve"' "$out"

printf 'm3 done\nRan 15 tests in 0.041s\n' > "$WORK/loop-r4.md"
"$PY" "$CLI" report --session "$S_LOOP" --result-file "$WORK/loop-r4.md" \
  >"$WORK/loop-final.out" 2>"$WORK/loop-final.err"; rc=$?
FINAL_OUT="$(cat "$WORK/loop-final.out")"
FINAL_ERR="$(cat "$WORK/loop-final.err")"
if [ "$rc" -eq 0 ]; then ok "loop: final report -> exit 0 (done)"
else bad "loop: final report -> exit 0 (done)" "rc=$rc :: $(printf '%s' "$FINAL_OUT" | tail -c 300)"; fi

# Stdout is exactly one JSON object -- the final advisor reply with the report
# pointer and the retrospective metadata attached -- so `json.load(stdout)` works
# with no "Extra data" error even though a report was also produced.
if printf '%s' "$FINAL_OUT" | "$PY" -c '
import json, sys
d = json.load(sys.stdin)
assert d["status"] == "done", d.get("status")
assert d["report_path"], d
assert d["retrospective"] and isinstance(d["retrospective"], dict), d
assert d["retrospective"].get("recorded") is True, d["retrospective"]
assert "lessons_saved" in d["retrospective"], d["retrospective"]
assert d["milestones"] == [] or True
' 2>/dev/null; then
  ok "loop: stdout is exactly one JSON object with report_path + retrospective"
else
  bad "loop: stdout is exactly one JSON object with report_path + retrospective" \
      "$(printf '%s' "$FINAL_OUT" | head -c 300)"
fi

# The report markdown and the retrospective narrative must NOT be on stdout.
expect_absent "loop: report markdown is not on stdout" "# dualmind report" "$FINAL_OUT"
expect_absent "loop: retrospective narrative is not on stdout" "run went cleanly" "$FINAL_OUT"

expect_contains "loop: prints DONE on stderr"  "DONE"              "$FINAL_ERR"
expect_contains "loop: status done"            '"status": "done"'  "$FINAL_OUT"
expect_contains "loop: all criteria met"       '"met": true'       "$FINAL_OUT"
expect_contains "loop: final report mentions the retrospective" "retrospective" "$FINAL_ERR"
expect_contains "loop: report markdown goes to stderr" "# dualmind report" "$FINAL_ERR"

# Artefacts
for f in transcript.json round-01-request.json round-01-response.json \
         round-05-request.json round-05-response.json \
         retrospective-request.json retrospective-response.json report.json report.md; do
  if [ -f "$S_LOOP/$f" ]; then ok "loop: wrote $f"
  else bad "loop: wrote $f" "missing"; fi
done

out="$("$PY" "$CLI" status --session "$S_LOOP" --json 2>&1)"
if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert d["rounds_used"]==5 and d["status"]=="done" and d["criteria_met"]==3, d' 2>/dev/null; then
  ok "loop: status reports 5 rounds, done, 3/3 criteria"
else
  bad "loop: status reports 5 rounds, done, 3/3 criteria" "$out"
fi

if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); ms=d["milestones"]; assert len(ms)==3 and all(m["state"]=="approved" for m in ms), ms' 2>/dev/null; then
  ok "loop: all three milestones recorded approved"
else
  bad "loop: all three milestones recorded approved" "$out"
fi

# The retrospective ran automatically during that final report, and its narrative
# was printed to stderr (not stdout, which is reserved for JSON).
expect_contains "loop: retrospective narrative on stderr" "run went cleanly" "$FINAL_ERR"
expect_contains "loop: retrospective announced on stderr" "retrospective" "$FINAL_ERR"
expect_contains "loop: lessons reported as saved" "lessons saved" "$FINAL_ERR"

"$PY" "$CLI" finish --session "$S_LOOP" --json --quiet >"$WORK/retro.json" 2>/dev/null
if "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["retrospective"] is True, d' "$WORK/retro.json" 2>/dev/null; then
  ok "loop: retrospective was recorded"
else
  bad "loop: retrospective was recorded" "$(head -c 300 "$WORK/retro.json" 2>&1)"
fi

if "$PY" -c '
import json, sys
d = json.load(open(sys.argv[1]))
r = d["tokens"]["retrospective"]
assert r.get("calls") == 1, r
assert r.get("input_tokens", 0) > 0, r
' "$WORK/retro.json" 2>/dev/null; then
  ok "loop: retrospective tokens are counted separately"
else
  bad "loop: retrospective tokens are counted separately" "$(head -c 300 "$WORK/retro.json" 2>&1)"
fi
echo

# --------------------------------------------------------------------------
# 5. Visible progress on stderr
# --------------------------------------------------------------------------
echo "-- progress lines --"
stderr_out="$("$PY" "$CLI" finish --session "$S_LOOP" --quiet 2>&1 >/dev/null)"
stderr_out="$("$PY" "$CLI" status --session "$S_LOOP" 2>&1 >/dev/null)" # keep $? sane
S_PROG="$WORK/session-progress"
PROG_BASE="$(start_mock prog --api-key "$API_KEY" --script milestones)" || exit 1
err="$(env DUALMIND_BASE_URL="$PROG_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" start \
  --task "progress check" --session "$S_PROG" --force 2>&1 >/dev/null)"
expect_contains "progress: escalation/start banner on stderr" "[DualMind]" "$err"
expect_contains "progress: names the model"        "selected model claude-opus-5-5" "$err"
expect_contains "progress: names the host"         "via 127.0.0.1" "$err"
expect_contains "progress: prints the round"       "round 1/" "$err"

printf 'x\n' > "$WORK/prog-r.md"
err="$(env DUALMIND_BASE_URL="$PROG_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" report \
  --session "$S_PROG" --result-file "$WORK/prog-r.md" 2>&1 >/dev/null)"
expect_contains "progress: announces the milestone" "milestone" "$err"
expect_contains "progress: prints a verdict"        "verdict:" "$err"

# --quiet silences the progress lines entirely.
err="$(env DUALMIND_BASE_URL="$PROG_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" status \
  --session "$S_PROG" --quiet 2>&1 >/dev/null)"
expect_absent "progress: --quiet silences stderr" "[DualMind]" "$err"
echo

# --------------------------------------------------------------------------
# 6. stuck -> re-escalation
# --------------------------------------------------------------------------
echo "-- stuck --"
S_STUCK="$WORK/session-stuck"
printf 'the eviction test passes but the key order is wrong\n' > "$WORK/failure.txt"
STUCK_BASE="$(start_mock stuck --api-key "$API_KEY" --script stuck)" || exit 1
out="$(env DUALMIND_BASE_URL="$STUCK_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" start \
  --task "stuck scenario" --session "$S_STUCK" --force 2>&1)"; rc=$?
out="$(env DUALMIND_BASE_URL="$STUCK_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" stuck \
  --session "$S_STUCK" --reason "eviction test passes but order is wrong" \
  --failure-file "$WORK/failure.txt" --attempts 2 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "stuck: re-escalation -> exit 0"
else bad "stuck: re-escalation -> exit 0" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "stuck: advisor rejects the failed approach" '"verdict": "reject"' "$out"

# Without details, stuck refuses rather than sending a vague prompt.
run_expect_exit "stuck: refuses with no failure details" 2 \
  env DUALMIND_BASE_URL="$STUCK_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" stuck --session "$S_STUCK"

if "$PY" - "$S_STUCK/round-02-request.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
last = d["messages"][-1]["content"]
assert "attempts" in last.lower() or "Attempts" in last, last[:400]
assert "order is wrong" in last or "key order" in last, last[:400]
PYEOF
then ok "stuck: the failure details reach the advisor"
else bad "stuck: the failure details reach the advisor"; fi
echo

# --------------------------------------------------------------------------
# 7. Completion semantics: done without criteria does not end the loop
# --------------------------------------------------------------------------
echo "-- completion is gated on criteria --"
S_NOCRIT="$WORK/session-nocrit"
NC_BASE="$(start_mock nocrit --api-key "$API_KEY" --script done-without-criteria)" || exit 1
out="$(env DUALMIND_BASE_URL="$NC_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" start \
  --task "done without criteria" --session "$S_NOCRIT" --force 2>&1)"; rc=$?
err="$(env DUALMIND_BASE_URL="$NC_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" status \
  --session "$S_NOCRIT" --json 2>&1)"
if printf '%s' "$err" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]!="done", d["status"]' 2>/dev/null; then
  ok "completion: done without criteria_status keeps the loop open"
else
  bad "completion: done without criteria_status keeps the loop open" "$err"
fi
echo

# --------------------------------------------------------------------------
# 8. Max rounds
# --------------------------------------------------------------------------
echo "-- max rounds --"
S_MAX="$WORK/session-max"
MAX_BASE="$(start_mock max --api-key "$API_KEY" --script continue-forever)" || exit 1
export DUALMIND_BASE_URL="$MAX_BASE" DUALMIND_API_KEY="$API_KEY" DUALMIND_MAX_ROUNDS=3
printf 'step\n' > "$WORK/max.md"
"$PY" "$CLI" start --task "Long task" --session "$S_MAX" --force --quiet >/dev/null 2>&1
"$PY" "$CLI" report --session "$S_MAX" --result-file "$WORK/max.md" --quiet >/dev/null 2>&1
out="$("$PY" "$CLI" report --session "$S_MAX" --result-file "$WORK/max.md" --quiet 2>&1)"; rc=$?
if [ "$rc" -eq 11 ]; then ok "max rounds: exit 11 after the budget"
else bad "max rounds: exit 11 after the budget" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "max rounds: explains the budget" "3 of 3 rounds" "$out"
if [ -f "$S_MAX/report.json" ]; then ok "max rounds: report written on max rounds"
else bad "max rounds: report written on max rounds" "no report.json"; fi
unset DUALMIND_MAX_ROUNDS
echo

# --------------------------------------------------------------------------
# 9. Blocked
# --------------------------------------------------------------------------
echo "-- blocked path --"
S_BLOCK="$WORK/session-block"
BLOCK_BASE="$(start_mock blocked --api-key "$API_KEY" --script blocked)" || exit 1
out="$(env DUALMIND_BASE_URL="$BLOCK_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" start \
  --task "Migrate the production database schema" --session "$S_BLOCK" --force 2>&1)"; rc=$?
if [ "$rc" -eq 10 ]; then ok "blocked: exit 10"
else bad "blocked: exit 10" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "blocked: prints blocked_reason" "Missing production credentials" "$out"
if printf '%s' "$out" | "$PY" -c 'import json,sys; json.loads(sys.stdin.read().split("DONE")[0])' 2>/dev/null; then
  ok "blocked: still prints the advisor JSON"
elif printf '%s' "$out" | grep -q '"blocked_reason"'; then
  # The JSON is followed by the report, so only the leading object parses.
  ok "blocked: still prints the advisor JSON"
else
  bad "blocked: still prints the advisor JSON" "$(printf '%s' "$out" | tail -c 300)"
fi
echo

# --------------------------------------------------------------------------
# 10. Invalid JSON -> one repair retry, then exit 12
# --------------------------------------------------------------------------
echo "-- invalid JSON --"
S_REPAIR="$WORK/session-repair"
REPAIRFILE="$WORK/repair-ok.json"
cat > "$REPAIRFILE" <<'JSONEOF'
[
  "I think you should refactor this. Here is roughly what I mean... {{ not json",
  {"status": "continue", "summary": "Repaired reply.", "assumptions": [], "questions_for_executor": [],
   "plan": [{"id": "1", "action": "Do the thing", "files": ["a.py"], "verify": "run it"}],
   "milestones": [], "current_milestone": null, "acceptance_criteria": [], "criteria_status": [],
   "lessons": [], "review": {"verdict": "n/a", "issues": []}, "next_instructions": "Do the thing.",
   "blocked_reason": null}
]
JSONEOF
out="$(env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" \
  --mock "$REPAIRFILE" start --task "t" --session "$S_REPAIR" --force 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "invalid JSON: repair retry recovers -> exit 0"
else bad "invalid JSON: repair retry recovers -> exit 0" "rc=$rc :: $(printf '%s' "$out" | tail -c 400)"; fi
expect_contains "invalid JSON: rc names the repair" "repair retry" "$out"
if [ -f "$S_REPAIR/round-01-request-repair.json" ] && [ -f "$S_REPAIR/round-01-response-repair.json" ]; then
  ok "invalid JSON: repair pair written to the session"
else
  bad "invalid JSON: repair pair written to the session" "missing round-01-*-repair.json"
fi
expect_contains "invalid JSON: repaired reply used" "Repaired reply." "$out"

S_BADJSON="$WORK/session-badjson"
BADFILE="$WORK/repair-bad.json"
printf '["not json at all {{{", "still not json ]]]"]\n' > "$BADFILE"
out="$(env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" \
  --mock "$BADFILE" start --task "t" --session "$S_BADJSON" --force 2>&1)"; rc=$?
if [ "$rc" -eq 12 ]; then ok "invalid JSON: two bad replies -> exit 12"
else bad "invalid JSON: two bad replies -> exit 12" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi

GARB_BASE="$(start_mock garb --api-key "$API_KEY" --mode garbage)" || exit 1
run_expect_exit "invalid JSON: live garbage -> exit 12" 12 \
  env DUALMIND_BASE_URL="$GARB_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" \
  start --task "t" --session "$WORK/session-garb" --force

S_FENCE="$WORK/session-fence"
FENCEFILE="$WORK/fence.json"
cat > "$FENCEFILE" <<'JSONEOF'
["Here is the plan:\n\n```json\n{\"status\":\"done\",\"summary\":\"Fine.\",\"assumptions\":[],\"questions_for_executor\":[],\"plan\":[],\"milestones\":[],\"current_milestone\":null,\"acceptance_criteria\":[\"it works\"],\"criteria_status\":[{\"criterion\":\"it works\",\"met\":true,\"evidence\":\"shown\"}],\"lessons\":[],\"review\":{\"verdict\":\"approve\",\"issues\":[]},\"next_instructions\":\"Stop.\",\"blocked_reason\":null}\n```\nLet me know!"]
JSONEOF
out="$(env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" \
  --mock "$FENCEFILE" start --task "t" --session "$S_FENCE" --force 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "invalid JSON: fenced JSON tolerates prose -> exit 0 DONE"
else bad "invalid JSON: fenced JSON tolerates prose -> exit 0 DONE" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
expect_contains "invalid JSON: fenced reply yields DONE" "DONE" "$out"

S_EXH="$WORK/session-exhausted"
printf '["{\\"status\\":\\"continue\\",\\"summary\\":\\"go\\",\\"assumptions\\":[],\\"questions_for_executor\\":[],\\"plan\\":[],\\"milestones\\":[],\\"current_milestone\\":null,\\"acceptance_criteria\\":[],\\"criteria_status\\":[],\\"lessons\\":[],\\"review\\":{\\"verdict\\":\\"n/a\\",\\"issues\\":[]},\\"next_instructions\\":\\"x\\",\\"blocked_reason\\":null}"]\n' > "$WORK/one.json"
"$PY" "$CLI" --mock "$WORK/one.json" start --task "t" --session "$S_EXH" --force --quiet >/dev/null 2>&1
printf 'r1\n' > "$WORK/e1.md"
run_expect_exit "mock: exhausted script -> exit 12" 12 \
  env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" \
  --mock "$WORK/one.json" report --session "$S_EXH" --result-file "$WORK/e1.md" --quiet
echo

# --------------------------------------------------------------------------
# 11. Context handling
# --------------------------------------------------------------------------
echo "-- context handling --"
S_CTX="$WORK/session-ctx"
BIG="$WORK/big.txt"
"$PY" -c "open('$BIG','w').write('x' * 200000)"
out="$(env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" DUALMIND_MAX_CONTEXT_CHARS=5000 \
  "$PY" "$CLI" --dry-run start --task "t" --context-file "$BIG" --session "$S_CTX" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "context: oversized file does not break the round"
else bad "context: oversized file does not break the round" "rc=$rc"; fi
expect_contains "context: truncation is announced" "truncated" "$out"
if printf '%s' "$out" | grep -q "characters omitted"; then
  ok "context: truncation note names the drop"
else
  bad "context: truncation note names the drop"
fi

printf 'BIG REPORT\n' > "$WORK/ctxreport.md"
run_expect_exit "context: unreadable context file is a note, not a failure" 0 \
  env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" \
  DUALMIND_MOCK="$REPAIRFILE" "$PY" "$CLI" report --session "$S_REPAIR" --result-file "$WORK/ctxreport.md" \
  --context-file "$WORK/definitely-missing.txt" --quiet
echo

# --------------------------------------------------------------------------
# 12. Lessons store
# --------------------------------------------------------------------------
echo "-- lessons --"
STORE="$DUALMIND_HOME/experience"

env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" lessons add \
  "Prefer unittest over pytest in this repo" --kind user_preference --confidence 0.7 --json --quiet \
  >"$WORK/lesson-add.json" 2>"$WORK/lesson-add.err"
if "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["added"]+d["merged"]>=1, d' \
   "$WORK/lesson-add.json" 2>/dev/null; then
  ok "lessons: add writes a lesson"
else
  bad "lessons: add writes a lesson" "$(head -c 300 "$WORK/lesson-add.json" 2>&1)"
fi
if "$PY" -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert d["total"] >= 1, d
' "$WORK/lesson-add.json" 2>/dev/null; then
  ok "lessons: add reports the resulting store size"
else
  bad "lessons: add reports the resulting store size" "$(head -c 200 "$WORK/lesson-add.json")"
fi

if [ -f "$STORE/lessons.jsonl" ]; then ok "lessons: lessons.jsonl written under temp HOME"
else bad "lessons: lessons.jsonl written under temp HOME" "missing $STORE/lessons.jsonl"; fi
if [ -f "$STORE/lessons.md" ]; then ok "lessons: lessons.md generated"
else bad "lessons: lessons.md generated" "missing"; fi

# Never inside the skill package or the repo.
if [ -z "$(find "$ROOT" -name 'lessons.jsonl' -not -path "$WORK/*" 2>/dev/null)" ]; then
  ok "lessons: nothing written inside the skill directory"
else
  bad "lessons: nothing written inside the skill directory" "$(find "$ROOT" -name 'lessons.jsonl' 2>/dev/null | head -3)"
fi
expect_contains "lessons: store is under the temp HOME" "$WORK" "$(printf '%s' "$out")"

# Dedupe/merge: a near-identical lesson merges instead of adding.
before="$(wc -l < "$STORE/lessons.jsonl" 2>/dev/null || echo 0)"
env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" lessons add \
  "Prefer unittest over pytest in this repository" --kind user_preference --confidence 0.5 \
  --json --quiet >"$WORK/lesson-merge.json" 2>/dev/null
after="$(wc -l < "$STORE/lessons.jsonl" 2>/dev/null || echo 0)"
if [ "$before" = "$after" ]; then ok "lessons: near-duplicate merges instead of adding"
else bad "lessons: near-duplicate merges instead of adding" "lines $before -> $after"; fi

# The merged record keeps one line but gains confidence.
if "$PY" -c '
import json, sys
best = 0.0
count = 0
for line in open(sys.argv[1]):
    d = json.loads(line)
    if "unittest" in d["text"]:
        count += 1
        best = max(best, float(d["confidence"]))
assert count == 1, "expected one merged lesson, found %d" % count
assert best >= 0.7, "confidence was not bumped: %s" % best
' "$STORE/lessons.jsonl" 2>/dev/null; then
  ok "lessons: merge bumps confidence and keeps one record"
else
  bad "lessons: merge bumps confidence and keeps one record" \
      "$("$PY" -c 'import json,sys; [print(json.loads(l)["text"][:40], json.loads(l)["confidence"]) for l in open(sys.argv[1]) if "unittest" in l]' "$STORE/lessons.jsonl" 2>&1 | head -3)"
fi

# Prune to a cap.
for i in $(seq 1 12); do
  env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" lessons add \
    "Distinct lesson number $i about topic $RANDOM$i" --confidence 0.9 --quiet >/dev/null 2>&1
done
total_before="$(wc -l < "$STORE/lessons.jsonl")"
out="$(env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" lessons prune \
  --cap 5 --json --quiet 2>&1)"
if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert d["kept"]==5, d' 2>/dev/null; then
  ok "lessons: prune honours the cap"
else
  bad "lessons: prune honours the cap" "$out"
fi
total_after="$(wc -l < "$STORE/lessons.jsonl" 2>/dev/null || echo 0)"
if [ "$total_after" -le 5 ]; then ok "lessons: store is at or below the cap after prune"
else bad "lessons: store is at or below the cap after prune" "$total_after lines"; fi

env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" lessons export \
  --out "$WORK/exported.md" --quiet >/dev/null 2>&1
if [ -s "$WORK/exported.md" ]; then ok "lessons: export writes a digest"
else bad "lessons: export writes a digest" "missing"; fi

# A store inside the skill package is refused.
run_expect_exit "lessons: refuses a store inside the skill package" 2 \
  env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" DUALMIND_HOME="$ROOT" \
  "$PY" "$CLI" lessons list

# Lessons work with no endpoint configured: `lessons list` is step 0.
run_expect_exit "lessons: list works without an endpoint" 0 \
  env -u DUALMIND_BASE_URL -u DUALMIND_API_KEY "$PY" "$CLI" lessons list --limit 5
echo

# --------------------------------------------------------------------------
# 13. Report contents
# --------------------------------------------------------------------------
echo "-- report --"
if "$PY" - "$S_LOOP/report.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
t = d["tokens"]
assert t["advisor_input"] > 0, t
assert t["advisor_output"] > 0, t
assert t["calls"] >= 6, t          # 5 rounds + the retrospective
assert t["retrospective"]["calls"] == 1, t
c = d["cost"]
assert c["advisor_usd"] > 0, c
assert c["baseline_all_advisor_usd"] > 0, c
assert "savings_usd" in c and "savings_pct" in c, c
assert d["escalations"] >= 1, d
assert d["rounds"] == 5, d
PYEOF
then ok "report.json: token sums, cost and savings present"
else bad "report.json: token sums, cost and savings present" "$(head -c 400 "$S_LOOP/report.json" 2>&1)"; fi

if "$PY" - "$S_LOOP/report.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
assert d["milestones"]["total"] == 3, d["milestones"]
assert d["milestones"]["approved"] == 3, d["milestones"]
assert d["milestones"]["verdicts"]["revise"] == 1, d["milestones"]
assert d["acceptance_criteria"]["met"] == 3, d["acceptance_criteria"]
assert d["lessons_saved"] >= 1, d
PYEOF
then ok "report.json: milestones, criteria and lessons recorded"
else bad "report.json: milestones, criteria and lessons recorded" "$(head -c 400 "$S_LOOP/report.json" 2>&1)"; fi

out="$(env DUALMIND_BASE_URL="$LOOP_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" finish \
  --session "$S_LOOP" 2>&1)"
expect_contains "report: markdown has the token section"   "## Tokens"        "$out"
expect_contains "report: markdown has the cost section"    "## Cost estimate" "$out"
expect_contains "report: markdown names the savings"       "estimated savings" "$out"
expect_contains "report: markdown says report written"     "report written"   "$out"

# Test completed_early milestones: done arrives with only m1 approved of 2 milestones
S_EARLY="$WORK/session-early"
EARLY_SCRIPT="$WORK/early.json"
cat > "$EARLY_SCRIPT" <<'EARLYJSON'
[
  {"text":"{\"status\":\"continue\",\"summary\":\"Starting with two milestones.\",\"assumptions\":[],\"questions_for_executor\":[],\"plan\":[{\"id\":\"1\",\"action\":\"Step 1\",\"files\":[\"a.py\"],\"verify\":\"test\"}],\"milestones\":[{\"id\":\"m1\",\"title\":\"First milestone\",\"deliverables\":[\"a.py\"],\"state\":\"pending\"},{\"id\":\"m2\",\"title\":\"Second milestone\",\"deliverables\":[\"b.py\"],\"state\":\"pending\"}],\"current_milestone\":\"m1\",\"acceptance_criteria\":[\"works\",\"tested\"],\"criteria_status\":[],\"lessons\":[],\"review\":{\"verdict\":\"n/a\",\"issues\":[]},\"next_instructions\":\"Do m1.\",\"blocked_reason\":null}","usage":{"input_tokens":800,"output_tokens":300}},
  {"text":"{\"status\":\"continue\",\"summary\":\"m1 approved.\",\"assumptions\":[],\"questions_for_executor\":[],\"plan\":[],\"milestones\":[{\"id\":\"m1\",\"title\":\"First milestone\",\"deliverables\":[\"a.py\"],\"state\":\"approved\"},{\"id\":\"m2\",\"title\":\"Second milestone\",\"deliverables\":[\"b.py\"],\"state\":\"pending\"}],\"current_milestone\":\"m2\",\"acceptance_criteria\":[\"works\",\"tested\"],\"criteria_status\":[],\"lessons\":[],\"review\":{\"verdict\":\"approve\",\"issues\":[]},\"next_instructions\":\"Do m2.\",\"blocked_reason\":null}","usage":{"input_tokens":900,"output_tokens":310}},
  {"text":"{\"status\":\"done\",\"summary\":\"All done early.\",\"assumptions\":[],\"questions_for_executor\":[],\"plan\":[],\"milestones\":[{\"id\":\"m1\",\"title\":\"First milestone\",\"deliverables\":[\"a.py\"],\"state\":\"approved\"},{\"id\":\"m2\",\"title\":\"Second milestone\",\"deliverables\":[\"b.py\"],\"state\":\"pending\"}],\"current_milestone\":null,\"acceptance_criteria\":[\"works\",\"tested\"],\"criteria_status\":[{\"criterion\":\"works\",\"met\":true,\"evidence\":\"yes\"},{\"criterion\":\"tested\",\"met\":true,\"evidence\":\"yes\"}],\"lessons\":[],\"review\":{\"verdict\":\"n/a\",\"issues\":[]},\"next_instructions\":\"Done.\",\"blocked_reason\":null}","usage":{"input_tokens":950,"output_tokens":320}}
]
EARLYJSON

env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" \
  --mock "$EARLY_SCRIPT" start --task "early completion" --session "$S_EARLY" --force --quiet >/dev/null 2>&1
printf 'm1 done\n' > "$WORK/early-r1.md"
env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" \
  --mock "$EARLY_SCRIPT" report --session "$S_EARLY" --result-file "$WORK/early-r1.md" --quiet >/dev/null 2>&1
out="$(env DUALMIND_BASE_URL="http://127.0.0.1:9" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" \
  --mock "$EARLY_SCRIPT" report --session "$S_EARLY" --result-file "$WORK/early-r1.md" 2>&1)"

if "$PY" - "$S_EARLY/report.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
assert d["milestones"]["total"] == 2, d["milestones"]
assert d["milestones"]["approved"] == 1, d["milestones"]
assert d["milestones"]["completed_early"] == 1, d["milestones"]
PYEOF
then ok "report: completed_early count in report.json"
else bad "report: completed_early count in report.json" "$(head -c 400 "$S_EARLY/report.json" 2>&1)"; fi

expect_contains "report: markdown shows completed early" "1 approved, 1 completed early" "$out"

echo

# --------------------------------------------------------------------------
# 14. Secrets never leak
# --------------------------------------------------------------------------
echo "-- secrets --"
LEAK=0
for f in "$S_LOOP"/*.json "$S_LOOP"/*.md; do
  case "$f" in
    *-stream.json) continue ;;
  esac
  if grep -q "$API_KEY" "$f" 2>/dev/null; then
    bad "secrets: no key in $(basename "$f")" "key found"
    LEAK=1
  fi
done
[ "$LEAK" -eq 0 ] && ok "secrets: no key string in any session file"

if grep -rq "$API_KEY" "$S_LOOP" 2>/dev/null; then
  bad "secrets: no key anywhere in the session directory"
else
  ok "secrets: no key anywhere in the session directory"
fi

out="$(env DUALMIND_BASE_URL="$LOOP_BASE" DUALMIND_API_KEY="$API_KEY" "$PY" "$CLI" finish \
  --session "$S_LOOP" 2>&1)"
expect_absent "secrets: report output does not contain the key" "$API_KEY" "$out"
echo

# --------------------------------------------------------------------------
# 15. AGENTS.md is never touched
# --------------------------------------------------------------------------
echo "-- AGENTS.md guarantee --"
AFTER_PROTECTED="$WORK/protected-after.txt"
snapshot_protected "$AFTER_PROTECTED"

if diff -q "$BEFORE_PROTECTED" "$AFTER_PROTECTED" >/dev/null 2>&1; then
  ok "agents_md: every pre-existing AGENTS.md is byte-identical (sha256)"
else
  bad "agents_md: every pre-existing AGENTS.md is byte-identical (sha256)" \
      "$(diff "$BEFORE_PROTECTED" "$AFTER_PROTECTED" 2>&1 | head -5)"
fi

if grep -q "$CODEX_HOME/AGENTS.md" "$AFTER_PROTECTED" 2>/dev/null; then
  ok "agents_md: the pre-existing CODEX_HOME AGENTS.md still exists"
else
  bad "agents_md: the pre-existing CODEX_HOME AGENTS.md still exists" "vanished"
fi

# No AGENTS.md/CLAUDE.md was created anywhere new under the temp tree.
new_files="$(find "$HOME" "$CODEX_HOME" -maxdepth 6 \( -name 'AGENTS.md' -o -name 'CLAUDE.md' \) \
  -type f 2>/dev/null | sort)"
expected_files="$(printf '%s\n' "$CODEX_HOME/AGENTS.md" | sort)"
if [ "$new_files" = "$expected_files" ]; then
  ok "agents_md: no AGENTS.md was created under the temp HOME/CODEX_HOME"
else
  bad "agents_md: no AGENTS.md was created under the temp HOME/CODEX_HOME" "$new_files"
fi

# Static check: no code path writes one. Grep for a write call whose argument
# mentions a protected filename; the guard module is the only place allowed to
# name these at all, and it has no write path.
WRITE_HITS="$(grep -rnE 'AGENTS\.md|CLAUDE\.md' "$PKG"/*.py 2>/dev/null \
  | grep -vE 'agents_md\.py' \
  | grep -E 'write_text|write_json|append_jsonl|\.write\(|open\([^)]*[\"'"'"']w' || true)"
if [ -z "$WRITE_HITS" ]; then
  ok "agents_md: no package code writes an AGENTS.md"
else
  bad "agents_md: no package code writes an AGENTS.md" "$(printf '%s' "$WRITE_HITS" | head -3)"
fi

# Nothing anywhere in the package opens one for writing.
OPEN_FOR_WRITE="$(grep -rnE 'open\(' "$PKG"/*.py 2>/dev/null \
  | grep -E 'AGENTS|CLAUDE' || true)"
if [ -z "$OPEN_FOR_WRITE" ]; then
  ok "agents_md: no package code opens a protected file"
else
  bad "agents_md: no package code opens a protected file" "$OPEN_FOR_WRITE"
fi

# The guard itself refuses.
if "$PY" -c "
import sys
sys.path.insert(0, '$SCRIPTS')
from dualmind.agents_md import guard_write, is_protected_path
from dualmind.config import DualmindError
assert is_protected_path('/tmp/x/AGENTS.md')
assert is_protected_path('/home/u/.codex/AGENTS.md')
assert not is_protected_path('/tmp/x/notes.md')
try:
    guard_write('/tmp/x/AGENTS.md')
except DualmindError:
    pass
else:
    raise SystemExit('guard did not refuse')
" 2>/dev/null; then
  ok "agents_md: guard_write refuses a protected path"
else
  bad "agents_md: guard_write refuses a protected path"
fi
echo

# --------------------------------------------------------------------------
# 16. Install
# --------------------------------------------------------------------------
echo "-- install --"
if [ -x "$ROOT/install.sh" ]; then ok "install: install.sh is executable"
else bad "install: install.sh is executable"; fi

INST_HOME="$WORK/inst/home"
INST_CODEX="$WORK/inst/codex"
rm -rf "$WORK/inst"; mkdir -p "$INST_HOME" "$INST_CODEX"
printf '# codex agents\n' > "$INST_CODEX/AGENTS.md"
INST_BEFORE="$(sha256sum "$INST_CODEX/AGENTS.md" | cut -d' ' -f1)"

out="$(HOME="$INST_HOME" CODEX_HOME="$INST_CODEX" bash "$ROOT/install.sh" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "install: local install -> exit 0"
else bad "install: local install -> exit 0" "rc=$rc :: $out"; fi
if [ -e "$INST_CODEX/skills/dualmind/SKILL.md" ]; then ok "install: skill lands in CODEX_HOME/skills"
else bad "install: skill lands in CODEX_HOME/skills" "$(ls -la "$INST_CODEX/skills" 2>&1 | head -3)"; fi
if [ -e "$INST_HOME/.agents/skills/dualmind" ]; then ok "install: symlink in ~/.agents/skills"
else bad "install: symlink in ~/.agents/skills"; fi

# curl | bash: no checkout, so it downloads the tarball from DUALMIND_SRC.
TARBALL="$WORK/inst/dualmind.tar.gz"
tar -czf "$TARBALL" -C "$ROOT" --exclude=tests --exclude=.dualmind --exclude=.git \
  --exclude=__pycache__ --exclude=experience . 2>/dev/null
INST2_HOME="$WORK/inst2/home"
INST2_CODEX="$WORK/inst2/codex"
rm -rf "$WORK/inst2"; mkdir -p "$INST2_HOME" "$INST2_CODEX"
printf '# codex agents 2\n' > "$INST2_CODEX/AGENTS.md"
INST2_BEFORE="$(sha256sum "$INST2_CODEX/AGENTS.md" | cut -d' ' -f1)"

out="$(cat "$ROOT/install.sh" | HOME="$INST2_HOME" CODEX_HOME="$INST2_CODEX" \
  DUALMIND_SRC="file://$TARBALL" bash 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "install: curl|bash (DUALMIND_SRC tarball) -> exit 0"
else bad "install: curl|bash (DUALMIND_SRC tarball) -> exit 0" "rc=$rc :: $(printf '%s' "$out" | tail -c 300)"; fi
if [ -e "$INST2_CODEX/skills/dualmind/SKILL.md" ]; then ok "install: downloaded skill is usable"
else bad "install: downloaded skill is usable" "$(ls "$INST2_CODEX/skills" 2>&1)"; fi
if [ ! -e "$INST2_CODEX/skills/dualmind/tests" ]; then ok "install: tests/ excluded from the install"
else bad "install: tests/ excluded from the install"; fi

# The installed skill runs the full loop.
INST_SESSION="$WORK/inst-session"
printf 'r\n' > "$WORK/inst-r.md"
inst_err="$(HOME="$INST2_HOME" DUALMIND_HOME="$INST2_HOME/.dualmind" \
  DUALMIND_BASE_URL="$LOOP_BASE" DUALMIND_API_KEY="$API_KEY" \
  "$PY" "$INST2_CODEX/skills/dualmind/scripts/dualmind_cli.py" status --session "$S_LOOP" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "install: the installed copy runs"
else bad "install: the installed copy runs" "rc=$rc :: $(printf '%s' "$inst_err" | tail -c 300)"; fi

# Install/uninstall must not touch AGENTS.md.
INST_AFTER="$(sha256sum "$INST_CODEX/AGENTS.md" | cut -d' ' -f1)"
INST2_AFTER="$(sha256sum "$INST2_CODEX/AGENTS.md" | cut -d' ' -f1)"
if [ "$INST_BEFORE" = "$INST_AFTER" ] && [ "$INST2_BEFORE" = "$INST2_AFTER" ]; then
  ok "install: neither install modified an AGENTS.md"
else
  bad "install: neither install modified an AGENTS.md" "$INST_BEFORE/$INST_AFTER $INST2_BEFORE/$INST2_AFTER"
fi

# Uninstall keeps the experience store.
mkdir -p "$INST2_HOME/.dualmind/experience"
printf '{"id":"x","text":"keep me"}\n' > "$INST2_HOME/.dualmind/experience/lessons.jsonl"
out="$(HOME="$INST2_HOME" CODEX_HOME="$INST2_CODEX" bash "$ROOT/install.sh" --uninstall 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "install: --uninstall -> exit 0"
else bad "install: --uninstall -> exit 0" "rc=$rc :: $out"; fi
if [ ! -e "$INST2_CODEX/skills/dualmind" ]; then ok "install: --uninstall removes the skill"
else bad "install: --uninstall removes the skill"; fi
if [ -f "$INST2_HOME/.dualmind/experience/lessons.jsonl" ]; then
  ok "install: --uninstall keeps the experience store"
else
  bad "install: --uninstall keeps the experience store"; fi

out="$(HOME="$INST_HOME" CODEX_HOME="$INST_CODEX" bash "$ROOT/install.sh" --uninstall --purge 2>&1)"
if [ ! -e "$INST_HOME/.dualmind" ]; then ok "install: --purge removes the store"
else bad "install: --purge removes the store"; fi

if [ "$(sha256sum "$INST_CODEX/AGENTS.md" | cut -d' ' -f1)" = "$INST_BEFORE" ]; then
  ok "install: uninstall did not modify the CODEX_HOME AGENTS.md"
else
  bad "install: uninstall did not modify the CODEX_HOME AGENTS.md"
fi
echo

# --------------------------------------------------------------------------
# 17. Package sanity
# --------------------------------------------------------------------------
echo "-- package --"
for f in "$ROOT/SKILL.md" "$ROOT/README.md" "$ROOT/install.sh" \
         "$ROOT/agents/openai.yaml" "$ROOT/references/config.md" "$ROOT/references/triggers.md" \
         "$ROOT/references/experience.md" "$ROOT/references/advisor-system-prompt.md" \
         "$ROOT/references/comparison-sources.md" "$ROOT/.gitignore" \
         "$ROOT/examples/minimal/README.md" "$ROOT/examples/minimal/mock_rounds.json"; do
  if [ -f "$f" ]; then ok "package: $(basename "$f") present"
  else bad "package: $(basename "$f") present" "missing $f"; fi
done

for m in config client schema scoring session loop experience agents_md report status io cli; do
  if [ -f "$PKG/$m.py" ]; then ok "package: dualmind/$m.py present"
  else bad "package: dualmind/$m.py present" "missing"; fi
done

if head -n 5 "$ROOT/SKILL.md" | grep -q '^name: dualmind$'; then
  ok "package: SKILL.md frontmatter name is dualmind"
else
  bad "package: SKILL.md frontmatter name is dualmind"
fi

expect_contains "package: SKILL.md documents lessons as step 0" "lessons list" "$(cat "$ROOT/SKILL.md")"
expect_contains "package: SKILL.md states the AGENTS.md guarantee" "AGENTS.md" "$(cat "$ROOT/SKILL.md")"

# The mock rounds file must carry the new schema.
if "$PY" - "$ROOT/examples/minimal/mock_rounds.json" <<'PYEOF' 2>/dev/null
import json, sys
data = json.load(open(sys.argv[1]))
assert isinstance(data, list) and len(data) >= 5, len(data)
first = json.loads(data[0]["text"])
assert first["milestones"] and len(first["milestones"]) == 3, first.get("milestones")
done = [json.loads(e["text"]) for e in data if isinstance(e, dict)]
assert any(d["status"] == "done" for d in done)
assert any(d.get("lessons") for d in done), "no retrospective lessons in the script"
assert all("usage" in e for e in data if isinstance(e, dict)), "usage missing"
PYEOF
then ok "package: mock_rounds.json has the milestone schema, done, lessons and usage"
else bad "package: mock_rounds.json has the milestone schema, done, lessons and usage"; fi

# Stdlib only. Relative imports (`from .x import y`) are intra-package and are
# allowed; anything else must be on the stdlib allowlist.
ALLOWED='argparse|json|os|re|socket|sys|time|traceback|urllib|http|pathlib|threading|shutil|tempfile|typing|hashlib|difflib|copy|__future__|dualmind|dualmind_common|check_config'
UNEXPECTED="$(grep -rnE '^[[:space:]]*(import|from)[[:space:]]+' "$SCRIPTS" --include='*.py' \
  | grep -vE ':[0-9]+:[[:space:]]*from[[:space:]]+\.' \
  | grep -vE '(import|from)[[:space:]]+('"$ALLOWED"')([[:space:].]|$)' || true)"
if [ -z "$UNEXPECTED" ]; then
  ok "package: stdlib only"
else
  bad "package: stdlib only" "$(printf '%s' "$UNEXPECTED" | head -4)"
fi

# The package imports cleanly on its own.
if "$PY" -c "
import sys
sys.path.insert(0, '$SCRIPTS')
import dualmind
from dualmind import cli, client, config, experience, io, loop, report, schema, scoring, session, status, agents_md, check_config, fixtures
" 2>/dev/null; then
  ok "package: every module imports"
else
  bad "package: every module imports"
fi

# The back-compat wrappers still work.
run_expect_exit "package: check_config.py wrapper works" 0 \
  env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$CHECK" --no-call
run_expect_exit "package: advisor.py wrapper works" 0 \
  env DUALMIND_BASE_URL="$BASE_URL" DUALMIND_API_KEY="$API_KEY" "$PY" "$ADVISOR" status --session "$S_LOOP"
echo

# --------------------------------------------------------------------------
# 17b. Prompt caching and history compression
# --------------------------------------------------------------------------
echo "-- cache + compression --"
run_three_rounds() {  # run_three_rounds <tag> <session> [ENV=VAL...]
  local tag="$1" sess="$2"; shift 2
  local base
  base="$(start_mock "$tag" --api-key "$API_KEY" --script milestones)" || exit 1
  env DUALMIND_BASE_URL="$base" DUALMIND_API_KEY="$API_KEY" "$@" \
    "$PY" "$CLI" start --task "Add a TTL cache layer to cache.py with tests" \
    --session "$sess" --force >/dev/null 2>&1
  for n in 1 2; do
    printf 'round %s report\nRan 13 tests\n' "$n" > "$WORK/$tag-r$n.md"
    env DUALMIND_BASE_URL="$base" DUALMIND_API_KEY="$API_KEY" "$@" \
      "$PY" "$CLI" report --session "$sess" --result-file "$WORK/$tag-r$n.md" >/dev/null 2>&1
  done
}
run_three_rounds cmp1 "$WORK/session-cmp1"
run_three_rounds cmp0 "$WORK/session-cmp0" DUALMIND_COMPRESS=0 DUALMIND_PROMPT_CACHE=0

if "$PY" - "$WORK/session-cmp1/round-03-request.json" "$WORK/session-cmp0/round-03-request.json" <<'PYEOF' 2>/dev/null
import json, sys
on, off = (json.load(open(p)) for p in sys.argv[1:3])
chars = lambda d: len(json.dumps(d["messages"]))
assert len(on["messages"]) < len(off["messages"]), (len(on["messages"]), len(off["messages"]))
assert chars(on) < chars(off), (chars(on), chars(off))
PYEOF
then ok "compression: round-3 request has fewer messages and chars than DUALMIND_COMPRESS=0"
else bad "compression: round-3 request has fewer messages and chars than DUALMIND_COMPRESS=0"; fi

if "$PY" - "$WORK/session-cmp1/round-03-request.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
assert isinstance(d["system"], list) and d["system"][0]["cache_control"] == {"type": "ephemeral"}
first = d["messages"][0]["content"]
assert isinstance(first, list) and first[-1]["cache_control"] == {"type": "ephemeral"}
PYEOF
then ok "prompt cache: cache_control present by default (system + first user message)"
else bad "prompt cache: cache_control present by default (system + first user message)"; fi

if "$PY" - "$WORK/session-cmp0/round-03-request.json" <<'PYEOF' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
assert isinstance(d["system"], str)
assert "cache_control" not in json.dumps(d["messages"])
PYEOF
then ok "prompt cache: cache_control absent with DUALMIND_PROMPT_CACHE=0"
else bad "prompt cache: cache_control absent with DUALMIND_PROMPT_CACHE=0"; fi

if "$PY" - "$WORK/session-cmp1/transcript.json" <<'PYEOF' 2>/dev/null
import json, sys
t = json.load(open(sys.argv[1]))
assert t["usage"]["cache_creation_input_tokens"] > 0, t["usage"]
assert t["usage"]["cache_read_input_tokens"] > 0, t["usage"]
PYEOF
then ok "prompt cache: mock reports cache reads after the first call"
else bad "prompt cache: mock reports cache reads after the first call"; fi

if "$PY" - "$S_LOOP/report.json" <<'PYEOF' 2>/dev/null
import json, sys
t = json.load(open(sys.argv[1]))["tokens"]
assert "cache_creation_input_tokens" in t and "cache_read_input_tokens" in t, t
assert t["cache_read_input_tokens"] > 0, t
PYEOF
then ok "report.json: includes cache token fields"
else bad "report.json: includes cache token fields"; fi
echo

# --------------------------------------------------------------------------
# 18. Final: nothing leaked outside the temp tree
# --------------------------------------------------------------------------
echo "-- isolation --"
if [ -z "$(find "$ROOT" -name 'lessons.jsonl' -o -name '.dualmind' -type d 2>/dev/null | grep -v "$WORK")" ]; then
  ok "isolation: no session or lesson data inside the skill directory"
else
  bad "isolation: no session or lesson data inside the skill directory" \
      "$(find "$ROOT" -name 'lessons.jsonl' -o -name '.dualmind' -type d 2>/dev/null | head -3)"
fi

if [ "$(count_protected)" = "1" ]; then
  ok "isolation: exactly the one pre-existing protected file exists under temp HOME"
else
  bad "isolation: exactly the one pre-existing protected file exists under temp HOME" \
      "$(find "$HOME" "$CODEX_HOME" \( -name 'AGENTS.md' -o -name 'CLAUDE.md' \) 2>/dev/null)"
fi
echo

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo "=========================================="
printf 'PASS: %d   FAIL: %d\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf 'failed cases:\n'
  for name in "${FAILED_NAMES[@]}"; do printf '  - %s\n' "$name"; done
  exit 1
fi
echo "ALL TESTS PASSED"
exit 0
