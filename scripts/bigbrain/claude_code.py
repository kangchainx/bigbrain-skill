"""Read-only Claude Code advisor; Bigbrain owns history and workspace binding."""

import json
import math
import os
import shutil
import signal
import subprocess
import threading

from .client import usage_of
from .config import BigbrainError, EXIT_AUTH, EXIT_CONFIG, EXIT_HTTP, EXIT_NETWORK


def executable():
    path = shutil.which("claude")
    if not path:
        raise BigbrainError("Claude Code CLI not found; install it and run claude auth login", EXIT_CONFIG)
    return path


def check():
    try:
        result = subprocess.run([executable(), "auth", "status"], capture_output=True,
                                text=True, timeout=15)
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise BigbrainError("Cannot read Claude Code login status; run claude auth status", EXIT_AUTH)
    if result.returncode or not isinstance(data, dict) or not data.get("loggedIn"):
        raise BigbrainError("Claude Code is not logged in; run claude auth login", EXIT_AUTH)
    return {"backend": "claude-code", "logged_in": True,
            "auth_method": data.get("authMethod"), "provider": data.get("apiProvider")}


def send(cfg, system_prompt, messages):
    # One input message preserves images as blocks; history is explicitly labelled.
    content = []
    for message in messages:
        content.append({"type": "text", "text": "\n# %s\n" % message["role"].upper()})
        body = message["content"]
        content.extend(body if isinstance(body, list) else [{"type": "text", "text": body}])
    request = {"type": "user", "message": {"role": "user", "content": content}}
    command = [executable(), "--print", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose",
               "--safe-mode", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
               "--tools", "Read,Glob,Grep", "--allowedTools", "Read,Glob,Grep",
               "--permission-mode", "dontAsk", "--model", cfg["model"],
               "--effort", cfg.get("effort", "medium"), "--system-prompt", system_prompt]
    if cfg.get("_native_id"):
        command += ["--resume" if cfg.get("_native_resume") else "--session-id", cfg["_native_id"]]
    else:
        command.append("--no-session-persistence")
    env = dict(os.environ)
    for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
                "CLAUDE_CODE_SKIP_PROMPT_HISTORY"):
        env.pop(key, None)
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, cwd=cfg.get("cwd"), env=env,
                                   start_new_session=os.name == "posix")
    except OSError:
        raise BigbrainError("Cannot launch Claude Code in the session workspace", EXIT_CONFIG)
    events = []
    malformed = []
    read_calls = []
    capture_errors = []

    def write_input():
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def read_output():
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                if line.strip():
                    malformed.append(True)
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") in ("result", "system"):
                events.append(event)
            if event.get("type") == "result" and cfg.get("_capture_result"):
                try:
                    cfg["_capture_result"](decode_result(cfg, events, 0, len(read_calls)))
                except Exception as exc:
                    capture_errors.append(exc)
            if event.get("type") == "assistant":
                message = event.get("message") or {}
                blocks = message.get("content", []) if isinstance(message, dict) else []
                for block in blocks if isinstance(blocks, list) else []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and block.get("name") in ("Read", "Glob", "Grep"):
                        read_calls.append(block["name"])
                        progress = cfg.get("_progress")
                        if progress and len(read_calls) <= 10:
                            target = block.get("input", {}).get("file_path") or block.get("input", {}).get("path") or "workspace"
                            target = str(target).replace("\n", " ").replace("\r", " ")[:160]
                            progress.line("Claude | %s: %s" % (block["name"], target))

    writer = threading.Thread(target=write_input, daemon=True)
    reader = threading.Thread(target=read_output, daemon=True)
    writer.start()
    reader.start()
    try:
        process.wait(timeout=cfg.get("max_total_timeout", 300))
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
        writer.join(timeout=2)
        reader.join(timeout=2)
        if not reader.is_alive():
            process.stdout.close()
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise BigbrainError("Claude Code advisor timed out; usage for this call is unknown", EXIT_NETWORK)
    writer.join(timeout=2)
    reader.join(timeout=2)
    if malformed or reader.is_alive() or writer.is_alive():
        raise BigbrainError("Claude Code returned no valid result JSON; check CLI version and login", EXIT_HTTP)
    process.stdout.close()
    if capture_errors:
        raise capture_errors[0]
    return decode_result(cfg, events, process.returncode, len(read_calls))


def decode_result(cfg, events, returncode, read_count):
    results = [event for event in events if event.get("type") == "result"]
    data = results[-1] if results else None
    if not isinstance(data, dict) or data.get("type") != "result":
        raise BigbrainError("Claude Code returned an unexpected result envelope", EXIT_HTTP)
    usage = usage_of(data)
    cost = data.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
        usage["cli_cost_usd"] = cost
    else:
        usage["cli_cost_missing"] = True
    models = list(data.get("modelUsage") or {})
    advisor_model = next((event["model"] for event in events if isinstance(event, dict)
                          and event.get("type") == "system" and event.get("subtype") == "init"
                          and isinstance(event.get("model"), str)), None)
    if not advisor_model:
        advisor_model = cfg["model"] if cfg["model"] in models or not models else max(
            models, key=lambda model: data["modelUsage"][model].get("outputTokens", 0))
    usage["models"] = models
    meta = {"mode": "live", "backend": "claude-code", "usage": usage,
            "model": advisor_model, "models": models,
            "cli_session_id": data.get("session_id"), "effort": cfg.get("effort", "medium"),
            "session_action": "resume" if cfg.get("_native_resume") else "create" if cfg.get("_native_id") else "ephemeral",
            "requested_session_id": cfg.get("_native_id"),
            "cli_error": bool(returncode or data.get("is_error")),
            "permission_denials": len(data.get("permission_denials") or []),
            "read_tool_calls": read_count,
            "compactions": sum(e.get("type") == "system" and e.get("subtype") == "compact_boundary"
                               for e in events)}
    meta["missing_session"] = bool(cfg.get("_native_resume") and data.get("is_error")
        and data.get("duration_api_ms") == 0 and data.get("num_turns") == 0
        and "No conversation found with session ID: %s" % cfg.get("_native_id") in (data.get("errors") or []))
    text = data.get("result")
    if not isinstance(text, str):
        text = ""
    return text, usage, meta
