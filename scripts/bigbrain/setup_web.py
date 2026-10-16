"""Loopback-only configuration form. Credentials never enter the launch URL or logs."""

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import BigbrainError
from .setup_wizard import VALIDATE_TIMEOUT, _scrub, configure, credentials

ASSETS = Path(__file__).with_name("setup_ui")


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, timeout=VALIDATE_TIMEOUT):
        super().__init__(("127.0.0.1", 0), SetupHandler)
        self.origin = "http://127.0.0.1:%d" % self.server_port
        self.token = secrets.token_urlsafe(32)
        self.api_timeout = timeout
        self.values = None
        self.result = None
        self.lock = threading.Lock()

    @property
    def url(self):
        return self.origin + "/#" + self.token

    def finish(self):
        self.values = None
        threading.Thread(target=self.shutdown, daemon=True).start()


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def host_valid(self):
        return self.headers.get("Host") == "127.0.0.1:%d" % self.server.server_port

    def do_GET(self):
        if not self.host_valid():
            self.reply(403, {"error": "Invalid host"})
            return
        assets = {"/": ("index.html", "text/html"),
                  "/setup.css": ("setup.css", "text/css"),
                  "/setup.js": ("setup.js", "text/javascript")}
        if self.path not in assets:
            self.reply(404, {"error": "Not found"})
            return
        name, kind = assets[self.path]
        self.reply(200, (ASSETS / name).read_bytes(), kind + "; charset=utf-8")

    def do_POST(self):
        if (not self.host_valid() or self.headers.get("Origin") != self.server.origin
                or not hmac.compare_digest(self.headers.get("X-Bigbrain-Token", "").encode(), self.server.token.encode())):
            self.reply(403, {"error": "Invalid setup session"})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "JSON required"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError()
            self.connection.settimeout(10)
            values = json.loads(self.rfile.read(size))
            if not isinstance(values, dict):
                raise ValueError()
        except (ValueError, OSError):
            self.reply(400, {"error": "Invalid JSON request"})
            return
        with self.server.lock:
            key = ""
            try:
                if self.path == "/models":
                    self.server.values = None
                    key = values.get("api_key") if isinstance(values.get("api_key"), str) else ""
                    checked = credentials(values.get("base_url"), key)
                    result = configure(checked, timeout=self.server.api_timeout)
                    self.server.values = checked
                    self.reply(200, result)
                elif self.path == "/save":
                    if self.server.values is None:
                        self.reply(400, {"error": "请先填写地址和密钥，并查询模型。"})
                        return
                    key = self.server.values["api_key"]
                    selected = dict(self.server.values, model=values.get("model"))
                    result = configure(selected, save=True, timeout=self.server.api_timeout)
                    self.server.result = {"model": result["model"],
                                          "environment_overrides": result["environment_overrides"]}
                    self.reply(200, self.server.result)
                    self.server.finish()
                elif self.path == "/cancel":
                    self.reply(200, {"ok": True})
                    self.server.finish()
                else:
                    self.reply(404, {"error": "Not found"})
            except BigbrainError as exc:
                self.reply(400, {"error": _scrub(str(exc), key)})
            except OSError:
                self.reply(500, {"error": "无法读取或保存本机配置，请检查文件权限。"})


def run_server(timeout=VALIDATE_TIMEOUT):
    server = SetupServer(timeout)
    timer = threading.Timer(15 * 60, server.shutdown)
    timer.daemon = True
    timer.start()
    print(json.dumps({"setup_url": server.url, "expires_in_seconds": 900}), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        timer.cancel()
        server.values = None
        server.server_close()
    print(json.dumps({"saved": server.result is not None, **(server.result or {})}), flush=True)
    return 0
