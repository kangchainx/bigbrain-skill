"""Read-only, offline audit of explicitly selected Bigbrain session snapshots."""
import argparse
import json
import math
from pathlib import Path


def number(value, integer=False):
    return (type(value) in (int, float) and math.isfinite(value) and value >= 0
            and (not integer or type(value) is int))


def audit(paths):
    files, excluded, sessions = set(), [], []
    markers = ('transcript.json', 'claude-session.json', 'claude-journal.json')
    for raw in sorted({str(Path(p).expanduser().resolve()) for p in paths}):
        path = Path(raw)
        if not path.is_dir():
            excluded.append({"path": raw, "reason": "not_found_or_not_directory"})
        elif any((path / name).exists() for name in markers):
            files.add(path.resolve() / "transcript.json")
        else:
            children = {p.parent.resolve() for name in markers for p in path.glob("*/" + name)}
            files.update(p / "transcript.json" for p in children)
            if not children:
                excluded.append({"path": raw, "reason": "transcript_missing"})
    for path in sorted(files):
        row = {"path": str(path.parent), "issues": []}
        if not path.exists():
            row['issues'] = ['transcript_missing', 'native_operation_unsettled']
            row['cli_cost_usd'] = None
            sessions.append(row)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("expected object")
        except (OSError, ValueError) as exc:
            row["issues"].append("transcript_unreadable" if isinstance(exc, OSError)
                                 else "transcript_invalid_json")
            sessions.append(row)
            continue
        rounds = data.get("rounds", [])
        rounds = rounds if isinstance(rounds, list) else []
        if data.get("mock") or any(isinstance(r, dict) and
                isinstance(r.get("meta"), dict) and r["meta"].get("mode") == "mock"
                for r in rounds):
            excluded.append({"path": str(path.parent), "reason": "mock"})
            continue
        usage = data.get("usage")
        row["native_session_id"] = (data.get("claude_session") or {}).get("id")
        journal_path = path.parent / "claude-journal.json"
        unsettled = False
        if journal_path.exists():
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                unsettled = (journal["state"] != "applied" and
                             data.get("native_applied_operation") != journal["id"])
                row["native_journal_state"] = journal["state"]
            except (OSError, ValueError, KeyError, TypeError):
                unsettled = True
            if unsettled:
                row["issues"].append("native_operation_unsettled")
        if not isinstance(usage, dict):
            usage = {}
            row["issues"].append("usage_missing")
        row.update(backend=data.get("backend", "api"), status=data.get("status"),
                   rounds=len(rounds), model=data.get("model"), effort=data.get("effort"))
        for key in ("input_tokens", "output_tokens", "calls",
                    "cache_creation_input_tokens", "cache_read_input_tokens"):
            value = usage.get(key)
            row[key] = value if number(value, integer=True) else None
            if row[key] is None:
                row["issues"].append(key + "_not_recorded_or_invalid")
        row["calls_by_kind"] = {}
        kinds = usage.get("by_kind")
        if isinstance(kinds, dict):
            for kind, bucket in sorted(kinds.items()):
                value = bucket.get("calls") if isinstance(bucket, dict) else None
                row["calls_by_kind"][kind] = value if number(value, integer=True) else None
        else:
            row["issues"].append("calls_by_kind_not_recorded")
        if usage.get("usage_missing_calls"):
            row["issues"].append("usage_missing_calls")
        cost = usage.get("cli_cost_usd")
        row["cli_cost_usd_recorded"] = cost if number(cost) else None
        row["cli_cost_usd"] = None
        if row["backend"] != "claude-code":
            row["cli_cost_usd_recorded"] = None
            row["issues"].append("cli_cost_not_applicable_api_backend")
        elif unsettled or data.get("cost_incomplete") or usage.get("cli_cost_missing") or usage.get("usage_missing_calls"):
            row["issues"].append("cli_cost_incomplete")
        elif cost is None:
            row["issues"].append("cli_cost_missing")
        elif not number(cost):
            row["issues"].append("cli_cost_invalid")
        else:
            row["cli_cost_usd"] = cost
        feedback = data.get("user_feedback", [])
        row["feedback_count"] = len(feedback) if isinstance(feedback, list) else None
        criteria = data.get("criteria_status", [])
        criteria = criteria if isinstance(criteria, list) else []
        row["criteria"] = {"reported": len(criteria), "met": sum(
            isinstance(c, dict) and c.get("met") is True for c in criteria)}
        reviews = data.get("milestone_reviews", [])
        reviews = reviews if isinstance(reviews, list) else []
        row["revision_reviews"] = sum(isinstance(r, dict) and
            r.get("verdict") in ("revise", "reject") for r in reviews)
        sessions.append(row)
    totals = {"sessions": len(sessions), "cost_known_sessions": sum(
        r.get("cli_cost_usd") is not None for r in sessions)}
    totals["cost_unknown_sessions"] = len(sessions) - totals["cost_known_sessions"]
    totals["cli_cost_usd_recorded"] = round(sum(
        r.get("cli_cost_usd_recorded") or 0 for r in sessions), 8)
    scope_incomplete = any(r["reason"] != "mock" for r in excluded)
    totals["cli_cost_usd"] = (None if scope_incomplete or totals["cost_unknown_sessions"]
                             else totals["cli_cost_usd_recorded"])
    for key in ("input_tokens", "output_tokens", "calls", "feedback_count"):
        values = [r.get(key) for r in sessions]
        totals[key + "_recorded"] = sum(v for v in values if v is not None)
        totals[key] = (None if scope_incomplete or any(v is None for v in values)
                      or (key in ("input_tokens", "output_tokens", "calls") and any(
                          "usage_missing_calls" in r["issues"] or
                          "cli_cost_incomplete" in r["issues"] for r in sessions))
                      else totals[key + "_recorded"])
    totals["calls_by_kind_recorded"] = {}
    for row in sessions:
        for kind, count in row.get("calls_by_kind", {}).items():
            if count is not None:
                totals["calls_by_kind_recorded"][kind] = totals["calls_by_kind_recorded"].get(kind, 0) + count
    totals["done_sessions"] = sum(r.get("status") == "done" for r in sessions)
    return {"scope": "Selected sessions' lifetime snapshots, not weekly spend or billing. "
                     "CLI costs are reported estimates. Done is recorded status, not user acceptance.",
            "sessions": sessions, "excluded": sorted(excluded, key=lambda r: (r["path"], r["reason"])),
            "totals": totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Session directories or roots with direct session children")
    args = parser.parse_args()
    print(json.dumps(audit(args.paths), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
