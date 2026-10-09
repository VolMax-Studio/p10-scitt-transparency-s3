import http.client
import io
import json
import os
import re
import tarfile
import tempfile
import threading
import unittest

from . import fakes
from .test_jobs import JobBase, PKG, wait_for
from workbench import importer, jobs, reports, server

TOKEN = "t" * 43


class ServerBase(JobBase):
    def serve(self, script, **kw):
        m = self.manager(script, **kw)
        self.srv, self.app = server.create(self.ws, m.module, m, TOKEN, 0)
        self.port = self.app.port
        th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        th.start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.m = m
        return m

    def req(self, method, path, body=None, headers=None, host=True, token=True, origin=True, ctype="application/json"):
        h = {}
        if host is True:
            h["Host"] = f"127.0.0.1:{self.port}"
        elif host:
            h["Host"] = host
        if token is True:
            h["X-Workbench-Token"] = TOKEN
        elif token:
            h["X-Workbench-Token"] = token
        if origin is True and method == "POST":
            h["Origin"] = f"http://127.0.0.1:{self.port}"
        elif origin and method == "POST":
            h["Origin"] = origin
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h["Content-Type"] = ctype
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            c.putheader(k, v)
        if data is not None and "Content-Length" not in h:
            c.putheader("Content-Length", str(len(data)))
        c.endheaders(data)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r, out


class Boundary(ServerBase):
    # case 12
    def test_host_must_match_exactly(self):
        self.serve(fakes.wrapper_script(0))
        for host in ("evil.example", f"localhost:{self.port}", "127.0.0.1", f"127.0.0.1:{self.port + 1}", f"127.0.0.1:{self.port}.evil.com"):
            self.assertEqual(self.req("GET", "/api/modules", host=host)[0].status, 403, host)
            self.assertEqual(self.req("GET", "/", host=host, token=False)[0].status, 403, host)
        self.assertEqual(self.req("GET", "/api/modules")[0].status, 200)

    def test_token_required_on_every_api_route(self):
        self.serve(fakes.wrapper_script(0))
        for path in ("/api/modules", "/api/runs", "/api/runs/20260101T000000Z-aaaaaaaa", "/api/runs/20260101T000000Z-aaaaaaaa/events"):
            self.assertEqual(self.req("GET", path, token=False)[0].status, 401, path)
            self.assertEqual(self.req("GET", path, token="wrong")[0].status, 401, path)
        self.assertEqual(self.req("POST", "/api/runs", {}, token=False)[0].status, 401)

    def test_origin_required_on_state_changing_requests(self):
        self.serve(fakes.wrapper_script(0))
        body = {"package_id": PKG, "lean_bin": "/opt/lean/bin"}
        for origin in (False, "http://evil.example", f"http://localhost:{self.port}", f"https://127.0.0.1:{self.port}", "null"):
            self.assertEqual(self.req("POST", "/api/inspect", body, origin=origin)[0].status, 403, origin)
        self.assertEqual(self.m.list(), [])
        self.assertEqual(self.req("POST", "/api/inspect", body)[0].status, 202)

    def test_no_cors_and_security_headers(self):
        self.serve(fakes.wrapper_script(0))
        r, body = self.req("GET", "/", token=False)
        self.assertEqual(r.status, 200)
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        r, _ = self.req("OPTIONS", "/api/modules")
        self.assertIn(r.status, (501, 405, 404))

    def test_only_explicit_routes_no_file_serving(self):
        self.serve(fakes.wrapper_script(0))
        for p in ("/etc/passwd", "/../../etc/passwd", "/static/app.js", "/app.js/../run.py", "/run.py", "/workbench/server.py", "/profiles/s3-accepted-rev2.json",
                  "/%2e%2e/run.py", "/api/../run.py", "/tests/fakes.py", "/ARCHITECTURE.md"):
            r, body = self.req("GET", p, token=False)
            self.assertIn(r.status, (401, 404) if p.startswith("/api/") else (404,), p)    # /api/ paths without a token stop at the token gate
            self.assertNotIn(b"import", body, p)
        self.assertEqual(self.req("GET", "/app.js", token=False)[0].status, 200)
        self.assertEqual(self.req("GET", "/app.css", token=False)[0].status, 200)

    def test_json_body_validation(self):
        self.serve(fakes.wrapper_script(0))
        self.assertEqual(self.req("POST", "/api/runs", b"{}", ctype="text/plain")[0].status, 400)
        self.assertEqual(self.req("POST", "/api/runs", b"x" * 70000)[0].status, 400)
        self.assertEqual(self.req("POST", "/api/runs", b"[1]")[0].status, 400)
        self.assertEqual(self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "/o", "command": "rm -rf /"})[0].status, 400)
        self.assertEqual(self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "/o", "expected_verdict": "x"})[0].status, 400)
        self.assertEqual(self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "relative"})[0].status, 400)

    def test_second_start_is_409_not_queued(self):
        self.serve(fakes.wrapper_script(0, body="sleep 300"))
        r, b = self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "/opt/lean/bin"})
        self.assertEqual(r.status, 202)
        jid = json.loads(b)["job_id"]
        r, b = self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "/opt/lean/bin"})
        self.assertEqual((r.status, json.loads(b)["error"]), (409, "JOB_ACTIVE"))
        wait_for(lambda: self.m.status(jid)["status"].get("child_pgid"))
        r, b = self.req("POST", f"/api/runs/{jid}/cancel", {})
        self.assertEqual(json.loads(b), {"cancel_requested": True})
        self.done(self.m, jid)

    def test_upload_limits_and_unsupported_package(self):
        self.serve(fakes.wrapper_script(0), limits={"upload_bytes": 5000})
        r, b = self.req("POST", "/api/packages", headers={"Content-Length": "999999", "Content-Type": "application/octet-stream"}, body=None)
        self.assertEqual(r.status, 413)
        r, b = self.req("POST", "/api/packages", b"junk" * 10, ctype="application/octet-stream")
        self.assertEqual(r.status, 422)
        j = json.loads(b)
        self.assertEqual(j["app_status"], "UNSUPPORTED_PACKAGE")
        self.assertEqual(j["sha256"], fakes.sha(b"junk" * 10))
        self.assertEqual(os.listdir(self.ws.p("packages")), [PKG])           # nothing new was extracted
        r, b = self.req("POST", "/api/packages", b"x", ctype="application/octet-stream", headers={"Transfer-Encoding": "chunked"})
        self.assertEqual(r.status, 400)

    def test_hostile_log_text_is_data_only(self):
        evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
        self.serve(fakes.wrapper_script(0, body=f"echo '{evil}'; echo '{evil}' >&2"))
        jid = json.loads(self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "/opt/lean/bin"})[1])["job_id"]
        self.done(self.m, jid)
        r, b = self.req("GET", f"/api/runs/{jid}/events")
        self.assertTrue(r.getheader("Content-Type").startswith("application/json"))
        self.assertIn(evil, json.loads(b)["stdout"]["text"])
        r, b = self.req("GET", f"/api/runs/{jid}/artifacts/stdout.log")
        self.assertTrue(r.getheader("Content-Type").startswith("text/plain"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))

    def test_ui_source_uses_text_rendering_only(self):
        with open(os.path.join(server.STATIC_DIR, "app.js")) as f:
            js = f.read()
        with open(os.path.join(server.STATIC_DIR, "index.html")) as f:
            html = f.read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "srcdoc"):
            self.assertNotIn(bad, js, bad)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")                   # no inline script
        self.assertNotRegex(html, r"\son\w+\s*=")                               # no inline handlers
        self.assertNotIn("http://", js.replace("http://127.0.0.1", ""))          # nothing remote
        self.assertNotRegex(html + js, r"https?://(?!127\.0\.0\.1)")

    def test_report_and_artifact_allowlists(self):
        v = fakes.VERDICT_BYTES
        self.serve(fakes.wrapper_script(0, verdict=v, info=fakes.dumps(fakes.good_info()), body="echo hi"))
        jid = json.loads(self.req("POST", "/api/runs", {"package_id": PKG, "lean_bin": "/opt/lean/bin"})[1])["job_id"]
        self.done(self.m, jid)
        jd = self.m.job_dir(jid)
        for rel, data in (("secret.txt", b"custody"), ("runner-out/extra.bin", b"x"), ("worker.out", b"w"), ("allowed_signers.pub", b"pub"), ("job.json", b"{}")):
            os.makedirs(os.path.dirname(os.path.join(jd, rel)), exist_ok=True)
            with open(os.path.join(jd, rel), "ab") as f:
                f.write(data)
        os.makedirs(os.path.join(jd, "runner-out", "logs"), exist_ok=True)
        with open(os.path.join(jd, "runner-out", "logs", "001.stdout"), "wb") as f:
            f.write(b"cache")
        os.symlink("/etc/passwd", os.path.join(jd, "runner-out", "preflight.json"))
        r, data = self.req("GET", f"/api/runs/{jid}/report")
        self.assertEqual(r.status, 200)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            names = sorted(m.name for m in tf)
            allowed = {"replay-report/" + n for n in reports.ARTIFACTS.values()} | {"replay-report/REPORT_SHA256SUMS"}
            self.assertTrue(set(names) <= allowed, set(names) - allowed)
            self.assertIn("replay-report/runner/verdict.json", names)
            self.assertIn("replay-report/app-report.json", names)
            self.assertNotIn("replay-report/runner/preflight.json", names, "symlinked artifacts are not exported")
            blob = b"".join(tf.extractfile(m).read() for m in tf if m.isfile())
            sums = tf.extractfile("replay-report/REPORT_SHA256SUMS").read().decode()
            for line in sums.splitlines():
                h, n = line.split("  ")
                self.assertEqual(fakes.sha(tf.extractfile("replay-report/" + n).read()), h)
        self.assertNotIn(TOKEN.encode(), blob)
        self.assertNotIn(b"custody", blob)
        for name in ("secret.txt", "job.json", "worker.out", "allowed_signers.pub", "../job.json", "..%2fjob.json", "preflight.json", "nope", "verdict.json/../job.json"):
            r, _ = self.req("GET", f"/api/runs/{jid}/artifacts/{name}")
            self.assertEqual(r.status, 404, name)
        self.assertEqual(self.req("GET", f"/api/runs/{jid}/artifacts/verdict.json")[1], v)
        for bad_id in ("..", "../x", "20260101T000000Z-zzzzzzzz", "x"):
            self.assertEqual(self.req("GET", f"/api/runs/{bad_id}")[0].status, 404, bad_id)


if __name__ == "__main__":
    unittest.main()
