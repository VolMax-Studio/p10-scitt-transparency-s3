import json
import os
import re
import unittest

from . import fakes
from .test_jobs import PKG
from .test_server import ServerBase, TOKEN
from workbench import modules, server
from workbench.modules import Registry, UnknownModule
from workbench.modules.s3 import S3Module
from workbench.util import write_json_atomic

TITLE = "S3 — Accepted capture replay"
SUMMARY = "Reproduce the accepted S3 capture offline using the approved package and the existing verification chain."


class RegistryTests(unittest.TestCase):
    def test_only_s3_is_registered_by_the_application(self):
        r = modules.default_registry()
        self.assertEqual(r.ids(), ["s3"])
        d = r.describe_all()
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["id"], d[0]["module"], d[0]["title"], d[0]["summary"], d[0]["action"], d[0]["available"]),
                         ("s3", "s3", TITLE, SUMMARY, "Open module", True))
        self.assertEqual(d[0]["profile_id"], "p10-s3-accepted-e56d3ea-rev2")          # existing identifiers are reused

    def test_available_means_implemented_not_verified(self):
        d = modules.default_registry().get("s3").describe()
        for k in d:
            for word in ("verified", "badge", "reproduced", "success", "ready", "binding"):
                self.assertNotIn(word, k.lower(), k)
        self.assertNotIn("badge", json.dumps({k: v for k, v in d.items() if k not in ("execution_kind", "description")}).lower())

    def test_unknown_and_malformed_identifiers_are_rejected(self):
        r = modules.default_registry()
        for bad in ("s1", "s2", "s2a", "s2b", "S3", "s3 ", " s3", "s3/", "../s3", "", None, 3, ["s3"], {"s3": 1}, "s" * 100, "s3\x00", "s3;rm"):
            with self.assertRaises(UnknownModule, msg=repr(bad)):
                r.get(bad)

    def test_registration_is_code_only_and_validated(self):
        r = Registry()
        r.register(S3Module.shipped())
        with self.assertRaises(ValueError):
            r.register(S3Module.shipped())                                          # duplicate

        class Bad:
            name = "Bad Id!"
        with self.assertRaises(ValueError):
            r.register(Bad())
        with open(modules.__file__) as f:
            src = f.read()
        for word in ("importlib", "__import__", "exec(", "eval(", "tarfile", "open(", "os.listdir", "glob"):
            self.assertNotIn(word, src, "the registry must not load modules from files or archives")

    def test_s1_s2_are_not_modules(self):
        self.assertEqual(sorted(n for n in os.listdir(os.path.dirname(modules.__file__)) if n.endswith(".py")), ["__init__.py", "s3.py"])


class ModuleApi(ServerBase):
    def api(self, method, path, body=None, **kw):
        r, data = self.req(method, path, body, **kw)
        return r.status, (json.loads(data) if data else None)

    def test_listing_and_single_descriptor(self):
        self.serve(fakes.wrapper_script(0))
        st, j = self.api("GET", "/api/modules")
        self.assertEqual((st, len(j["modules"])), (200, 1))
        self.assertEqual((j["modules"][0]["id"], j["modules"][0]["title"], j["modules"][0]["summary"]), ("s3", TITLE, SUMMARY))
        st, j = self.api("GET", "/api/modules/s3")
        self.assertEqual((st, j["module"]["id"], j["module"]["action"]), (200, "s3", "Open module"))

    def test_unknown_module_identifiers_are_rejected_everywhere(self):
        self.serve(fakes.wrapper_script(0))
        for mid in ("s9", "s1", "s2a", "S3", "..", "s3%2f..", "x" * 80, "s3;"):
            st, j = self.api("GET", "/api/modules/" + mid)
            self.assertEqual((st, j["error"]), (404, "UNKNOWN_MODULE"), mid)
        good = {"package_id": PKG, "lean_bin": "/opt/lean/bin"}
        for bad in ("s9", "S3", "", None, 3, ["s3"], {"a": 1}, "s3;", "x" * 80):
            for path in ("/api/inspect", "/api/runs"):
                st, j = self.api("POST", path, dict(good, module=bad))
                self.assertEqual((st, j["error"]), (400, "UNKNOWN_MODULE"), (path, bad))
        self.assertEqual(self.m.list(), [], "no job may be created for an unknown module")
        st, j = self.api("POST", "/api/packages?module=s9", b"junk", ctype="application/octet-stream")
        self.assertEqual((st, j["error"]), (404, "UNKNOWN_MODULE"))
        self.assertEqual(os.listdir(self.ws.p("packages")), [PKG], "nothing was imported for an unknown module")

    def test_known_module_and_the_old_requests_without_a_module_still_work(self):
        self.serve(fakes.wrapper_script(0))
        for body in (dict(package_id=PKG, lean_bin="/opt/lean/bin"), dict(package_id=PKG, lean_bin="/opt/lean/bin", module="s3")):
            st, j = self.api("POST", "/api/inspect", body)
            self.assertEqual(st, 202, body)
            self.done(self.m, j["job_id"])
        jobs = self.m.list()
        self.assertEqual({x["module"] for x in jobs}, {"s3"})
        st, j = self.api("POST", "/api/packages?module=s3", b"junk", ctype="application/octet-stream")
        self.assertEqual((st, j["app_status"]), (422, "UNSUPPORTED_PACKAGE"))        # the module is known; the archive is not the approved one

    def test_uploaded_archives_cannot_define_modules(self):
        self.serve(fakes.wrapper_script(0), limits={"upload_bytes": 4000})
        import io
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in (("p10-s3-offline/module.json", b'{"id": "evil", "command": ["sh"]}'), ("p10-s3-offline/s3.py", b"raise SystemExit(7)")):
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        st, j = self.api("POST", "/api/packages", buf.getvalue(), ctype="application/octet-stream")
        self.assertEqual((st, j["app_status"]), (422, "UNSUPPORTED_PACKAGE"))
        self.assertEqual(self.api("GET", "/api/modules")[1]["modules"][0]["id"], "s3")
        self.assertEqual(len(self.api("GET", "/api/modules")[1]["modules"]), 1)
        self.assertEqual(self.api("GET", "/api/modules/evil")[0], 404)

    def test_token_origin_host_apply_to_module_routes(self):
        self.serve(fakes.wrapper_script(0))
        self.assertEqual(self.api("GET", "/api/modules/s3", token=False)[0], 401)
        self.assertEqual(self.api("GET", "/api/modules/s3", host="evil.example")[0], 403)
        self.assertEqual(self.api("POST", "/api/runs", {"module": "s3", "package_id": PKG, "lean_bin": "/o"}, origin="http://evil.example")[0], 403)

    def test_jobs_stored_before_this_version_stay_visible_as_s3(self):
        m = self.serve(fakes.wrapper_script(0))
        for jid, with_field in (("20260101T000000Z-0a1d0a01", False), ("20260101T000001Z-0a1d0a02", True)):
            jd = self.ws.p("runs", jid)
            os.makedirs(jd)
            spec = {"job_id": jid, "kind": "run", "package_id": PKG, "created": "2026-01-01T00:00:00Z", "module_description": {"module": "s3", "execution_kind": "old"}}
            if with_field:
                spec["module_id"] = "s3"
            write_json_atomic(os.path.join(jd, "job.json"), spec)
            write_json_atomic(os.path.join(jd, "status.json"), {"state": "DONE", "execution": "COMPLETED", "kind": "run"})
            write_json_atomic(os.path.join(jd, "result.json"), {"job_id": jid, "kind": "run", "execution": {"status": "COMPLETED", "reason": None},
                                                                 "p10": {"state": "AVAILABLE", "outcome": "BINDING_MATCH"}, "reproduction": {"status": "MATCH", "badge": True, "checks": []}})
        st, j = self.api("GET", "/api/runs")
        old = [r for r in j["runs"] if r["job_id"].startswith("20260101")]
        self.assertEqual(len(old), 2)
        self.assertEqual({r["module"] for r in old}, {"s3"})
        st, j = self.api("GET", "/api/runs/20260101T000000Z-0a1d0a01")
        self.assertEqual((st, j["module"], j["result"]["reproduction"]["badge"]), (200, "s3", True))     # kept as stored

    def test_a_historical_success_does_not_change_the_module_descriptor_or_start_a_job(self):
        self.serve(fakes.wrapper_script(0, verdict=fakes.VERDICT_BYTES, info=fakes.dumps(fakes.good_info())))
        jid = self.api("POST", "/api/runs", {"module": "s3", "package_id": PKG, "lean_bin": "/opt/lean/bin"})[1]["job_id"]
        self.done(self.m, jid)
        before = json.dumps(self.api("GET", "/api/modules/s3")[1]["module"], sort_keys=True)
        self.assertNotIn("MATCH", before)
        self.assertNotIn(jid, before)
        for k in ("verified", "badge", "last_result", "last_job"):
            self.assertNotIn(k, before)
        self.assertEqual(len([x for x in self.m.list() if x["state"] != "DONE"]), 0, "reading modules or history never starts anything")


class UiSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(server.STATIC_DIR, "index.html")) as f:
            cls.html = f.read()
        with open(os.path.join(server.STATIC_DIR, "app.js")) as f:
            cls.js = f.read()

    def home(self):
        return self.html[self.html.index('id="view-home"'):self.html.index('id="view-s3"')]

    def test_home_has_no_static_module_cards_or_placeholders(self):
        h = self.home()
        self.assertIn('id="module-cards"', h)
        self.assertNotRegex(h, r"S1|S2a|S2b|coming soon|placeholder|disabled")
        self.assertEqual(h.count("<article"), 0, "cards are built from the server's module list")
        for word in ("badge", "verified", "reproduced"):
            self.assertNotIn(word, h.lower())

    def test_s3_screen_keeps_the_three_axes_and_details(self):
        for needle in ("Application execution", "P10 runner outcome", "Accepted-result reproduction", "BINDING_MATCH", "Details", "Export report archive",
                       "Wrapper stdout", "Host settings in use", "← Home", "Stop active job"):
            self.assertIn(needle if needle != "← Home" else "&larr; Home", self.html if needle != "← Home" else self.html, needle)
        self.assertIn("not separate modules", self.html)

    def test_navigation_code_never_starts_stops_or_restarts_jobs(self):
        start = self.js.index("function navigate(")
        end = self.js.index("// ---------------------------------------------------------------------------------------------------------- active job indicator")
        nav = self.js[start:end]
        for forbidden in ('"POST"', "/cancel", "/api/runs\"", "start(", "api(\"POST\""):
            self.assertNotIn(forbidden, nav, forbidden)
        # the only code that posts to /cancel is the explicit Stop button handler
        idx = [m.start() for m in re.finditer(r"/cancel", self.js)]
        self.assertEqual(len(idx), 1)
        self.assertIn('$("btn-stop").addEventListener("click"', self.js[idx[0] - 400:idx[0]])
        self.assertNotIn("/api/inspect", self.js[self.js.index("async function render()"):self.js.index("async function renderHome()")])

    def test_module_screens_are_whitelisted_and_validated_by_the_server(self):
        self.assertIn('const MODULE_SCREENS = { s3: "view-s3" };', self.js)
        self.assertIn("/api/modules/", self.js)
        self.assertIn("MODULE_ID_RE", self.js)
        self.assertEqual(self.js.count("view-s3"), 1)

    def test_past_jobs_are_labelled_and_do_not_set_readiness(self):
        self.assertIn("earlier job", self.js)
        fin = self.js[self.js.index("function finish("):self.js.index("function renderRows(")]
        self.assertIn("const fresh = !state.past && state.fresh === st.job_id;", fin)
        self.assertEqual(fin.count("state.readyKey = inputsKey()"), 1)
        self.assertIn("if (fresh) {\n      state.readyKey", fin)

    def test_no_third_party_or_inline_code_and_text_only_rendering(self):
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "localStorage"):
            self.assertNotIn(bad, self.js, bad)
        self.assertNotRegex(self.html, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(self.html + self.js, r"https?://(?!127\.0\.0\.1)")


if __name__ == "__main__":
    unittest.main()
