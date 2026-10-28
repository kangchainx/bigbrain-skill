"""Task-bound CLI sessions and durable, locally recoverable turn receipts.

The command lock covers transcript reads through commit. A receipt is saved as
soon as a terminal CLI event arrives. Unknown outcomes are never retried here.
"""
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import uuid

from .config import BigbrainError, EXIT_CONFIG

STATE = "claude-session.json"
JOURNAL = "claude-journal.json"


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BigbrainError("Cannot read native session state: %s" % path, EXIT_CONFIG) from exc


def durable_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        os.chmod(tmp, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def lock(session_dir):
    # flock is released by the OS after exit/SIGKILL; never delete its inode.
    import fcntl

    root = Path(session_dir)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".claude.lock", "a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BigbrainError("This task is busy; another command holds its session lock", EXIT_CONFIG) from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def binding(transcript, root):
    return {"task_sha256": hashlib.sha256(transcript["task"].encode()).hexdigest(),
            "cwd": str(Path(transcript["cwd"]).resolve()),
            "task_dir": str(Path(root).resolve()),
            "codex_thread_id": transcript.get("codex_thread_id")}


def validate(state, transcript, root):
    if state["binding"] != binding(transcript, root):
        raise BigbrainError("Native session task/workspace binding changed; refusing to resume", EXIT_CONFIG)
    owner = state["binding"].get("codex_thread_id")
    current = os.environ.get("CODEX_THREAD_ID")
    if owner and current and owner != current:
        raise BigbrainError("Native session belongs to another chat", EXIT_CONFIG)


def status(root):
    root = Path(root)
    state = read(root / STATE) if (root / STATE).exists() else None
    journal = read(root / JOURNAL) if (root / JOURNAL).exists() else None
    pending = journal and journal["state"] != "applied"
    captured = pending and journal["calls"] and all("response" in c for c in journal["calls"])
    public_state = {k: v for k, v in (state or {}).items() if k != "system_prompt"}
    sid = (state or {}).get("id", "unknown")
    replacement = str(root.resolve().with_name(root.name + "-replacement"))
    recovery_hint = ("Inspect native history with claude --resume %s. Restore missing history before retry; "
                     "if abandoning it, explicitly start a NEW task directory such as %s and retain "
                     "this journal and unknown-cost flag. Never reuse start --force here." % (sid, replacement))
    return {"session": public_state or None, "journal_state": journal["state"] if journal else None,
            "operation_id": journal["id"] if journal else None,
            "next_action": ("recover --session DIR (local receipts only)" if captured else
                            "Outcome unknown. " + recovery_hint if pending else
                            "Missing native session. " + recovery_hint if state and state.get("missing_session") else
                            "Last native call failed; inspect session history/login before retrying" if state and state.get("last_call_error") else "ready"),
            "outcome_unknown": bool(pending and not captured)}


def guard(root):
    journal_path = Path(root) / JOURNAL
    transcript_path = Path(root) / "transcript.json"
    if journal_path.exists() and transcript_path.exists():
        journal = read(journal_path)
        if journal["state"] != "applied" and read(transcript_path).get("native_applied_operation") == journal["id"]:
            mark_applied(root, journal)
    info = status(root)
    if info["journal_state"] not in (None, "applied"):
        raise BigbrainError("Previous Claude operation is unfinished: " + info["next_action"], EXIT_CONFIG)


def checkpoint(root, transcript):
    """Prepare commit marker in the SAME atomic transcript as its usage/state."""
    op_id = transcript.pop("_native_operation_id", None)
    if not op_id:
        return None
    journal = read(Path(root) / JOURNAL)
    state = read(Path(root) / STATE)
    transcript["claude_session"] = state
    if journal["id"] != op_id or not journal["calls"] or not all("response" in c for c in journal["calls"]):
        return None
    transcript["native_applied_operation"] = op_id
    return journal


def mark_applied(root, journal):
    if journal:
        # Stable operation filenames make commit recovery idempotent and retain
        # paid failure/repair receipts after the active journal advances.
        durable_write(Path(root) / "claude-receipts" / (journal["id"] + ".json"), {
            "id": journal["id"], "kind": journal["kind"],
            "calls": [{"id": c["id"], "usage": c["response"][1], "meta": c["response"][2]}
                      for c in journal["calls"] if "response" in c]})
        journal["state"] = "applied"
        durable_write(Path(root) / JOURNAL, journal)


class Turn:
    def __init__(self, root, transcript, user_content, kind, system_prompt, cfg):
        self.root, self.cfg = Path(root), cfg
        self.index = 0
        self.recovering = bool(cfg.get("_native_recover"))
        path = self.root / STATE
        if path.exists():
            self.state = read(path)
            validate(self.state, transcript, root)
        else:
            self.state = {"id": str(uuid.uuid4()), "binding": binding(transcript, root),
                          "system_prompt": system_prompt, "started": False,
                          "cost_cumulative": 0.0, "compactions": 0,
                          "migrated_from_nonpersistent": bool(transcript.get("messages"))}
            durable_write(path, self.state)
        if self.recovering:
            self.journal = read(self.root / JOURNAL)
        else:
            guard(root)
            self.journal = {"id": str(uuid.uuid4()), "state": "pending", "kind": kind,
                            "snapshot": copy.deepcopy(transcript), "user_content": user_content,
                            "effort": cfg.get("effort", "medium"), "calls": []}
            durable_write(self.root / JOURNAL, self.journal)
        transcript["_native_operation_id"] = self.journal["id"]

    def messages(self, transcript, user_content):
        if self.recovering and self.journal["calls"]:
            return copy.deepcopy(self.journal["calls"][0]["messages"])
        capsule = {"task": transcript["task"],
                   "acceptance_criteria": transcript.get("acceptance_criteria", []),
                   "current_milestone": transcript.get("current_milestone"),
                   "user_corrections": transcript.get("user_feedback", [])}
        messages = []
        if not self.state["started"]:
            # One-time legacy bootstrap, explicitly recorded; never pretend resume.
            messages = list(transcript.get("messages", []))
        return messages + [{"role": "user", "content": "# REASSERTED TASK CONTRACT\n" + json.dumps(capsule)},
                           {"role": "user", "content": user_content}]

    def send(self, messages):
        from .claude_code import send

        index = self.index
        self.index += 1
        if index < len(self.journal["calls"]):
            call = self.journal["calls"][index]
            if "response" not in call:
                raise BigbrainError("Claude outcome unknown; refusing automatic resend", EXIT_CONFIG)
            self.state = call["state_after"]
            durable_write(self.root / STATE, self.state)
            return copy.deepcopy(call["response"])
        if self.recovering:
            raise BigbrainError("Recovery needs another Claude call; no automatic paid retry", EXIT_CONFIG)
        # Repairs send only the repair instruction; Claude already has the reply.
        if index:
            messages = [messages[-1]]
        call = {"id": str(uuid.uuid4()), "state": "pending", "messages": messages,
                "cost_before": self.state.get("cost_cumulative")}
        self.journal["calls"].append(call)
        durable_write(self.root / JOURNAL, self.journal)
        receipt_written = False

        def captured(response):
            nonlocal receipt_written
            text, usage, meta = copy.deepcopy(response)
            if meta.get("cli_session_id") != self.state["id"]:
                raise BigbrainError("Claude returned a different/missing session ID; refusing rebind", EXIT_CONFIG)
            cumulative = usage.pop("cli_cost_usd", None)
            baseline = call["cost_before"]
            if meta.get("missing_session"):
                # Verified CLI startup error: zero API time/turns. Its 0 is not
                # a reset of the existing session's cumulative spending.
                usage["cli_cost_usd"] = 0.0
            elif cumulative is not None and baseline is not None and cumulative >= baseline:
                usage["cli_cost_usd"] = cumulative - baseline
            else:
                usage["cli_cost_missing"] = True
            if not meta.get("missing_session"):
                self.state["cost_cumulative"] = cumulative
            self.state["started"] = True
            self.state["last_call_error"] = bool(meta.get("cli_error"))
            self.state["missing_session"] = bool(meta.get("missing_session"))
            self.state["compactions"] += meta.get("compactions", 0)
            meta.update(native_call_id=call["id"], cost_cumulative_usd=cumulative,
                        cost_scope="native-session cumulative; usage is invocation-local", usage=usage)
            call.update(state="captured", response=[text, usage, meta], state_after=copy.deepcopy(self.state))
            self.journal["state"] = "captured"
            # Receipt first; replay can repair a crash before the state checkpoint.
            durable_write(self.root / JOURNAL, self.journal)
            receipt_written = True
            durable_write(self.root / STATE, self.state)

        cfg = dict(self.cfg, _native_id=self.state["id"], _native_resume=self.state["started"],
                   _capture_result=captured)
        try:
            send(cfg, self.state["system_prompt"], messages)
        except BaseException:
            if not receipt_written:
                raise
            # A complete terminal receipt survives transport shutdown errors.
        if not receipt_written:
            raise BigbrainError("Claude produced no durable terminal receipt; outcome unknown", EXIT_CONFIG)
        return copy.deepcopy(call["response"])
