import json
import os
import socket
import stat
import tempfile
import threading
import unittest

from . import fakes
from .test_server import ServerBase, TOKEN
from workbench import importer, jobs, server
from workbench.settings import FORMAT, SettingsError, SettingsStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "settings.json")
        self.store = SettingsStore(self.path, 60)

    def write_raw(self, data):
        with open(self.path, "wb") as f:
            f.write(data if isinstance(data, bytes) else json.dumps(data).encode())

    def test_missing_file_gives_defaults_without_warning(self):
        self.assertEqual(self.store.load(), ({"lean_bin": "", "allowed_signers": "", "deadline_minutes": 60}, None))

    def test_save_load_roundtrip_with_owner_only_file_and_no_leftovers(self):
        saved = self.store.save({"lean_bin": "/opt/lean 4/bin", "allowed_signers": "/home/u/.ssh/allowed_signers", "deadline_minutes": 90})
        self.assertEqual(self.store.load(), (saved, None))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n != "settings.json"], [], "atomic write leaves no temp file")
        with open(self.path) as f:
            on_disk = json.load(f)
        self.assertEqual(sorted(on_disk), ["allowed_signers", "deadline_minutes", "format", "lean_bin"])
        self.assertEqual(on_disk["format"], FORMAT)

    def test_paths_outside_the_workspace_are_allowed_and_empty_means_unset(self):
        s = self.store.save({"lean_bin": "/somewhere/else/entirely/bin", "allowed_signers": ""})
        self.assertEqual(s["lean_bin"], "/somewhere/else/entirely/bin")
        self.assertEqual(s["allowed_signers"], "")
        self.assertEqual(self.store.save({}), self.store.defaults())

    def test_validation_rejects_bad_input_and_writes_nothing(self):
        bad = [[], "x", None, {"lean_bin": 5}, {"lean_bin": "relative/bin"}, {"lean_bin": "/a/../b"}, {"lean_bin": "/a\x00b"},
               {"lean_bin": "/" + "x" * 5000}, {"allowed_signers": "rel"}, {"allowed_signers": ["/a"]}, {"deadline_minutes": True},
               {"deadline_minutes": "60"}, {"deadline_minutes": 0}, {"deadline_minutes": 1441}, {"deadline_minutes": -3}, {"deadline_minutes": None},
               {"deadline_minutes": float("nan")}, {"token": "x"}, {"lean_bin": "/a", "private_key": "x"}, {"format": "other"}]
        for b in bad:
            with self.assertRaises(SettingsError, msg=repr(b)):
                self.store.save(b)
        self.assertFalse(os.path.exists(self.path))

    def test_malformed_file_gives_defaults_and_a_clear_warning_and_can_be_replaced(self):
        cases = [b"{not json", b"", b"\xff\xfe", b'{"lean_bin": "/a", "lean_bin": "/b"}', b'{"deadline_minutes": NaN}', b"[]", b'{"lean_bin": "relative"}',
                 b'{"unknown": 1}', b'{"deadline_minutes": true}', b" " * (70 * 1024)]
        for raw in cases:
            self.write_raw(raw)
            s, warn = self.store.load()
            self.assertEqual(s, self.store.defaults(), raw[:30])
            self.assertTrue(warn and "defaults are used" in warn, raw[:30])
        saved = self.store.save({"lean_bin": "/ok/bin"})
        self.assertEqual(self.store.load(), (saved, None))

    def test_symlink_and_non_regular_settings_are_refused_and_never_written_through(self):
        target = os.path.join(self.tmp.name, "target.json")
        with open(target, "w") as f:
            f.write('{"lean_bin": "/from/target"}')
        os.symlink(target, self.path)
        s, warn = self.store.load()
        self.assertEqual(s, self.store.defaults())
        self.assertTrue(warn)
        self.store.save({"lean_bin": "/new/bin"})
        self.assertFalse(os.path.islink(self.path))
        with open(target) as f:
            self.assertEqual(json.load(f), {"lean_bin": "/from/target"}, "the link target is untouched")
        os.remove(self.path)
        os.mkfifo(self.path)
        s, warn = SettingsStore(self.path, 60).load()
        self.assertEqual(s, self.store.defaults())

    def test_nothing_secret_is_stored(self):
        self.store.save({"lean_bin": "/opt/lean/bin", "allowed_signers": "/home/u/allowed"})
        with open(self.path) as f:
            raw = f.read()
        for word in ("token", "PRIVATE", "BEGIN"):
            self.assertNotIn(word, raw)


class SettingsApi(ServerBase):
    def settings_req(self, method, body=None, **kw):
        r, data = self.req(method, "/api/settings", body, **kw)
        return r.status, (json.loads(data) if data else None)

    def test_defaults_then_save_then_load(self):
        self.serve(fakes.wrapper_script(0))
        st, j = self.settings_req("GET")
        self.assertEqual(st, 200)
        self.assertEqual((j["settings"], j["warning"]), (j["defaults"], None))
        st, j = self.settings_req("POST", {"lean_bin": "/opt/lean/bin", "allowed_signers": "/x/allowed", "deadline_minutes": 45})
        self.assertEqual((st, j["settings"]["deadline_minutes"]), (200, 45))
        self.assertEqual(self.settings_req("GET")[1]["settings"]["lean_bin"], "/opt/lean/bin")
        self.assertEqual(stat.S_IMODE(os.stat(self.ws.p("settings.json")).st_mode), 0o600)

    def test_host_origin_and_token_checks_apply_to_the_settings_api(self):
        self.serve(fakes.wrapper_script(0))
        body = {"lean_bin": "/opt/lean/bin"}
        self.assertEqual(self.settings_req("GET", token=False)[0], 401)
        self.assertEqual(self.settings_req("GET", token="wrong")[0], 401)
        self.assertEqual(self.settings_req("GET", host="evil.example")[0], 403)
        self.assertEqual(self.settings_req("GET", host=f"localhost:{self.port}")[0], 403)
        self.assertEqual(self.settings_req("POST", body, token=False)[0], 401)
        self.assertEqual(self.settings_req("POST", body, host="evil.example")[0], 403)
        for origin in (False, "http://evil.example", f"http://localhost:{self.port}", "null"):
            self.assertEqual(self.settings_req("POST", body, origin=origin)[0], 403, origin)
        self.assertFalse(os.path.exists(self.ws.p("settings.json")), "rejected requests write nothing")

    def test_body_validation_at_the_api(self):
        self.serve(fakes.wrapper_script(0))
        for body, ctype in (({"lean_bin": "relative"}, "application/json"), ({"deadline_minutes": 0}, "application/json"), ({"deadline_minutes": True}, "application/json"),
                            ({"token": "x"}, "application/json"), ({"lean_bin": "/a/../b"}, "application/json"), (b"[1]", "application/json"),
                            (b"{bad", "application/json"), (b"{}", "text/plain"), (b"x" * 70000, "application/json")):
            r, data = self.req("POST", "/api/settings", body, ctype=ctype)
            self.assertEqual(r.status, 400, body)
        self.assertFalse(os.path.exists(self.ws.p("settings.json")))

    def test_malformed_file_is_reported_with_safe_defaults(self):
        self.serve(fakes.wrapper_script(0))
        with open(self.ws.p("settings.json"), "w") as f:
            f.write("{broken")
        st, j = self.settings_req("GET")
        self.assertEqual((st, j["settings"]), (200, j["defaults"]))
        self.assertIn("invalid", j["warning"])
        self.assertEqual(self.settings_req("POST", {"lean_bin": "/ok"})[0], 200)
        self.assertIsNone(self.settings_req("GET")[1]["warning"])

    def test_write_failure_is_reported_not_swallowed(self):
        self.serve(fakes.wrapper_script(0))
        os.mkdir(self.ws.p("settings.json"))                    # replacing a directory with a file fails
        st, j = self.settings_req("POST", {"lean_bin": "/ok"})
        self.assertEqual((st, j["error"]), (500, "SETTINGS_WRITE_FAILED"))

    def test_settings_never_start_a_job_or_set_readiness(self):
        self.serve(fakes.wrapper_script(0))
        self.settings_req("POST", {"lean_bin": "/opt/lean/bin", "allowed_signers": "/x/allowed"})
        self.settings_req("GET")
        self.assertEqual(self.m.list(), [])
        self.assertFalse(self.m.is_busy())
        self.assertEqual(os.listdir(self.ws.p("runs")), [])


class PersistenceAcrossPorts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = importer.Workspace(os.path.join(self.tmp.name, "ws"))
        self.cfgdir = os.path.join(self.tmp.name, "cfg")
        os.makedirs(self.cfgdir)
        script = os.path.join(self.tmp.name, "w.sh")
        with open(script, "w") as f:
            f.write(fakes.wrapper_script(0))
        cfg = {"profile": fakes.test_profile(), "script": script, "readiness": []}
        self.module = fakes.StubModule(cfg)

    def start(self, port=0):
        mgr = jobs.JobManager(self.ws, self.module, module_ref="tests.fakes:make_module", extra_sys_path=[fakes.APP, self.cfgdir])
        srv, app = server.create(self.ws, self.module, mgr, TOKEN, port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return mgr, srv, app

    @staticmethod
    def call(app, method, path, body=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", app.port, timeout=30)
        h = {"Host": app.host_header, "X-Workbench-Token": TOKEN}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.update({"Content-Type": "application/json", "Origin": app.origin})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = json.loads(r.read())
        c.close()
        return r.status, out

    def test_settings_survive_a_restart_on_a_different_port_without_restoring_any_result(self):
        m1, s1, a1 = self.start()
        self.assertEqual(self.call(a1, "POST", "/api/settings", {"lean_bin": "/opt/lean 4/bin", "allowed_signers": "/h/allowed", "deadline_minutes": 75})[0], 200)
        m1.close()                                   # instance 1 stops; its socket stays bound so the next port is certainly different
        m2, s2, a2 = self.start()
        self.addCleanup(lambda: (s1.shutdown(), s1.server_close(), s2.shutdown(), s2.server_close(), m2.close()))
        self.assertNotEqual(a1.port, a2.port)
        st, j = self.call(a2, "GET", "/api/settings")
        self.assertEqual((st, j["warning"]), (200, None))
        self.assertEqual(j["settings"], {"lean_bin": "/opt/lean 4/bin", "allowed_signers": "/h/allowed", "deadline_minutes": 75})
        self.assertEqual(self.call(a2, "GET", "/api/runs")[1], {"runs": []}, "restoring settings starts no job and restores no result")
        self.assertEqual(os.listdir(self.ws.p("runs")), [])

    def test_port_selection_is_automatic_by_default_and_explicit_ports_are_not_silently_replaced(self):
        m, s1, a1 = self.start()
        self.addCleanup(lambda: (s1.shutdown(), s1.server_close(), m.close()))
        self.assertGreater(a1.port, 0)
        with self.assertRaises(OSError):                       # explicit port already taken: no silent fallback to another port
            server.create(self.ws, self.module, m, TOKEN, a1.port)

    def test_run_py_parser_has_no_fixed_default_port(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("run_py_for_test", os.path.join(fakes.APP, "run.py"))
        run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run)
        ap = run.build_parser()
        self.assertEqual(ap.parse_args([]).port, 0)
        self.assertEqual(ap.parse_args(["--port", "4242"]).port, 4242)
        self.assertEqual(ap.get_default("port"), 0)


class UiSource(unittest.TestCase):
    def test_ui_restores_fields_only(self):
        with open(os.path.join(server.STATIC_DIR, "app.js")) as f:
            js = f.read()
        self.assertNotIn("localStorage", js, "settings live on the server, not in browser storage")
        self.assertIn("/api/settings", js)
        start = js.index("async function loadSettings()")
        body = js[start:js.index("async function saveSettings()")]
        for forbidden in ("start(", "poll(", "/api/inspect", "/api/runs", "readyKey", "finish("):
            self.assertNotIn(forbidden, body, forbidden)
        with open(os.path.join(server.STATIC_DIR, "index.html")) as f:
            self.assertIn("Save host settings", f.read())


if __name__ == "__main__":
    unittest.main()
