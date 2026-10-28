"""Inject workflow only for a chat that explicitly opted in. Off is silent."""
import json
from pathlib import Path
import sys


def main():
    event = sys.argv[1] if len(sys.argv) == 2 else ""
    if event not in ("SessionStart", "UserPromptSubmit"):
        return
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from bigbrain.activation import chat_id, enabled
    from bigbrain.config import BigbrainError

    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
        identity = chat_id(payload.get("session_id"))
    except (ValueError, AttributeError, BigbrainError):
        return
    if not enabled(identity):
        return
    rules = (root / "references" / "collaboration.md").read_text(encoding="utf-8")
    context = "Bigbrain is explicitly enabled for this chat. Workflow: %s.\n\n%s" % (root / "SKILL.md", rules)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                             "additionalContext": context}}))


if __name__ == "__main__":
    main()
