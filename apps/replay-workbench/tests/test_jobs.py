"""End-to-end supervision tests with the real worker process and a STUB module. These are synthetic test runs, not offline P10 runs."""
import json
import os
import signal
import tempfile
import time
import unittest

from . import fakes
from workbench import importer, jobs
from workbench.worker import write_json_atomic

PKG = "ab" * 32
APP = fakes.APP


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def read_text(path):
    with open(path) as f:
        return f.read()


def wait_for(cond, timeout=60.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timed out")


class JobBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = self.tmp.name
        self.ws = importer.Workspace(os.path.join(self.t, "ws"))
        os.makedirs(self.ws.p("packages", PKG, "p10-s3-offline", "repo", "ref", "runner"))
        os.makedirs(self.ws.p("packages", PKG, "p10-s3-offline", "repo", "ref", "runner-2"))
        for d in ("runner", "runner-2"):
            with open(self.ws.p("packages", PKG, "p10-s3-offline", "repo", "ref", d, "verdict.json"), "wb") as f:
                f.write(fakes.VERDICT_BYTES)
        self.cfgdir = os.path.join(self.t, "cfg")
        os.makedirs(self.cfgdir)
        self.managers = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for m in self.managers:
            a = m.active
            if a and a["proc"].poll() is None:
                try:
                    os.killpg(a["proc"].pid, signal.SIGKILL)
                except OSError:
                    pass
                a["proc"].wait()

    def manager(self, script, readiness=None, limits=None, min_deadline=1):
        path = os.path.join(self.t, "wrapper.sh")
        with open(path, "w") as f:
            f.write(script)
        prof = fakes.test_profile(**(limits or {}))
        cfg = {"profile": prof, "script": path, "readiness": readiness if readiness is not None else [{"id": "x", "label": "stub readiness", "status": "pass", "detail": ""}]}
        with open(os.path.join(self.cfgdir, "stub_config.json"), "w") as f:
            json.dump(cfg, f)
        m = jobs.JobManager(self.ws, fakes.StubModule(cfg), module_ref="tests.fakes:make_module", extra_sys_path=[APP, self.cfgdir])
        m.min_deadline_minutes = min_deadline
        self.managers.append(m)
        return m

    def start_run(self, m, **kw):
        return m.start("run", PKG, "/opt/lean/bin", None, kw.pop("deadline_minutes", None))

    def done(self, m, jid, timeout=90):
        return wait_for(lambda: (lambda s: s if s and s["status"].get("state") == "DONE" else None)(m.status(jid)), timeout)


class Supervision(JobBase):
    def test_stub_success_is_labelled_synthetic(self):
        m = self.manager(fakes.wrapper_script(0, verdict=fakes.VERDICT_BYTES, info=fakes.dumps(fakes.good_info()), body='echo "ALL PASS: stub"'))
        jid = self.start_run(m)
        s = self.done(m, jid)
        r = s["result"]
        self.assertEqual(r["execution"]["status"], "COMPLETED")
        self.assertEqual(r["p10"]["outcome"], "BINDING_MATCH")
        self.assertEqual(r["reproduction"]["status"], "MATCH")
        self.assertFalse(r["reproduction"]["badge"])
        self.assertTrue(s["synthetic"])
        self.assertIn("SYNTHETIC", s["execution_kind"])
        self.assertEqual(r["wrapper_exit"], 0)
        rep = json.loads(read_text(os.path.join(m.job_dir(jid), "app-report.json")))
        self.assertTrue(rep["not_a_verdict"])
        self.assertTrue(rep["synthetic"])
        self.assertEqual(rep["axes"]["p10_runner_outcome"]["outcome"], "BINDING_MATCH")
        self.assertIn("runner-out/verdict.json", rep["raw_artifacts"])
        # fresh, separate output directory
        self.assertTrue(r["command"]["output_dir"].startswith(m.job_dir(jid)))
        ev = m.events(jid)
        self.assertTrue(any(e["kind"] == "phase" and "host prerequisites" in e["text"] for e in ev["events"]))
        self.assertIn("ALL PASS: stub", ev["stdout"]["text"])
        st = s["status"]
        self.assertGreaterEqual(st["resources"].get("nice", 10), 10)
        self.assertLessEqual(len(st["resources"].get("cpus", [0])), 2)

    # case 3 (job level)
    def test_readiness_failure_starts_no_wrapper(self):
        sentinel = os.path.join(self.t, "sentinel")
        m = self.manager(fakes.wrapper_script(0, verdict=fakes.VERDICT_BYTES, body=f"touch {sentinel}"),
                         readiness=[{"id": "sum", "label": "checksums", "status": "fail", "detail": "sha256sum -c exited with status 1"}])
        s = self.done(m, self.start_run(m))
        self.assertEqual(s["result"]["execution"], {"status": "BLOCKED", "reason": "READINESS_FAILED"})
        self.assertEqual(s["result"]["p10"]["state"], "NOT_EVALUATED")
        self.assertFalse(os.path.exists(sentinel))
        self.assertFalse(os.path.exists(os.path.join(m.job_dir(s["job_id"]), "runner-out")))

    def test_readiness_job_has_no_p10_outcome(self):
        m = self.manager(fakes.wrapper_script(0))
        jid = m.start("readiness", PKG, "/opt/lean/bin", None, None)
        r = self.done(m, jid)["result"]
        self.assertEqual(r["execution"]["status"], "COMPLETED")
        self.assertEqual(r["p10"]["state"], "NOT_EVALUATED")
        self.assertFalse(r["reproduction"]["badge"])

    # case 8
    def test_all_pass_stub_without_records_is_not_success(self):
        m = self.manager(fakes.wrapper_script(0, body='echo "ALL PASS: the offline replay reproduced the accepted verdict on this host."'))
        r = self.done(m, self.start_run(m))["result"]
        self.assertEqual(r["execution"]["status"], "APP_FAILURE")
        self.assertFalse(r["reproduction"]["badge"])
        self.assertNotEqual(r["reproduction"]["status"], "MATCH")

    # case 6 (job level)
    def test_reject_with_wrapper_exit_1(self):
        v = fakes.dumps(fakes.good_verdict(outcome="REJECT", reason={"code": "SomeCode", "rule": "R"}))
        m = self.manager(fakes.wrapper_script(1, verdict=v, info=fakes.dumps(fakes.good_info())))
        r = self.done(m, self.start_run(m))["result"]
        self.assertEqual((r["execution"]["status"], r["p10"]["outcome"], r["reproduction"]["status"], r["wrapper_exit"]), ("COMPLETED", "REJECT", "DIFFERENT", 1))

    # case 10
    def test_cancel_kills_process_group_and_child_and_keeps_partial_records(self):
        pidfile = os.path.join(self.t, "child.pid")
        body = f'sleep 300 &\necho $! > {pidfile}\nwait'
        m = self.manager(fakes.wrapper_script(0, verdict=fakes.VERDICT_BYTES, info=fakes.dumps(fakes.good_info()), body=body))
        jid = self.start_run(m)
        child = int(wait_for(lambda: os.path.exists(pidfile) and read_text(pidfile).strip() or None))
        self.assertTrue(alive(child))
        self.assertTrue(m.cancel(jid))
        s = self.done(m, jid)
        self.assertEqual(s["result"]["execution"]["status"], "CANCELLED")
        self.assertFalse(s["result"]["reproduction"]["badge"])
        self.assertIsNone(s["result"]["p10"]["outcome"])
        self.assertTrue(s["result"]["artifacts"]["verdict.json"]["present"])
        wait_for(lambda: not alive(child), 10)

    def test_term_ignoring_child_is_killed_after_five_seconds(self):
        pidfile = os.path.join(self.t, "child.pid")
        body = f"trap '' TERM\n(trap '' TERM; exec sleep 300) &\necho $! > {pidfile}\nwhile true; do sleep 1; done"
        m = self.manager(fakes.wrapper_script(0, body=body))
        jid = self.start_run(m)
        child = int(wait_for(lambda: os.path.exists(pidfile) and read_text(pidfile).strip() or None))
        t0 = time.time()
        m.cancel(jid)
        s = self.done(m, jid)
        self.assertGreaterEqual(time.time() - t0, 4.5)
        self.assertTrue(s["result"]["supervision"]["cleanup"]["kill"])
        wait_for(lambda: not alive(child), 10)
        self.assertEqual(s["result"]["execution"]["status"], "CANCELLED")

    def test_deadline_stops_job(self):
        pidfile = os.path.join(self.t, "child.pid")
        m = self.manager(fakes.wrapper_script(0, body=f"sleep 300 &\necho $! > {pidfile}\nwait"), min_deadline=0.01)
        jid = self.start_run(m, deadline_minutes=0.03)
        child = int(wait_for(lambda: os.path.exists(pidfile) and read_text(pidfile).strip() or None))
        s = self.done(m, jid)
        self.assertEqual(s["result"]["execution"], {"status": "CANCELLED", "reason": "deadline"})
        wait_for(lambda: not alive(child), 10)
        self.assertEqual(s["result"]["p10"]["state"], "NOT_EVALUATED")

    # case 11
    def test_one_active_job(self):
        m = self.manager(fakes.wrapper_script(0, body="sleep 300"))
        jid = self.start_run(m)
        with self.assertRaises(jobs.Busy):
            self.start_run(m)
        with self.assertRaises(jobs.Busy):
            m.start("readiness", PKG, "/opt/lean/bin", None, None)
        wait_for(lambda: m.status(jid)["status"].get("phase") == "wrapper" or m.status(jid)["status"].get("child_pgid"))
        m.cancel(jid)
        self.done(m, jid)
        wait_for(lambda: not m.is_busy())
        jid2 = m.start("readiness", PKG, "/opt/lean/bin", None, None)
        self.assertNotEqual(jid, jid2)
        self.done(m, jid2)

    def test_restart_recovery_marks_interrupted_and_never_reruns(self):
        m = self.manager(fakes.wrapper_script(0))
        jid = "20260101T000000Z-deadbeef"
        jd = self.ws.p("runs", jid)
        os.makedirs(os.path.join(jd, "runner-out"))
        with open(os.path.join(jd, "runner-out", "verdict.json"), "wb") as f:
            f.write(fakes.VERDICT_BYTES)
        write_json_atomic(os.path.join(jd, "status.json"), {"state": "RUNNING", "execution": "RUNNING", "kind": "run", "worker_pid": 2 ** 22 - 3, "worker_start_ticks": 1})
        m2 = self.manager(fakes.wrapper_script(0))
        s = m2.status(jid)
        self.assertEqual(s["status"]["state"], "DONE")
        self.assertEqual(s["result"]["execution"], {"status": "APP_FAILURE", "reason": "INTERRUPTED_BY_RESTART"})
        self.assertFalse(s["result"]["reproduction"]["badge"])
        self.assertTrue(os.path.exists(os.path.join(jd, "runner-out", "verdict.json")), "partial files are preserved")
        self.assertFalse(m2.is_busy())
        self.assertIsNone(m2.active)

    def test_logs_and_events_are_bounded(self):
        body = 'head -c 200000 /dev/zero | tr "\\0" "x"\nfor i in $(seq 1 600); do echo "== phase $i"; done'
        m = self.manager(fakes.wrapper_script(0, body=body), limits={"log_bytes": 2000})
        s = self.done(m, self.start_run(m))
        self.assertEqual(s["result"]["execution"], {"status": "APP_FAILURE", "reason": "LOG_LIMIT_EXCEEDED"})
        self.assertLessEqual(os.path.getsize(os.path.join(m.job_dir(s["job_id"]), "stdout.log")), 2000)
        self.assertLessEqual(len(m.events(s["job_id"])["events"]), 500)

    def test_event_stream_is_capped(self):
        body = 'for i in $(seq 1 600); do echo "== phase $i"; done'
        m = self.manager(fakes.wrapper_script(0, body=body))
        s = self.done(m, self.start_run(m))
        n = len(read_text(os.path.join(m.job_dir(s["job_id"]), "events.jsonl")).splitlines())
        self.assertLessEqual(n, 210)

    def test_worker_crash_is_an_application_failure_and_cleans_child(self):
        pidfile = os.path.join(self.t, "child.pid")
        m = self.manager(fakes.wrapper_script(0, body=f"sleep 300 &\necho $! > {pidfile}\nwait"))
        jid = self.start_run(m)
        child = int(wait_for(lambda: os.path.exists(pidfile) and read_text(pidfile).strip() or None))
        wait_for(lambda: m.status(jid)["status"].get("child_pgid"))
        os.kill(m.active["proc"].pid, signal.SIGKILL)
        s = self.done(m, jid)
        self.assertEqual(s["result"]["execution"]["status"], "APP_FAILURE")
        self.assertFalse(s["result"]["reproduction"]["badge"])
        wait_for(lambda: not alive(child), 10)

    def test_start_validation(self):
        m = self.manager(fakes.wrapper_script(0))
        for kw in (dict(package_id="xyz"), dict(package_id="cd" * 32), dict(lean_bin="relative/path"), dict(lean_bin="/a/../b"), dict(lean_bin="/a\x00b"),
                   dict(allowed_signers="rel"), dict(deadline_minutes=0), dict(deadline_minutes=True), dict(deadline_minutes="60")):
            args = dict(package_id=PKG, lean_bin="/opt/lean/bin", allowed_signers=None, deadline_minutes=None)
            args.update(kw)
            with self.assertRaises(jobs.BadRequest, msg=str(kw)):
                m.start("run", args["package_id"], args["lean_bin"], args["allowed_signers"], args["deadline_minutes"])
        with self.assertRaises(jobs.BadRequest):
            m.start("shell", PKG, "/opt/lean/bin")


if __name__ == "__main__":
    unittest.main()
