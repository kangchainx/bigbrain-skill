#!/usr/bin/env bash
# A short, offline Bigbrain demo for the README recording (docs/demo.tape).
#
# Runs the real CLI against scripts/mock_server.py -- a local Anthropic-compatible
# server replaying a scripted advisor -- under a throwaway HOME. No API key, no
# network, nothing written outside the temp dir. The replies are scripted, so
# this shows the mechanics, not a real advisor review.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/scripts/bigbrain_cli.py"
PY="${PYTHON:-python3}"
PAUSE="${DEMO_PAUSE:-1.2}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/bigbrain-demo.XXXXXX")"
MOCK_PID=""
cleanup() { [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

export HOME="$WORK/home" CODEX_HOME="$WORK/codex" BIGBRAIN_HOME="$WORK/home/.bigbrain"
mkdir -p "$HOME" "$CODEX_HOME"

"$PY" "$ROOT/scripts/mock_server.py" --port 0 --port-file "$WORK/port" --quiet \
  --script milestones >/dev/null 2>&1 &
MOCK_PID=$!
for _ in $(seq 1 100); do [ -s "$WORK/port" ] && break; sleep 0.05; done
export BIGBRAIN_BASE_URL="http://127.0.0.1:$(cat "$WORK/port")"
export BIGBRAIN_API_KEY="test-key"

S="$WORK/session"
say()  { printf '\n\033[1;36m# %s\033[0m\n' "$*"; sleep "$PAUSE"; }
bb()   { "$PY" "$CLI" "$@"; }
note() { printf '%s\n' "$2" > "$WORK/$1.md"; }

say "Score the task: escalate only above the threshold"
bb score --files-estimated 5 --ambiguity 0.7 --high-risk migration 2>&1 | head -1

say "Escalate: the advisor returns milestones + acceptance criteria"
bb start --task "Add a TTL cache layer to cache.py with tests" --session "$S" >/dev/null

say "Codex works each milestone and reports it for review"
note m1 "1.1 TTLCache with an injectable clock. \$ python -m unittest -> Ran 13 tests OK"
bb report --session "$S" --result-file "$WORK/m1.md" >/dev/null
note m2 "2.1 LRU eviction at maxsize; test asserts the length. Ran 14 tests OK"
bb report --session "$S" --result-file "$WORK/m2.md" >/dev/null
sleep "$PAUSE"
note m2b "2.2 Test now asserts the evicted key by name. Ran 15 tests OK"
bb report --session "$S" --result-file "$WORK/m2b.md" >/dev/null

say "Last milestone: DONE only when every criterion is met"
note m3 "3.1 Full suite, no filters. Ran 15 tests OK"
# On DONE the full report is printed too; keep the status lines, summarise below.
bb report --session "$S" --result-file "$WORK/m3.md" 2>&1 >/dev/null \
  | grep '^\[Bigbrain\]' | grep -v 'report written'

say "Usage and savings report (report.md, abridged)"
grep -E '^- (rounds used|met|advisor total|executor work|advisor spend|actual total|everything to|estimated savings)' \
  "$S/report.md" | sed -e 's/\*\*//g' -e 's/ -- from .*//' -e 's/^- met:/- acceptance criteria met:/'
sleep "$PAUSE"
printf '\n\033[2m(scripted mock advisor via scripts/mock_server.py -- no real API call)\033[0m\n'
sleep "$PAUSE"
