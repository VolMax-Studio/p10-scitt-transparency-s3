"""Regression tests for the v0.1.1 findings: swallowed write errors, process/instance control, export snapshots.
All runs here are synthetic (StubModule); a stub run is never an offline P10 run."""
import fcntl
import io
import json
import os
import signal
import subprocess
import tarfile
import threading
import time
import unittest

from . import fakes
from .test_jobs import JobBase, PKG, alive, read_text, wait_for
from workbench import jobs, reports
from workbench.util import claim_result, downgrade, proc_start_ticks, read_json, write_json_atomic

GOOD = dict(verdict=fakes.VERDICT_BYTES, info=fakes.dumps(fakes.good_info()))


def good_script(body=""):
    return fakes.wrapper_script(0, body=body, **GOOD)


class Finding1WriteErrors(JobBase):
    def run_job(self, extra, body=""):
        m = self.manager(good_script(body), extra=extra)
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        return m, jid, self.done(m, jid)

    def assert_failed_without_promotion(self, m, jid, s, reason_prefix, record_expected=True):
        r = s["result"]
        self.assertEqual(r["execution"]["status"], "APP_FAILURE", r["execution"])
        self.assertTrue(r["execution"]["reason"].startswith(reason_prefix), r["execution"])
        self.assertFalse(r["reproduction"]["badge"])
        self.assertEqual(r["reproduction"]["status"], "NOT_EVALUATED")
        self.assertIsNone(r["p10"]["outcome"])
        self.assertEqual(r["p10"]["state"], "NOT_EVALUATED")
        raw = os.path.join(m.job_dir(jid), "runner-out", "verdict.json")
        if record_expected:
            with open(raw, "rb") as f:                  # original runner record untouched
                self.assertEqual(f.read(), fakes.VERDICT_BYTES)
        elif os.path.exists(raw):
            with open(raw, "rb") as f:
                self.assertEqual(f.read(), fakes.VERDICT_BYTES)
        self.assertEqual(s["status"]["execution"], "APP_FAILURE")

    def test_baseline_non_synthetic_stub_gets_badge(self):
        m, jid, s = self.run_job({"synthetic": False})
        self.assertTrue(s["result"]["reproduction"]["badge"])           # proves the failure tests below are not trivially false

    def test_log_open_failure_is_an_application_failure(self):
        m, jid, s = self.run_job({"synthetic": False, "sabotage": {"stdout_dir": True}})
        self.assert_failed_without_promotion(m, jid, s, "LOG_WRITE_FAILED", record_expected=False)   # the child is stopped before it writes
        self.assertEqual(s["result"]["wrapper_exit"], None)

    def test_log_write_failure_enospc_is_an_application_failure(self):
        m, jid, s = self.run_job({"synthetic": False, "sabotage": {"stdout_devfull": True}}, body="echo some stdout text")
        self.assert_failed_without_promotion(m, jid, s, "LOG_WRITE_FAILED")

    def test_report_finalization_failure_is_an_application_failure(self):
        m, jid, s = self.run_job({"synthetic": False, "sabotage": {"report_dir": True}})
        self.assert_failed_without_promotion(m, jid, s, "REPORT_FINALIZATION_FAILED")
        self.assertEqual(s["result"]["downgraded_from"]["execution"]["status"], "COMPLETED")      # what was observed, kept aside
        self.assertTrue(s["result"]["artifacts"]["verdict.json"]["present"])
        self.assertTrue(os.path.exists(os.path.join(m.job_dir(jid), "report-error.txt")))

    def test_supervision_exception_still_cleans_up_the_child(self):
        sentinel = os.path.join(self.t, "sentinel")
        m = self.manager(good_script(f"sleep 2\ntouch {sentinel}\nsleep 60"), extra={"synthetic": False, "sabotage": {"status_dir": True}})
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        s = self.done(m, jid)
        self.assertEqual(s["result"]["execution"]["status"], "APP_FAILURE")
        self.assertTrue(s["result"]["execution"]["reason"].startswith("WORKER_EXCEPTION"))
        self.assertFalse(s["result"]["reproduction"]["badge"])
        time.sleep(3.5)
        self.assertFalse(os.path.exists(sentinel), "the wrapper must have been killed when supervision raised")
        wait_for(lambda: not m.is_busy(), 10)

    def test_downgrade_never_keeps_a_badge(self):
        res = {"execution": {"status": "COMPLETED", "reason": None}, "p10": {"state": "AVAILABLE", "outcome": "BINDING_MATCH"},
               "reproduction": {"status": "MATCH", "badge": True, "checks": [{"id": "x", "ok": True}]}}
        d = downgrade(res, "APP_FAILURE", "X", "note")
        self.assertEqual((d["execution"]["status"], d["reproduction"]["badge"], d["reproduction"]["status"], d["p10"]["outcome"]),
                         ("APP_FAILURE", False, "NOT_EVALUATED", None))
        self.assertTrue(res["reproduction"]["badge"], "the input is not modified")


class Finding2ProcessControl(JobBase):
    def long_script(self, pidfile):
        return fakes.wrapper_script(0, body=f"sleep 300 &\necho $! > {pidfile}\nwait", **GOOD)

    def start_long(self, m, pidfile):
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        child = int(wait_for(lambda: os.path.exists(pidfile) and read_text(pidfile).strip() or None))
        st = wait_for(lambda: (lambda x: x if x and x.get("child_pgid") and x.get("worker_pid") else None)(read_json(os.path.join(m.job_dir(jid), "status.json"))))
        return jid, child, st

    def assert_consistent_interrupted(self, m, jid, reason):
        s = m.status(jid)
        r = s["result"]
        self.assertEqual(r["execution"], {"status": "APP_FAILURE", "reason": reason})
        self.assertFalse(r["reproduction"]["badge"])
        self.assertNotEqual(r["reproduction"]["status"], "MATCH")
        self.assertIsNone(r["p10"]["outcome"])
        self.assertEqual((s["status"]["state"], s["status"]["execution"]), ("DONE", "APP_FAILURE"))
        rep = read_json(os.path.join(m.job_dir(jid), "app-report.json"))
        if rep is not None:
            self.assertEqual(rep["axes"]["application_execution"]["status"], "APP_FAILURE")
            self.assertFalse(rep["axes"]["accepted_reference_reproduction"]["badge"])
        return s

    # one active job across instances ------------------------------------------------------------------------------------------
    def test_second_instance_on_same_workspace_is_refused(self):
        m = self.manager(fakes.wrapper_script(0))
        with self.assertRaises(jobs.WorkspaceInUse):
            self.manager(fakes.wrapper_script(0))
        m.close()
        self.manager(fakes.wrapper_script(0))        # released: a new instance may start

    def test_foreign_active_job_lock_blocks_start(self):
        m = self.manager(fakes.wrapper_script(0))
        fd = os.open(self.ws.p("active-job.lock"), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)               # stands for a worker of another/older instance
        try:
            self.assertTrue(m.is_busy())
            with self.assertRaises(jobs.Busy):
                m.start("run", PKG, "/opt/lean/bin", None, None)
            with self.assertRaises(jobs.Busy):
                m.start("readiness", PKG, "/opt/lean/bin", None, None)
        finally:
            os.close(fd)
        self.assertFalse(m.is_busy())

    def test_active_lock_is_held_by_the_worker_for_its_lifetime(self):
        pidfile = os.path.join(self.t, "c.pid")
        m = self.manager(self.long_script(pidfile))
        jid, child, st = self.start_long(m, pidfile)
        m._simulate_crash()                           # the instance "dies"; the worker lives on
        self.assertTrue(m.is_busy())
        m.cancel(jid)
        self.done(m, jid)
        wait_for(lambda: not m.is_busy(), 10)

    # live orphan on restart -----------------------------------------------------------------------------------------------------
    def orphan_case(self, stop_worker):
        pidfile = os.path.join(self.t, "c.pid")
        m1 = self.manager(self.long_script(pidfile), extra={"synthetic": False})
        jid, child, st = self.start_long(m1, pidfile)
        worker = st["worker_pid"]
        m1._simulate_crash()                          # instance 1 is gone; its worker is now an orphan
        if stop_worker:
            os.kill(worker, signal.SIGSTOP)           # a worker that cannot handle TERM
        m2 = self.manager(fakes.wrapper_script(0), extra={"synthetic": False}, orphan_grace=(1.5 if stop_worker else 8.0))    # starting it recovers
        s = self.assert_consistent_interrupted(m2, jid, "INTERRUPTED_BY_RESTART")
        wait_for(lambda: not alive(child), 10)
        wait_for(lambda: not alive(worker), 10)
        self.assertTrue(os.path.exists(os.path.join(m2.job_dir(jid), "runner-out", "verdict.json")), "partial records preserved")
        if not stop_worker:                           # the worker itself sealed the job from its own observations
            self.assertTrue(s["result"]["artifacts"]["verdict.json"]["present"])
        before = json.dumps(m2.status(jid)["result"], sort_keys=True)
        time.sleep(1.5)                               # nothing may change the result later
        self.assertEqual(json.dumps(m2.status(jid)["result"], sort_keys=True), before)
        self.assertFalse(m2.is_busy())
        self.assertIsNone(m2.active)
        jid2 = m2.start("readiness", PKG, "/opt/lean/bin", None, None)                # a new attempt gets a new id
        self.assertNotEqual(jid, jid2)
        self.done(m2, jid2)

    def test_live_orphan_worker_is_stopped_and_sealed_as_interrupted(self):
        self.orphan_case(stop_worker=False)

    def test_unresponsive_orphan_worker_is_killed_after_the_grace_period(self):
        self.orphan_case(stop_worker=True)

    def test_late_result_cannot_overwrite_a_sealed_result(self):
        jd = self.ws.p("runs", "20260101T000000Z-abcdef12")
        os.makedirs(jd)
        sealed = {"execution": {"status": "APP_FAILURE", "reason": "INTERRUPTED_BY_RESTART"}}
        late = {"execution": {"status": "COMPLETED", "reason": None}, "reproduction": {"status": "MATCH", "badge": True}}
        self.assertTrue(claim_result(jd, sealed))
        self.assertFalse(claim_result(jd, late))
        self.assertEqual(read_json(os.path.join(jd, "result.json")), sealed)
        self.assertEqual([n for n in os.listdir(jd) if n.endswith(".tmp")], [])

    def test_worker_that_loses_the_race_leaves_a_consistent_job(self):
        # worker finishes while the supervisor has already sealed the job: the sealed result stays, the report is regenerated from it
        m = self.manager(good_script("sleep 1"), extra={"synthetic": False})
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        jd = m.job_dir(jid)
        wait_for(lambda: (read_json(os.path.join(jd, "status.json")) or {}).get("child_pgid"))
        sealed = downgrade({"job_id": jid, "kind": "run", "execution": {"status": "COMPLETED"}, "p10": {}, "reproduction": {}}, "APP_FAILURE", "INTERRUPTED_BY_RESTART", "x")
        self.assertTrue(claim_result(jd, sealed))
        wait_for(lambda: not m.is_busy(), 30)
        s = m.status(jid)
        self.assertEqual(s["result"]["execution"], {"status": "APP_FAILURE", "reason": "INTERRUPTED_BY_RESTART"})
        rep = read_json(os.path.join(jd, "app-report.json"))
        self.assertEqual(rep["axes"]["application_execution"]["status"], "APP_FAILURE")
        self.assertFalse(rep["axes"]["accepted_reference_reproduction"]["badge"])

    # shutdown ---------------------------------------------------------------------------------------------------------------------
    def test_shutdown_stops_the_worker_and_its_child(self):
        pidfile = os.path.join(self.t, "c.pid")
        m = self.manager(self.long_script(pidfile), extra={"synthetic": False})
        jid, child, st = self.start_long(m, pidfile)
        m.shutdown()
        wait_for(lambda: not alive(child) and not alive(st["worker_pid"]), 10)
        self.assert_consistent_interrupted(m, jid, "INTERRUPTED_BY_SHUTDOWN")

    def test_shutdown_kills_an_unresponsive_worker(self):
        pidfile = os.path.join(self.t, "c.pid")
        m = self.manager(self.long_script(pidfile), extra={"synthetic": False})
        jid, child, st = self.start_long(m, pidfile)
        os.kill(st["worker_pid"], signal.SIGSTOP)
        m.shutdown(wait=1.5)
        wait_for(lambda: not alive(child) and not alive(st["worker_pid"]), 10)
        self.assert_consistent_interrupted(m, jid, "INTERRUPTED_BY_SHUTDOWN")

    # identity guards --------------------------------------------------------------------------------------------------------------
    def fabricate(self, **status):
        jid = "20260102T000000Z-cafebabe"
        jd = self.ws.p("runs", jid)
        os.makedirs(jd, exist_ok=True)
        write_json_atomic(os.path.join(jd, "status.json"), dict({"state": "RUNNING", "execution": "RUNNING", "kind": "run"}, **status))
        return jid

    def test_recovery_does_not_signal_a_process_with_the_wrong_identity(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        real = proc_start_ticks(bystander.pid)
        # recorded as worker and as child group, but with a start time that does not match: must not be signalled
        jid = self.fabricate(worker_pid=bystander.pid, worker_start_ticks=real + 12345, child_pgid=bystander.pid, child_start_ticks=real + 12345)
        m = self.manager(fakes.wrapper_script(0))
        self.assertEqual(m.status(jid)["result"]["execution"]["reason"], "INTERRUPTED_BY_RESTART")
        self.assertIsNone(bystander.poll(), "a process with a different identity must not be touched")

    def test_worker_identity_requires_the_worker_command_line(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        t = proc_start_ticks(bystander.pid)
        jid = self.fabricate(worker_pid=bystander.pid, worker_start_ticks=t)         # same start time, but not a worker.py for this job
        m = self.manager(fakes.wrapper_script(0), orphan_grace=0.5)
        self.assertEqual(m.status(jid)["result"]["execution"]["status"], "APP_FAILURE")
        self.assertIsNone(bystander.poll(), "ticks alone are not enough to identify a worker")

    def test_recorded_child_group_with_matching_identity_is_cleaned(self):
        leftover = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (leftover.kill(), leftover.wait()))
        jid = self.fabricate(child_pgid=leftover.pid, child_start_ticks=proc_start_ticks(leftover.pid))
        m = self.manager(fakes.wrapper_script(0))
        self.assertEqual(m.status(jid)["result"]["execution"]["reason"], "INTERRUPTED_BY_RESTART")
        wait_for(lambda: leftover.poll() is not None, 10)

    def test_status_and_result_agree_for_every_terminal_job(self):
        m = self.manager(fakes.wrapper_script(1, verdict=fakes.dumps(fakes.good_verdict(outcome="REJECT")), info=fakes.dumps(fakes.good_info())))
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        s = self.done(m, jid)
        self.assertEqual(s["status"]["execution"], s["result"]["execution"]["status"])
        self.assertTrue(os.path.exists(os.path.join(m.job_dir(jid), "result.json")))


class Finding3ExportSnapshot(JobBase):
    def make_job(self, log=b"first line\n"):
        jd = self.ws.p("runs", "20260103T000000Z-0badc0de")
        os.makedirs(os.path.join(jd, "runner-out"), exist_ok=True)
        for rel, data in (("stdout.log", log), ("stderr.log", b"err\n"), ("runner-out/verdict.json", fakes.VERDICT_BYTES), ("result.json", b"{}\n")):
            with open(os.path.join(jd, rel), "wb") as f:
                f.write(data)
        return jd

    @staticmethod
    def check(data):
        """Every member's bytes must hash to its REPORT_SHA256SUMS entry; returns {name: bytes}."""
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            files = {m.name.split("/", 1)[1]: tf.extractfile(m).read() for m in tf if m.isfile()}
        listed = {}
        for line in files["REPORT_SHA256SUMS"].decode().splitlines():
            h, n = line.split("  ", 1)
            listed[n] = h
        assert set(listed) == set(files) - {"REPORT_SHA256SUMS"}, (sorted(listed), sorted(files))
        for n, h in listed.items():
            assert fakes.sha(files[n]) == h, f"{n}: manifest hash does not match the archived bytes"
        info = json.loads(files["export-info.json"])
        for n, meta in info["files"].items():
            assert fakes.sha(files[n]) == meta["sha256"] and len(files[n]) == meta["bytes"], n
        return files

    def test_append_between_hash_and_archive_cannot_desynchronise(self):
        jd = self.make_job()
        log = os.path.join(jd, "stdout.log")

        def append():
            with open(log, "ab") as f:
                f.write(b"appended after the snapshot\n" * 1000)
        data = reports.export_archive(jd, tmp_dir=self.ws.p("tmp"), _after_snapshot=append)
        files = self.check(data)
        self.assertEqual(files["logs/wrapper-stdout.log"], b"first line\n")             # one stable prefix, exactly what was hashed
        self.assertEqual(os.listdir(self.ws.p("tmp")), [], "snapshot temp files are removed")

    def test_export_while_a_log_is_continuously_appended(self):
        jd = self.make_job()
        stop = threading.Event()

        def writer():
            with open(os.path.join(jd, "stdout.log"), "ab", buffering=0) as f:
                for _ in range(2000):                       # bounded: about 8 MiB in total
                    if stop.is_set():
                        break
                    f.write(b"x" * 4096 + b"\n")
                    time.sleep(0.002)
        th = threading.Thread(target=writer, daemon=True)
        th.start()
        self.addCleanup(lambda: (stop.set(), th.join(5)))
        for _ in range(40):
            self.check(reports.export_archive(jd, tmp_dir=self.ws.p("tmp"), partial=True))

    def test_export_of_a_running_job_through_the_manager_is_marked_partial(self):
        pidfile = os.path.join(self.t, "c.pid")
        m = self.manager(fakes.wrapper_script(0, body=f'echo started; sleep 300 &\necho $! > {pidfile}\nwait'))
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        wait_for(lambda: os.path.exists(pidfile))
        wait_for(lambda: "started" in m.events(jid)["stdout"]["text"])
        files = self.check(m.export(jid))
        self.assertFalse(json.loads(files["export-info.json"])["job_had_final_result"])
        self.assertIn(b"started", files["logs/wrapper-stdout.log"])
        m.cancel(jid)
        self.done(m, jid)
        self.assertTrue(json.loads(self.check(m.export(jid))["export-info.json"])["job_had_final_result"])

    def test_symlinked_and_non_regular_artifacts_are_not_exported(self):
        jd = self.make_job()
        os.remove(os.path.join(jd, "stderr.log"))
        os.symlink("/etc/passwd", os.path.join(jd, "stderr.log"))
        os.remove(os.path.join(jd, "result.json"))
        os.mkdir(os.path.join(jd, "result.json"))
        files = self.check(reports.export_archive(jd, tmp_dir=self.ws.p("tmp")))
        self.assertNotIn("logs/wrapper-stderr.log", files)
        self.assertNotIn("result.json", files)


if __name__ == "__main__":
    unittest.main()
