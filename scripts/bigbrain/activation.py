"""Explicit, chat-scoped opt-in. No prompt interpretation or model calls."""
import hashlib
import json
import os
from pathlib import Path

from .config import BigbrainError, EXIT_CONFIG, bigbrain_home_dir


def chat_id(explicit=None):
    current = os.environ.get("CODEX_THREAD_ID")
    if explicit and current and explicit != current:
        raise BigbrainError("Chat ID does not match CODEX_THREAD_ID", EXIT_CONFIG)
    value = explicit or current
    if not isinstance(value, str) or not value.strip():
        raise BigbrainError("Chat ID unavailable; set CODEX_THREAD_ID or pass --chat-id", EXIT_CONFIG)
    return value


def state_path(identity):
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return bigbrain_home_dir() / "chat-activation" / (key + ".json")


def enabled(identity):
    if not identity:
        return False
    try:
        data = json.loads(state_path(identity).read_text(encoding="utf-8"))
        return isinstance(data, dict) and data.get("chat_id") == identity and data.get("enabled") is True
    except (OSError, ValueError):
        return False


def set_mode(identity, on):
    path = state_path(identity)
    # Atomic replace; concurrent changes in the same chat use last completed write.
    # Unique temp paths avoid collisions between local on/off commands.
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        json.dump({"chat_id": identity, "enabled": bool(on)}, stream)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def require_enabled():
    identity = os.environ.get("CODEX_THREAD_ID")
    if identity and not enabled(identity):
        raise BigbrainError("Bigbrain is off for this chat. Only after explicit user opt-in, run: "
                            "bigbrain_cli.py mode on. No advisor request was sent.", EXIT_CONFIG)
