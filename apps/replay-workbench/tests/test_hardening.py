"""Regression tests for the v0.1.1 findings: swallowed write errors, process/instance control, export snapshots.
All runs here are synthetic (StubModule); a stub run is never an offline P10 run."""
import fcntl
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time
import unittest
from unittest import mock

from . import fakes
from .test_jobs import JobBase, PKG, alive, read_text, wait_for
from workbench import jobs, reports
from workbench import util
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
        # record_expected=False: the child is stopped at an arbitrary point, so a partial or absent record is legitimate; the application does not touch it
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
        self.assert_failed_without_promotion(m, jid, s, "LOG_WRITE_FAILED", record_expected=False)

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
        m2 = self.manager(fakes.wrapper_script(0), extra={"synthetic": False}, orphan_grace=(1.5 if stop_worker else 15.0))    # starting it recovers
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

    @unittest.skipUnless(util.proc_identity_available(), "start time checks need a readable /proc")
    def test_recovery_does_not_signal_a_process_with_the_wrong_identity(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        real = proc_start_ticks(bystander.pid)
        # recorded as worker and as child group, but with a start time that does not match: must not be signalled
        jid = self.fabricate(worker_pid=bystander.pid, worker_start_ticks=real + 12345, child_pgid=bystander.pid, child_start_ticks=real + 12345)
        m = self.manager(fakes.wrapper_script(0))
        self.assertEqual(m.status(jid)["result"]["execution"]["reason"], "INTERRUPTED_BY_RESTART")
        self.assertIsNone(bystander.poll(), "a process with a different identity must not be touched")

    @unittest.skipUnless(util.proc_identity_available(), "start time and command line checks need a readable /proc")
    def test_worker_identity_requires_the_worker_command_line(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        t = proc_start_ticks(bystander.pid)
        jid = self.fabricate(worker_pid=bystander.pid, worker_start_ticks=t)         # same start time, but not a worker.py for this job
        fd = os.open(util.worker_lock_path(self.ws.p("runs", jid)), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)                                               # and even with a held worker lock
        self.addCleanup(os.close, fd)
        m = self.manager(fakes.wrapper_script(0), orphan_grace=0.5)
        self.assertEqual(m.status(jid)["result"]["execution"]["status"], "APP_FAILURE")
        self.assertIsNone(bystander.poll(), "ticks and lock alone are not enough to identify a worker on a host with /proc")

    def test_pid_without_the_worker_lock_is_never_a_worker(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        jid = self.fabricate(worker_pid=bystander.pid, worker_start_ticks=proc_start_ticks(bystander.pid))
        self.assertFalse(util.is_worker_process(bystander.pid, proc_start_ticks(bystander.pid), self.ws.p("runs", jid)))
        with mock.patch.object(util, "PROC_ENABLED", False):
            self.assertFalse(util.is_worker_process(bystander.pid, None, self.ws.p("runs", jid)), "no /proc: still needs the lock proof")

    @unittest.skipUnless(util.proc_identity_available(), "start time checks need a readable /proc")
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


class NoProcHost(Finding2ProcessControl):
    """The same process-control scenarios on a host where /proc cannot be read: identity then rests on the worker/child locks."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(util, "PROC_ENABLED", False)
        p.start()
        self.addCleanup(p.stop)
        self.assertFalse(util.proc_identity_available())

    def test_worker_identity_requires_the_worker_command_line(self):
        self.skipTest("command line checks need /proc")

    def test_recorded_child_group_with_matching_identity_is_cleaned(self):
        self.skipTest("start time checks need /proc; see test_child_group_held_by_the_child_lock_is_cleaned_without_proc")

    def test_recovery_does_not_signal_a_process_with_the_wrong_identity(self):
        self.skipTest("wrong start time cannot be detected without /proc; the lock proof is tested in test_pid_without_the_worker_lock_is_never_a_worker")


class ChildLockIdentity(JobBase):
    def test_child_group_held_by_the_child_lock_is_cleaned_without_proc(self):
        jid = "20260106T000000Z-c0ffee00"
        jd = self.ws.p("runs", jid)
        os.makedirs(jd)
        lock = util.try_lock(util.child_lock_path(jd))
        leftover = subprocess.Popen(["sleep", "60"], start_new_session=True, pass_fds=(lock,))     # the group inherits the lock, as in the worker
        os.close(lock)
        self.addCleanup(lambda: (leftover.kill(), leftover.wait()))
        write_json_atomic(os.path.join(jd, "status.json"), {"state": "RUNNING", "execution": "RUNNING", "kind": "run",
                                                            "child_pgid": leftover.pid, "child_start_ticks": None})
        with mock.patch.object(util, "PROC_ENABLED", False):
            m = self.manager(fakes.wrapper_script(0))
            self.assertEqual(m.status(jid)["result"]["execution"]["reason"], "INTERRUPTED_BY_RESTART")
        wait_for(lambda: leftover.poll() is not None, 10)

    def test_released_child_lock_means_the_group_id_is_not_signalled(self):
        jid = "20260106T000000Z-c0ffee01"
        jd = self.ws.p("runs", jid)
        os.makedirs(jd)
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)       # unrelated process whose pid is recorded, no lock held
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        with mock.patch.object(util, "PROC_ENABLED", False):
            self.assertFalse(util.group_signal_ok(jd, bystander.pid, None))
            self.assertFalse(util.kill_group_guarded(jd, bystander.pid, None, signal.SIGKILL))
        self.assertIsNone(bystander.poll())

    def test_real_worker_publishes_proof_of_life_locks(self):
        pidfile = os.path.join(self.t, "c.pid")
        m = self.manager(fakes.wrapper_script(0, body=f"sleep 300 &\necho $! > {pidfile}\nwait", **GOOD))
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        jd = m.job_dir(jid)
        wait_for(lambda: os.path.exists(pidfile))
        wait_for(lambda: util.lock_held(util.worker_lock_path(jd)))
        wait_for(lambda: util.lock_held(util.child_lock_path(jd)))
        m.cancel(jid)
        self.done(m, jid)
        wait_for(lambda: not util.lock_held(util.worker_lock_path(jd)) and not util.lock_held(util.child_lock_path(jd)), 10)

    def test_worker_refuses_to_run_a_job_that_was_already_interrupted(self):
        m = self.manager(fakes.wrapper_script(0, verdict=fakes.VERDICT_BYTES, body="touch " + os.path.join(self.t, "ran")), extra={"synthetic": False})
        m.close()
        jid = "20260106T000000Z-0ff1ce00"
        jd = self.ws.p("runs", jid)
        os.makedirs(jd)
        spec = {"job_id": jid, "kind": "run", "package_id": PKG, "managed_dir": self.ws.p("packages", PKG), "workspace": self.ws.root,
                "host_config": {"lean_bin": "/opt/lean/bin", "allowed_signers": None}, "module_ref": "tests.fakes:make_module",
                "extra_sys_path": [fakes.APP, self.cfgdir], "deadline_s": 60.0, "log_limit": 1 << 20, "created": "x",
                "module_description": m.module.describe(), "profile": m.module.profile}
        write_json_atomic(os.path.join(jd, "job.json"), spec)
        write_json_atomic(os.path.join(jd, "status.json"), {"state": "RUNNING", "execution": "RUNNING", "kind": "run"})
        self.assertEqual(register_interrupt(jd, "INTERRUPTED_BY_RESTART"), "registered")
        p = subprocess.run([sys.executable, "-I", "-B", jobs.WORKER_PY, jd], capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 6)
        self.assertFalse(os.path.exists(os.path.join(self.t, "ran")), "an interrupted job must not start its wrapper")


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


# --- v0.1.2: interruption racing with final-result publication ---------------------------------------------------------------------
import random
from unittest import mock

from workbench import worker as worker_mod
from workbench.util import SealLock, publish_result, register_interrupt


class Finding4SealRace(JobBase):
    """Rule under test: whichever of {interruption registration, result publication} takes the per-job seal lock first wins.
    Worker first: the job finished before the interruption; result, report and status say COMPLETED and the registration returns 'too_late'.
    Interruption first: the worker converts its result to an application failure and writes the report for that result. Never a badge after
    an interruption was registered."""

    def worker_with_result(self, jid="20260104T000000Z-5ea15ea1", extra=None, wrapper_exit=0):
        cfg_extra = dict({"synthetic": False}, **(extra or {}))
        m = self.manager(fakes.wrapper_script(0), extra=cfg_extra)
        m.close()                                              # we drive the worker in-process; no manager needed
        jd = self.ws.p("runs", jid)
        os.makedirs(os.path.join(jd, "runner-out"))
        for name, data in (("verdict.json", fakes.VERDICT_BYTES), ("run-info.json", fakes.dumps(fakes.good_info()))):
            with open(os.path.join(jd, "runner-out", name), "wb") as f:
                f.write(data)
        mod = m.module
        spec = {"job_id": jid, "kind": "run", "package_id": PKG, "managed_dir": self.ws.p("packages", PKG), "workspace": self.ws.root,
                "host_config": {"lean_bin": "/opt/lean/bin", "allowed_signers": None}, "module_ref": "tests.fakes:make_module",
                "extra_sys_path": [fakes.APP, self.cfgdir], "deadline_s": 600.0, "log_limit": 1 << 20, "created": "2026-10-09T00:00:00Z",
                "module_description": mod.describe(), "profile": mod.profile}
        write_json_atomic(os.path.join(jd, "job.json"), spec)
        write_json_atomic(os.path.join(jd, "status.json"), {"state": "RUNNING", "execution": "RUNNING", "kind": "run"})
        w = worker_mod.Worker(jd)
        col = mod.collect({"wrapper_exit": wrapper_exit}, os.path.join(jd, "runner-out"), self.ws.p("packages", PKG))
        ex = col.pop("execution")
        res = w.finish(ex["status"], ex["reason"], col)
        self.assertTrue(res["reproduction"]["badge"], "sanity: an uninterrupted result of this job would carry the badge")
        return w, jd, res

    def raw_unchanged(self, jd):
        with open(os.path.join(jd, "runner-out", "verdict.json"), "rb") as f:
            self.assertEqual(f.read(), fakes.VERDICT_BYTES)

    def assert_agree(self, jd, final, status, badge):
        """result.json, app-report.json (and the in-memory result) describe the same decision."""
        on_disk = read_json(os.path.join(jd, "result.json"))
        self.assertEqual(on_disk["execution"], final["execution"])
        self.assertEqual(on_disk["reproduction"]["badge"], badge)
        self.assertEqual(final["execution"]["status"], status)
        rep = read_json(os.path.join(jd, "app-report.json"))
        self.assertEqual(rep["axes"]["application_execution"], on_disk["execution"])
        self.assertEqual(rep["axes"]["accepted_reference_reproduction"]["badge"], badge)
        self.assertEqual(rep["axes"]["p10_runner_outcome"].get("outcome"), on_disk["p10"].get("outcome"))
        self.raw_unchanged(jd)

    # --- the reported sequence --------------------------------------------------------------------------------------------------
    def test_interruption_during_report_finalization_is_honoured(self):
        w, jd, res = self.worker_with_result()
        calls, orig = [], reports.finalize

        def finalize(job_dir, spec, r):
            calls.append(r["execution"]["status"])
            if len(calls) == 1:                                # shutdown registers and the worker gets TERM while the report is written
                with open(os.path.join(job_dir, "interrupt.json"), "w") as f:
                    json.dump({"reason": "INTERRUPTED_BY_SHUTDOWN"}, f)
                w.handle_term(signal.SIGTERM, None)
            return orig(job_dir, spec, r)
        with mock.patch.object(reports, "finalize", finalize):
            final, won = w.publish(res)
        self.assertTrue(won)
        self.assertEqual(calls, ["COMPLETED", "APP_FAILURE"], "the report is rewritten for the decision that is published")
        self.assert_agree(jd, final, "APP_FAILURE", badge=False)
        self.assertEqual(final["execution"]["reason"], "INTERRUPTED_BY_SHUTDOWN")
        self.assertIsNone(final["p10"]["outcome"])
        self.assertEqual(final["reproduction"]["status"], "NOT_EVALUATED")

    def test_same_sequence_through_worker_main(self):
        # mirrors the reproduction: marker written and handle_term() called from a finalization callback, then Worker.main()
        m = self.manager(good_script(), extra={"synthetic": False})
        m.close()
        jid = "20260104T000000Z-6a1ec0de"
        jd = self.ws.p("runs", jid)
        os.makedirs(jd)
        mod = m.module
        spec = {"job_id": jid, "kind": "run", "package_id": PKG, "managed_dir": self.ws.p("packages", PKG), "workspace": self.ws.root,
                "host_config": {"lean_bin": "/opt/lean/bin", "allowed_signers": None}, "module_ref": "tests.fakes:make_module",
                "extra_sys_path": [fakes.APP, self.cfgdir], "deadline_s": 600.0, "log_limit": 1 << 20, "created": "x",
                "module_description": mod.describe(), "profile": mod.profile}
        write_json_atomic(os.path.join(jd, "job.json"), spec)
        write_json_atomic(os.path.join(jd, "status.json"), {"state": "RUNNING", "execution": "RUNNING", "kind": "run"})
        w = worker_mod.Worker(jd)
        olds = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in olds.items()])
        n, orig = [0], reports.finalize

        def finalize(job_dir, sp, r):
            n[0] += 1
            if n[0] == 1:
                with open(os.path.join(job_dir, "interrupt.json"), "w") as f:
                    json.dump({"reason": "INTERRUPTED_BY_SHUTDOWN"}, f)
                w.handle_term(signal.SIGTERM, None)
            return orig(job_dir, sp, r)
        with mock.patch.object(reports, "finalize", finalize):
            code = w.main()
        res = read_json(os.path.join(jd, "result.json"))
        self.assertEqual(code, 0)
        self.assertEqual(res["execution"], {"status": "APP_FAILURE", "reason": "INTERRUPTED_BY_SHUTDOWN"})
        self.assertFalse(res["reproduction"]["badge"])
        self.assertEqual(read_json(os.path.join(jd, "status.json"))["execution"], "APP_FAILURE")
        self.assertEqual(read_json(os.path.join(jd, "app-report.json"))["axes"]["application_execution"]["status"], "APP_FAILURE")
        self.raw_unchanged(jd)

    def test_stop_request_during_finalization_wins_without_marker(self):
        w, jd, res = self.worker_with_result()
        orig = reports.finalize
        fired = []

        def finalize(job_dir, spec, r):
            if not fired:
                fired.append(1)
                w.handle_term(signal.SIGTERM, None)            # user Stop / external TERM, no marker
            return orig(job_dir, spec, r)
        with mock.patch.object(reports, "finalize", finalize):
            final, won = w.publish(res)
        self.assert_agree(jd, final, "CANCELLED", badge=False)
        self.assertFalse(os.path.exists(os.path.join(jd, "interrupt.json")))

    # --- the two orders, deterministic ------------------------------------------------------------------------------------------
    def test_worker_first_the_late_interruption_loses_and_everything_says_completed(self):
        w, jd, res = self.worker_with_result()
        orig = reports.finalize
        out, started = {}, threading.Event()

        def sup():
            started.set()
            out["r"] = register_interrupt(jd, "INTERRUPTED_BY_SHUTDOWN")          # blocks on the seal lock held by the worker

        t = threading.Thread(target=sup)

        def finalize(job_dir, spec, r):
            t.start()
            started.wait(5)
            time.sleep(0.4)
            self.assertTrue(t.is_alive(), "registration must wait for the worker's seal lock, not slip in during finalization")
            self.assertFalse(os.path.exists(os.path.join(job_dir, "interrupt.json")))
            return orig(job_dir, spec, r)
        with mock.patch.object(reports, "finalize", finalize):
            final, won = w.publish(res)
        t.join(10)
        self.assertEqual(out["r"], "too_late")
        self.assertFalse(os.path.exists(os.path.join(jd, "interrupt.json")))
        self.assert_agree(jd, final, "COMPLETED", badge=True)

    def test_interruption_first_the_worker_converts_its_result(self):
        w, jd, res = self.worker_with_result()
        self.assertEqual(register_interrupt(jd, "INTERRUPTED_BY_RESTART"), "registered")
        final, won = w.publish(res)
        self.assertTrue(won)
        self.assert_agree(jd, final, "APP_FAILURE", badge=False)
        self.assertEqual(final["execution"]["reason"], "INTERRUPTED_BY_RESTART")

    def test_forced_marker_when_the_lock_holder_is_unresponsive_is_still_honoured(self):
        w, jd, res = self.worker_with_result()
        with SealLock(jd):                                                         # a stopped worker holds the lock
            self.assertEqual(register_interrupt(jd, "INTERRUPTED_BY_RESTART", timeout=0.2), "forced")
        self.assertTrue(os.path.exists(os.path.join(jd, "interrupt.json")))
        final, _ = w.publish(res)                                                  # when it resumes it sees the marker
        self.assert_agree(jd, final, "APP_FAILURE", badge=False)

    def test_supervisor_publication_and_worker_publication_are_exclusive(self):
        w, jd, res = self.worker_with_result()
        sealed = downgrade(res, "APP_FAILURE", "INTERRUPTED_BY_RESTART", "x")
        self.assertTrue(publish_result(jd, sealed))
        final, won = w.publish(res)                                                # the worker arrives late
        self.assertFalse(won)
        self.assertEqual(read_json(os.path.join(jd, "result.json"))["execution"]["status"], "APP_FAILURE")

    def test_concurrent_interruption_and_publication_always_agree(self):
        orig_dir = self.ws.p("runs")
        seen = {"too_late": 0, "registered": 0}
        w0, jd0, res0 = self.worker_with_result()

        def quick_finalize(job_dir, spec, r):
            write_json_atomic(os.path.join(job_dir, "app-report.json"), {"axes": {"application_execution": r["execution"],
                              "accepted_reference_reproduction": {"badge": r["reproduction"]["badge"]}, "p10_runner_outcome": r["p10"]}})
        rnd = random.Random(12345)
        with mock.patch.object(reports, "finalize", quick_finalize):
            for i in range(120):
                jid = f"20260105T0000{i // 60:02d}Z-{i:08x}"
                jd = os.path.join(orig_dir, jid)
                os.makedirs(jd)
                with open(os.path.join(jd, "job.json"), "w") as f:
                    f.write("{}")
                w = worker_mod.Worker.__new__(worker_mod.Worker)                    # light worker bound to this directory
                w.dir, w.spec, w.cancel = jd, w0.spec, threading.Event()
                res = dict(res0, job_id=jid)
                barrier, out = threading.Barrier(2), {}
                d1, d2 = rnd.random() * 0.003, rnd.random() * 0.003

                def sup():
                    barrier.wait()
                    time.sleep(d1)
                    out["reg"] = register_interrupt(jd, "INTERRUPTED_BY_SHUTDOWN")

                def wrk():
                    barrier.wait()
                    time.sleep(d2)
                    out["fin"], out["won"] = w.publish(res)
                ts = [threading.Thread(target=sup), threading.Thread(target=wrk)]
                [t.start() for t in ts]
                [t.join(30) for t in ts]
                on_disk = read_json(os.path.join(jd, "result.json"))
                marker = os.path.exists(os.path.join(jd, "interrupt.json"))
                rep = read_json(os.path.join(jd, "app-report.json"))
                self.assertTrue(out["won"])
                self.assertEqual(on_disk["execution"], out["fin"]["execution"])
                self.assertEqual(rep["axes"]["application_execution"], on_disk["execution"], i)
                if out["reg"] == "too_late":
                    seen["too_late"] += 1
                    self.assertFalse(marker, i)
                    self.assertEqual((on_disk["execution"]["status"], on_disk["reproduction"]["badge"]), ("COMPLETED", True), i)
                else:
                    seen["registered"] += 1
                    self.assertEqual(out["reg"], "registered")
                    self.assertTrue(marker, i)
                    self.assertEqual((on_disk["execution"]["status"], on_disk["reproduction"]["badge"]), ("APP_FAILURE", False), i)
                    self.assertFalse(rep["axes"]["accepted_reference_reproduction"]["badge"])
        self.assertGreater(seen["too_late"] + seen["registered"], 100)

    # --- real worker process, real shutdown, finalization held open -----------------------------------------------------------------
    def test_shutdown_during_finalization_in_a_real_worker_is_consistent(self):
        m = self.manager(good_script(), extra={"synthetic": False, "sabotage": {"profile_fifo": True}})
        jid = m.start("run", PKG, "/opt/lean/bin", None, None)
        jd = m.job_dir(jid)
        wait_for(lambda: (read_json(os.path.join(jd, "status.json")) or {}).get("phase") == "sealing", 60)
        out = {}
        sd = threading.Thread(target=lambda: (m.shutdown(wait=20), out.update(done=True)))
        sd.start()                                      # blocks in register_interrupt: the worker is inside finalization holding the seal lock
        time.sleep(0.8)
        self.assertTrue(sd.is_alive())
        self.assertFalse(os.path.exists(os.path.join(jd, "interrupt.json")), "registration must wait for the seal lock")
        with open(os.path.join(jd, "profile.json"), "rb") as f:       # let finalization proceed
            f.read()
        sd.join(30)
        self.assertTrue(out.get("done"))
        s = wait_for(lambda: (lambda x: x if x and x["result"] else None)(m.status(jid)), 30)
        r = s["result"]
        marker = os.path.exists(os.path.join(jd, "interrupt.json"))
        self.assertFalse(marker)                        # the worker published first
        self.assertEqual((r["execution"]["status"], r["reproduction"]["badge"]), ("COMPLETED", True))
        self.assertEqual((s["status"]["state"], s["status"]["execution"]), ("DONE", "COMPLETED"))
        self.assertEqual(read_json(os.path.join(jd, "app-report.json"))["axes"]["application_execution"]["status"], "COMPLETED")
        self.raw_unchanged(jd)
        wait_for(lambda: not m.is_busy(), 10)


if __name__ == "__main__":
    unittest.main()
