#!/usr/bin/env bash
# Walk the full DualMind milestone loop using the scripted replies in
# mock_rounds.json -- no API key, no network, no real advisor.
#
# Safe to run from anywhere: everything happens under a temporary HOME.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CLI="$ROOT/scripts/dualmind_cli.py"
MOCK="$HERE/mock_rounds.json"

PY="${PYTHON:-python3}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/dualmind-example.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

export HOME="$WORK/home"
export CODEX_HOME="$WORK/codex"
export DUALMIND_HOME="$WORK/home/.dualmind"
export DUALMIND_MOCK="$MOCK"
# A closed port: with --mock, nothing is ever sent here, which is the point.
export DUALMIND_BASE_URL="http://127.0.0.1:9"
export DUALMIND_API_KEY="not-a-real-key"
mkdir -p "$HOME" "$CODEX_HOME"

SESSION="$WORK/session-cache"
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

step "0. lessons (first step on every trigger)"
"$PY" "$CLI" lessons list --limit 10

step "1. score the task"
"$PY" "$CLI" score --files-estimated 5 --ambiguity 0.7 --high-risk migration

step "2. round 1 -- escalate, get milestones and acceptance criteria"
"$PY" "$CLI" start \
  --task "Add a TTL cache layer to cache.py with tests. Acceptance: entries expire after
          their TTL; the cache is bounded by maxsize and the evicted key is asserted; the
          full test suite stays green." \
  --session "$SESSION" --force --quiet > "$WORK/r1.json" 2>"$WORK/r1.err" || true
sed -n '1,4p' "$WORK/r1.err"
"$PY" - "$WORK/r1.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
print("  status            :", d["status"])
print("  current_milestone :", d["current_milestone"])
print("  milestones        :", ", ".join(m["id"] for m in d["milestones"]))
print("  global criteria   :", len(d["acceptance_criteria"]))
PYEOF

report() { printf '%s\n' "$2" > "$WORK/$1.md"; }

step "3. report milestone m1 (expect approve)"
report m1 "## Steps completed
1.1 TTLCache added with an injectable clock.
1.2 Frozen-clock expiry test added.
## Verify
\$ python -m unittest discover -s tests
Ran 13 tests in 0.038s
OK"
"$PY" "$CLI" report --session "$SESSION" --result-file "$WORK/m1.md" --quiet >/dev/null 2>"$WORK/m1.err" || true
grep -E 'milestone|verdict|round' "$WORK/m1.err"

step "4. report milestone m2 (expect revise -- the evicted key is not asserted)"
report m2 "## Steps completed
2.1 LRU eviction at maxsize.
2.2 Test asserting the resulting length.
## Verify
\$ python -m unittest discover -s tests
Ran 14 tests in 0.041s
OK"
"$PY" "$CLI" report --session "$SESSION" --result-file "$WORK/m2.md" --quiet >/dev/null 2>"$WORK/m2.err" || true
grep -E 'milestone|verdict|round' "$WORK/m2.err"

step "5. fix what it named, report m2 again (expect approve)"
report m2b "## Steps completed
2.2 Corrected: the evicted key is asserted by name, plus a re-insert-moves-to-front case.
## Verify
\$ python -m unittest discover -s tests
Ran 15 tests in 0.043s
OK"
"$PY" "$CLI" report --session "$SESSION" --result-file "$WORK/m2b.md" --quiet >/dev/null 2>"$WORK/m2b.err" || true
grep -E 'milestone|verdict|round' "$WORK/m2b.err"

step "6. report milestone m3 (expect DONE, retrospective, report)"
report m3 "## Steps completed
3.1 Full suite run, no filters.
## Verify
\$ python -m unittest discover -s tests
Ran 15 tests in 0.041s
OK"
"$PY" "$CLI" report --session "$SESSION" --result-file "$WORK/m3.md" --quiet \
  > "$WORK/final.out" 2>"$WORK/final.err"
rc=$?
grep -E 'milestone|verdict|round|retrospective|lessons saved|report written|BLOCKED' "$WORK/final.err"
grep -q '^DONE$' "$WORK/final.out" && echo "  exit code: $rc -- DONE"

step "7. the report"
sed -n '/## Tokens/,/^## Learning/p' "$WORK/final.out"

step "8. lessons saved (user level, never in the repo)"
echo "store: $DUALMIND_HOME/experience"
"$PY" "$CLI" lessons list --limit 5
echo
echo "AGENTS.md files created or modified anywhere here:"
found="$(find "$HOME" "$CODEX_HOME" -name 'AGENTS.md' 2>/dev/null | wc -l)"
echo "  $found (expected: 0)"

step "9. session state"
"$PY" "$CLI" status --session "$SESSION" --quiet

step "done"
echo "session: $SESSION  (removed with the temp dir on exit)"
