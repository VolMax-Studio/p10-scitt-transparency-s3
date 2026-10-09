"""Loopback HTTP API and static UI. Explicit routes only; no directory serving, no CORS, no arbitrary-file endpoint."""
import hmac
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import importer, reports
from .jobs import Busy, BadRequest, JobManager, valid_job_id

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
MAX_JSON = 64 * 1024
RUN_RE = re.compile(r"^/api/runs/([^/]+)(?:/(events|cancel|report|artifacts/([A-Za-z0-9._-]+)))?$")


class App:
    def __init__(self, workspace, module, jobs, token, port):
        self.ws, self.module, self.jobs, self.token, self.port = workspace, module, jobs, token, port
        self.host_header = f"127.0.0.1:{port}"
        self.origin = f"http://127.0.0.1:{port}"
        self.import_lock = threading.Lock()


def make_server(port=0):
    class Handler(BaseHTTPRequestHandler):
        server_version = "P10ReplayWorkbench"
        sys_version = ""
        protocol_version = "HTTP/1.0"
        timeout = 30

        def log_message(self, fmt, *args):
            pass

        # ---- helpers -------------------------------------------------------------------------------------------------------
        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def _err(self, code, error, detail=""):
            self._json(code, {"error": error, "detail": detail})

        def _gate(self, api, post):
            app = self.server.app
            if self.headers.get("Host") != app.host_header:
                self._err(403, "BAD_HOST")
                return False
            if not api:
                return True
            tok = self.headers.get("X-Workbench-Token", "")
            if not hmac.compare_digest(tok.encode(), app.token.encode()):
                self._err(401, "BAD_TOKEN")
                return False
            if post and self.headers.get("Origin") != app.origin:
                self._err(403, "BAD_ORIGIN")
                return False
            return True

        def _body_json(self):
            if self.headers.get("Transfer-Encoding"):
                raise BadRequest("chunked bodies are not accepted")
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise BadRequest("Content-Length required")
            if n < 0 or n > MAX_JSON:
                raise BadRequest("JSON body too large")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                raise BadRequest("Content-Type must be application/json")
            try:
                obj = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise BadRequest("invalid JSON")
            if not isinstance(obj, dict):
                raise BadRequest("JSON object expected")
            return obj

        @staticmethod
        def _only(obj, allowed):
            extra = set(obj) - set(allowed)
            if extra:
                raise BadRequest("unknown fields: " + ", ".join(sorted(extra)))

        # ---- verbs ---------------------------------------------------------------------------------------------------------
        def do_GET(self):
            app = self.server.app
            path = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            try:
                if path in STATIC:
                    if not self._gate(False, False):
                        return
                    name, ctype = STATIC[path]
                    with open(os.path.join(STATIC_DIR, name), "rb") as f:
                        return self._send(200, f.read(), ctype)
                if not path.startswith("/api/"):
                    return self._err(404, "NOT_FOUND")
                if not self._gate(True, False):
                    return
                if path == "/api/modules":
                    d = app.module.describe()
                    d["workspace"] = app.ws.root
                    d["default_deadline_minutes"] = app.jobs.default_deadline_minutes
                    d["packages"] = sorted(x for x in os.listdir(app.ws.p("packages")) if len(x) == 64)
                    return self._json(200, {"modules": [d]})
                if path == "/api/runs":
                    return self._json(200, {"runs": app.jobs.list()})
                m = RUN_RE.match(path)
                if not m or not valid_job_id(m.group(1)):
                    return self._err(404, "NOT_FOUND")
                jid, sub = m.group(1), m.group(2)
                st = app.jobs.status(jid)
                if st is None:
                    return self._err(404, "NO_SUCH_JOB")
                if sub is None:
                    return self._json(200, st)
                if sub == "events":
                    after = 0
                    for kv in query.split("&"):
                        if kv.startswith("after="):
                            try:
                                after = max(0, int(kv[6:]))
                            except ValueError:
                                return self._err(400, "BAD_REQUEST", "after must be an integer")
                    return self._json(200, app.jobs.events(jid, after))
                if sub == "report":
                    data = app.jobs.export(jid)
                    return self._send(200, data, "application/gzip", {"Content-Disposition": f'attachment; filename="replay-report-{jid}.tar.gz"'})
                if sub.startswith("artifacts/"):
                    data = reports.read_served(app.jobs.job_dir(jid), m.group(3))
                    if data is None:
                        return self._err(404, "NO_SUCH_ARTIFACT")
                    return self._send(200, data, "text/plain; charset=utf-8")
                return self._err(404, "NOT_FOUND")
            except BadRequest as e:
                self._err(400, "BAD_REQUEST", str(e))
            except Exception as e:    # never leak a traceback to the client
                self._err(500, "INTERNAL", type(e).__name__)

        def do_POST(self):
            app = self.server.app
            path = self.path.split("?", 1)[0]
            try:
                if not path.startswith("/api/"):
                    return self._err(404, "NOT_FOUND")
                if not self._gate(True, True):
                    return
                if path == "/api/packages":
                    return self._upload()
                if path in ("/api/inspect", "/api/runs"):
                    body = self._body_json()
                    self._only(body, ("package_id", "lean_bin", "allowed_signers", "deadline_minutes"))
                    kind = "readiness" if path == "/api/inspect" else "run"
                    try:
                        jid = app.jobs.start(kind, body.get("package_id"), body.get("lean_bin"), body.get("allowed_signers"), body.get("deadline_minutes"))
                    except Busy as e:
                        return self._err(409, "JOB_ACTIVE", str(e))
                    return self._json(202, {"job_id": jid, "kind": kind})
                m = RUN_RE.match(path)
                if m and m.group(2) == "cancel" and valid_job_id(m.group(1)):
                    return self._json(200, {"cancel_requested": app.jobs.cancel(m.group(1))})
                return self._err(404, "NOT_FOUND")
            except BadRequest as e:
                self._err(400, "BAD_REQUEST", str(e))
            except Exception as e:
                self._err(500, "INTERNAL", type(e).__name__)

        def _upload(self):
            app = self.server.app
            if self.headers.get("Transfer-Encoding"):
                return self._err(400, "BAD_REQUEST", "chunked bodies are not accepted")
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._err(411, "LENGTH_REQUIRED")
            lim = app.module.profile["limits"]["upload_bytes"]
            if n < 0 or n > lim:
                return self._err(413, "UPLOAD_TOO_LARGE", f"limit {lim} bytes")
            remaining = [n]

            def read(k):
                k = min(k, remaining[0])
                b = self.rfile.read(k) if k > 0 else b""
                remaining[0] -= len(b)
                return b
            with app.import_lock:
                try:
                    r = importer.import_package(app.ws, read, app.module.profile)
                except importer.ImportRejected as e:
                    return self._json(422, {"app_status": "IMPORT_REJECTED", "reason": e.code, "detail": e.detail[:300]})
                except OSError as e:
                    return self._json(422, {"app_status": "IMPORT_FAILED", "reason": type(e).__name__})
            if r["app_status"] == "UNSUPPORTED_PACKAGE":
                return self._json(422, r)
            return self._json(200, r)

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    return srv


def create(workspace, module, jobs, token, port=0):
    """Bind 127.0.0.1:<port> and attach the App; returns (server, app)."""
    srv = make_server(port)
    srv.app = App(workspace, module, jobs, token, srv.server_address[1])
    return srv, srv.app
