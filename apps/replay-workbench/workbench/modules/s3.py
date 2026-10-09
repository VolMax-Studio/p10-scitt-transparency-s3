"""S3 module: shipped profile, mechanical readiness, fixed wrapper command and structural result collection.

Module interface (blueprint section 10): describe(), inspect(), command(), collect().
No P10 rule, COSE/CBOR/Lean/transcript logic or reason-token list lives here.
"""
import hashlib
import json
import os
import re
import shutil
import sys

from .. import records as R

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE_PATH = os.path.join(APP_DIR, "profiles", "s3-accepted-rev2.json")

# Exit status meanings of the (unchanged) wrapper. These are NOT P10 outcomes.
WRAPPER_EXIT_MEANING = {
    0: "full replay success",
    1: "failed replay or comparison",
    2: "prerequisite or output refusal (runner not started)",
    3: "wrapper test mode (invalid for a real run)",
}
HOST_PASSTHROUGH = ("HOME", "USER", "LOGNAME", "LANG", "RUSTUP_HOME", "CARGO_HOME")
SAFE_PATH = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")
REQUIRED_TOOLS = ("python3", "git", "unshare", "rustc", "sha256sum", "cmp", "tar", "bash")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def rec(rid, label, status, detail="", **extra):
    """Readiness record. status: pass | fail | warn | info | not_checked."""
    d = {"id": rid, "label": label, "status": status, "detail": str(detail)[:2000]}
    d.update(extra)
    return d


class S3Module:
    name = "s3"

    def __init__(self, profile, synthetic=False, profile_bytes=None):
        self.profile = profile
        self.synthetic = bool(synthetic)
        self.profile_sha256 = hashlib.sha256(profile_bytes if profile_bytes is not None
                                             else json.dumps(profile, sort_keys=True).encode()).hexdigest()

    @classmethod
    def shipped(cls):
        with open(PROFILE_PATH, "rb") as f:
            raw = f.read()
        return cls(json.loads(raw), synthetic=False, profile_bytes=raw)

    # ---- describe ---------------------------------------------------------------------------------------------------------
    def describe(self):
        p = self.profile
        return {"module": self.name, "profile_id": p["profile_id"], "profile_sha256": self.profile_sha256,
                "description": p["description"], "archive_name": p["archive"]["name"], "archive_sha256": p["archive"]["sha256"],
                "synthetic": self.synthetic,
                "execution_kind": ("SYNTHETIC TEST RUN - not an offline P10 run" if self.synthetic
                                   else "Offline P10 replay of the approved S3 rev2 package"),
                "limits": p["limits"], "wrapper_sha256": p["wrapper"]["sha256"]}

    # ---- paths ------------------------------------------------------------------------------------------------------------
    def pkg(self, package_root, *rel):
        return os.path.join(package_root, *rel)

    def package_root(self, managed_dir):
        return os.path.join(managed_dir, self.profile["archive"]["root"])

    # ---- environment ------------------------------------------------------------------------------------------------------
    def build_env(self, host_config, tmpdir, host_env=None):
        """Deliberately constructed environment: nothing is inherited except an allowlist of host/toolchain locations."""
        host_env = os.environ if host_env is None else host_env
        env = {k: host_env[k] for k in HOST_PASSTHROUGH if host_env.get(k)}
        home = env.get("HOME", "")
        path = list(SAFE_PATH)
        extra = []
        cargo = os.path.join(env.get("CARGO_HOME") or (home and os.path.join(home, ".cargo")) or "", "bin")
        if cargo and os.path.isdir(cargo):
            extra.append(cargo)
        rc = shutil.which("rustc", path=host_env.get("PATH", ""))
        if rc and os.path.dirname(rc) not in path + extra:
            extra.append(os.path.dirname(rc))
        env["PATH"] = ":".join(extra + path)
        env["LC_ALL"] = "C.UTF-8"
        env["TMPDIR"] = tmpdir
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["RUSTUP_AUTO_INSTALL"] = "0"
        env["LEAN_BIN"] = host_config["lean_bin"]
        if host_config.get("allowed_signers"):
            env["ALLOWED_SIGNERS"] = host_config["allowed_signers"]
        return env

    def probe_namespace(self, ctx, env):
        for flag in ("-n", "-rn"):
            r = ctx.run(["unshare", flag, "true"], env=env, timeout=20)
            if r.rc == 0:
                return flag, ""
        return None, (r.stderr or r.stdout or f"exit {r.rc}")[-300:]

    # ---- inspect (readiness) ----------------------------------------------------------------------------------------------
    def inspect(self, managed_dir, host_config, ctx):
        p, out = self.profile, []
        root = self.package_root(managed_dir)
        env = self.build_env(host_config, ctx.tmpdir)
        add = out.append
        if not os.path.isdir(root):
            return [rec("package", "Managed package present", "fail", f"{root} is missing")]
        add(rec("package", "Managed package present", "pass", "extracted from the approved archive"))

        # 1. commands, Rust, Lean
        for t in REQUIRED_TOOLS:
            where = shutil.which(t, path=env["PATH"])
            add(rec("tool-" + t, f"Command {t}", "pass" if where else "fail", where or "not found on the application PATH"))
        add(rec("tool-ssh-keygen", "Command ssh-keygen (optional signature check)", "info" if shutil.which("ssh-keygen", path=env["PATH"]) else "warn",
                shutil.which("ssh-keygen", path=env["PATH"]) or "not found; tag signatures cannot be verified"))
        lb = host_config.get("lean_bin", "")
        ok_lb = bool(lb) and os.path.isabs(lb) and os.path.isfile(os.path.join(lb, "lean")) and os.access(os.path.join(lb, "lean"), os.X_OK) \
            and os.path.isfile(os.path.join(lb, "lake")) and os.access(os.path.join(lb, "lake"), os.X_OK)
        add(rec("lean-bin", "Lean bin directory (absolute path with lean and lake)", "pass" if ok_lb else "fail",
                lb if ok_lb else f"not an absolute directory containing executable lean and lake: {lb!r}"))
        spec = self.pkg(root, "repo", "spike", "s3-entry")
        r = ctx.run(["rustc", "-V"], env=env, cwd=spec, timeout=60) if os.path.isdir(spec) else None
        want = "rustc " + p["rust_version"] + " "
        good = bool(r) and r.rc == 0 and r.stdout.startswith(want)
        add(rec("rust", f"Rust {p['rust_version']} inside spike/s3-entry", "pass" if good else "fail", (r.stdout.strip() if r and r.rc == 0 else (r.stderr.strip() if r else "spike/s3-entry missing"))[:300]))

        # 2. namespace method
        flag, why = self.probe_namespace(ctx, env)
        add(rec("netns", "Network namespace launch method", "pass" if flag else "fail",
                f"unshare {flag}" if flag else "unprivileged network namespaces unavailable (host setup problem; the application does not change host policy): " + why,
                method=flag))

        # 3. checksum files, decided by exit status
        for s in p["sumfiles"]:
            d = os.path.normpath(os.path.join(root, s["dir"]))
            f = os.path.join(d, s["file"])
            if not os.path.isfile(f):
                add(rec("sum-" + s["label"], f"{s['label']} checksum list", "fail", f"{s['file']} missing"))
                continue
            with open(f, "rb") as fh:
                listed = sum(1 for line in fh if line.strip())
            c = ctx.run(["sha256sum", "-c", s["file"], "--quiet"], env=env, cwd=d, timeout=900)
            if c.rc == 0:
                add(rec("sum-" + s["label"], f"{s['label']} checksum list", "pass", f"sha256sum -c exit 0; {listed} listed paths read", listed=listed))
            else:
                msg = (c.stdout + c.stderr).strip()[-600:]
                add(rec("sum-" + s["label"], f"{s['label']} checksum list", "fail",
                        f"sha256sum -c exited with status {c.rc}" + (f": {msg}" if msg else " (it printed nothing)"), listed=listed, exit=c.rc))

        # 4. git state, tags, anchor, wrapper/source/binary hashes
        repo = self.pkg(root, "repo")
        g = lambda *a, cwd=repo: ctx.run(["git", *a], env=env, cwd=cwd, timeout=120)
        h = g("rev-parse", "HEAD")
        add(rec("head-s3", "S3 package HEAD", "pass" if h.rc == 0 and h.stdout.strip() == p["s3_package_head"] else "fail", f"{h.stdout.strip() or h.stderr.strip()} (want {p['s3_package_head']})"))
        st = g("status", "--porcelain", "--untracked-files=no")
        add(rec("clean-s3", "S3 tracked files unmodified", "pass" if st.rc == 0 and not st.stdout.strip() else "fail", "clean" if st.rc == 0 and not st.stdout.strip() else (st.stdout or st.stderr)[:300]))
        for name, want_ids in p["tags"].items():
            o = g("rev-parse", name)
            t = g("rev-parse", name + "^{commit}")
            good = o.rc == 0 and o.stdout.strip() == want_ids["object"] and t.rc == 0 and t.stdout.strip() == want_ids["target"]
            add(rec("tag-" + name, f"Tag {name} object and peeled target", "pass" if good else "fail", f"{o.stdout.strip()} -> {t.stdout.strip()}"))
            body = g("cat-file", "-p", name)
            has_sig = body.rc == 0 and "BEGIN SSH SIGNATURE" in body.stdout
            add(rec("sigpresent-" + name, f"Tag {name} carries a signature block", "pass" if has_sig else "fail", "signature block present (validity is a separate row)" if has_sig else "no signature block"))
        sig = host_config.get("allowed_signers")
        for name in p["tags"]:
            if sig:
                v = g("-c", "gpg.ssh.allowedSignersFile=" + sig, "verify-tag", name)
                add(rec("sigcheck-" + name, f"Tag {name} signature against supplied public allowed-signers file", "pass" if v.rc == 0 else "fail",
                        "verifies" if v.rc == 0 else "does not verify: " + (v.stderr or v.stdout)[-300:]))
            else:
                add(rec("sigcheck-" + name, f"Tag {name} signature", "not_checked", "Signature not checked (no allowed-signers file supplied)"))
        for dep, want_head in p["dependencies"].items():
            dd = self.pkg(root, "deps", dep)
            hh = g("rev-parse", "HEAD", cwd=dd) if os.path.isdir(dd) else None
            ss = g("status", "--porcelain", "--untracked-files=no", cwd=dd) if hh else None
            good = bool(hh) and hh.rc == 0 and hh.stdout.strip() == want_head and ss.rc == 0 and not ss.stdout.strip()
            add(rec("dep-" + dep, f"{dep.upper()} checkout at pinned commit and clean", "pass" if good else "fail",
                    f"{(hh.stdout.strip() if hh else 'missing')} (want {want_head})"))
        try:
            with open(self.pkg(root, p["anchor_file"]), "r", encoding="utf-8") as af:
                anchor = af.read().strip()
        except OSError:
            anchor = None
        add(rec("anchor", "Capture anchor", "pass" if anchor == p["anchor_sha256"] else "fail", f"{anchor} (want {p['anchor_sha256']})"))
        for rel, want_sha in [(p["wrapper"]["path"], p["wrapper"]["sha256"])] + list(p["files"].items()):
            try:
                got = sha256_file(self.pkg(root, *rel.split("/")))
            except OSError as e:
                got = "unreadable " + type(e).__name__
            add(rec("sha-" + rel, f"SHA-256 of {rel}", "pass" if got == want_sha else "fail", f"{got} (want {want_sha})"))
        refs = []
        for rel in p["references"]:
            try:
                refs.append(sha256_file(self.pkg(root, *rel.split("/"))))
            except OSError:
                refs.append(None)
        add(rec("accepted-reference", "Accepted verdict reference files (hashed only; not passed to the runner)",
                "pass" if all(x == p["accepted_verdict_sha256"] for x in refs) else "fail", ", ".join(str(x) for x in refs)))

        # preflight (existing, hash-verified script) run inside an offline subprocess
        pf = self.pkg(root, "repo", "spike", "host", "preflight.py")
        hashes_ok = all(x["status"] == "pass" for x in out if x["id"] == "sha-repo/spike/host/preflight.py")
        if flag and ok_lb and hashes_ok:
            outp = os.path.join(ctx.tmpdir, "preflight-readiness.json")
            argv = ["unshare", flag, "--", "python3", "-B", pf, "--s1", self.pkg(root, "deps", "s1"), "--s2a", self.pkg(root, "deps", "s2a"),
                    "--s2b", self.pkg(root, "deps", "s2b"), "--lean-bin-dir", lb, "--out", outp]
            pr = ctx.run(argv, env=env, cwd=repo, timeout=600)
            raw, obj, prob = R.read_record(outp)
            if prob or not isinstance(obj, dict) or not isinstance(obj.get("checks"), list):
                add(rec("preflight", "Existing preflight.py (offline)", "fail", f"exit {pr.rc}; report {prob or 'malformed'}: {(pr.stderr or pr.stdout)[-300:]}"))
            else:
                rows = [c for c in obj["checks"] if isinstance(c, dict)][:100]
                bad = [c for c in rows if c.get("required") is True and c.get("ok") is not True]
                add(rec("preflight", "Existing preflight.py (offline)", "fail" if bad or pr.rc != 0 else "pass",
                        f"{len(rows)} checks, {len(bad)} required failed, exit {pr.rc}",
                        rows=[{"id": str(c.get("id")), "ok": c.get("ok") is True, "required": c.get("required") is True, "detail": str(c.get("detail"))[:300]} for c in rows]))
        else:
            add(rec("preflight", "Existing preflight.py (offline)", "not_checked", "skipped: namespace, Lean directory or preflight.py hash prerequisite not met"))

        # 6. resources (observations, not P10 evidence)
        try:
            du = shutil.disk_usage(ctx.workspace)
            add(rec("disk", "Free disk in workspace", "info", f"{du.free / 2**30:.1f} GiB free of {du.total / 2**30:.1f} GiB", free_bytes=du.free))
        except OSError as e:
            add(rec("disk", "Free disk in workspace", "warn", type(e).__name__))
        mem = None
        try:
            with open("/proc/meminfo") as mf:
                for line in mf:
                    if line.startswith("MemAvailable:"):
                        mem = int(line.split()[1]) * 1024
        except (OSError, ValueError):
            pass
        add(rec("memory", "Available memory (observation; the first replay builds Lean helpers and can be memory-hungry)", "info" if mem else "warn",
                f"{mem / 2**30:.1f} GiB available" if mem else "unknown", available_bytes=mem))
        return out

    @staticmethod
    def blocking(records):
        return [r for r in records if r["status"] == "fail"]

    # ---- command ----------------------------------------------------------------------------------------------------------
    def command(self, managed_dir, host_config, fresh_output, ctx):
        root = self.package_root(managed_dir)
        if os.path.exists(fresh_output):
            raise RuntimeError("runner output directory must not exist")
        env = self.build_env(host_config, ctx.tmpdir)
        flag, why = self.probe_namespace(ctx, env)
        if not flag:
            raise RuntimeError("network namespaces unavailable: " + why)
        argv = ["unshare", flag, "--", "bash", self.pkg(root, self.profile["wrapper"]["path"]), fresh_output]
        return {"argv": argv, "env": env, "cwd": root, "namespace_flag": flag, "output_dir": fresh_output}

    # ---- collect ----------------------------------------------------------------------------------------------------------
    def collect(self, job_exit, out_dir, managed_dir):
        """Map raw records to the three axes. `job_exit` keys: wrapper_exit, signal, cancelled, deadline, app_failure."""
        p = self.profile
        root = self.package_root(managed_dir)
        arts, parsed, problems = {}, {}, {}
        for name in ("verdict.json", "run-info.json", "preflight.json"):
            raw, obj, prob = R.read_record(os.path.join(out_dir, name))
            arts[name] = {"present": raw is not None, "bytes": None if raw is None else len(raw),
                          "sha256": None if raw is None else R.sha256_bytes(raw), "problem": prob}
            parsed[name] = (raw, obj)
        vraw, vobj = parsed["verdict.json"]
        iraw, iobj = parsed["run-info.json"]
        vprob = arts["verdict.json"]["problem"] or ("; ".join(R.validate_verdict(vobj)) or None) if vraw is not None else "missing"
        iprob = arts["run-info.json"]["problem"] or ("; ".join(R.validate_run_info(iobj)) or None) if iraw is not None else "missing"
        verdict_ok, info_ok = vprob is None, iprob is None
        p10 = {"state": "UNAVAILABLE", "outcome": None, "stage": None, "reason": None, "rows": None,
               "record_problems": {"verdict.json": vprob, "run-info.json": iprob}}
        if verdict_ok:
            p10.update(state="AVAILABLE", outcome=vobj["outcome"], stage=vobj["stage"], reason=vobj["reason"],
                       rows=(vobj.get("post") or {}).get("rows") if isinstance(vobj.get("post"), dict) else None)
        we = job_exit.get("wrapper_exit")
        interrupted = job_exit.get("cancelled") or job_exit.get("deadline") or job_exit.get("app_failure") or we is None
        repro = {"status": "NOT_EVALUATED", "badge": False, "checks": [], "reasons": []}
        ex = {"status": "COMPLETED", "reason": None}

        def refs():
            out = []
            for rel in p["references"]:
                try:
                    with open(self.pkg(root, *rel.split("/")), "rb") as f:
                        out.append((rel, f.read()))
                except OSError:
                    out.append((rel, None))
            return out

        def checks():
            cs = []
            add = lambda i, ok, d="": cs.append({"id": i, "ok": bool(ok), "detail": str(d)[:300]})
            add("wrapper-exit-0", we == 0, f"wrapper exit {we}")
            add("verdict-valid", verdict_ok, vprob or "")
            add("run-info-valid", info_ok, iprob or "")
            add("outcome-binding-match", verdict_ok and vobj["outcome"] == "BINDING_MATCH", p10["outcome"])
            vsha = arts["verdict.json"]["sha256"]
            add("verdict-sha-equals-approved-digest", vsha == p["accepted_verdict_sha256"], vsha)
            for rel, rb in refs():
                add("verdict-bytes-equal-" + rel.split("/")[-2], rb is not None and vraw is not None and rb == vraw, rel)
            ep = vobj.get("executables_pinned") if verdict_ok else None
            add("executables-pinned-true", ep == {"entry": True, "g5": True} and all(v is True for v in ep.values()), json.dumps(ep, sort_keys=True))
            if info_ok:
                add("network-isolated-measured", iobj["network_isolated"] is True, repr(iobj["network_isolated"]))
                add("no-problems", iobj["problems"] == [], json.dumps(iobj["problems"])[:200])
                add("no-tcb-source-mismatch", iobj["tcb_source_mismatch"] == [], json.dumps(iobj["tcb_source_mismatch"])[:200])
                add("runner-source-hashes", iobj["runner_source_sha256"] == p["runner_source_sha256"], "")
                add("entry-binary-hash", iobj["entry_binary_sha256"] == p["entry_binary_sha256"], iobj["entry_binary_sha256"])
                add("g5-binary-hash", iobj["g5_binary_sha256"] == p["g5_binary_sha256"], iobj["g5_binary_sha256"])
            else:
                add("run-info-conditions", False, "run-info.json unusable")
            return cs

        unpromoted = dict(p10, state="NOT_EVALUATED", outcome=None, stage=None, reason=None, rows=None)
        if job_exit.get("app_failure"):
            ex = {"status": "APP_FAILURE", "reason": job_exit["app_failure"]}
            p10 = unpromoted
        elif job_exit.get("cancelled") or job_exit.get("deadline"):
            ex = {"status": "CANCELLED", "reason": "deadline" if job_exit.get("deadline") else "cancelled"}
            p10 = unpromoted
            repro["reasons"].append("interrupted run; partial records are preserved but not promoted")
        elif we is None:
            ex = {"status": "APP_FAILURE", "reason": "WRAPPER_TERMINATED_BY_SIGNAL" if job_exit.get("signal") else "NO_WRAPPER_EXIT"}
            p10 = unpromoted
        elif we == 2:
            ex = {"status": "BLOCKED", "reason": "wrapper refused: " + WRAPPER_EXIT_MEANING[2]}
            p10 = unpromoted
        elif we == 3:
            ex = {"status": "APP_FAILURE", "reason": "WRAPPER_TEST_MODE"}
            p10 = unpromoted
        elif we not in (0, 1):
            ex = {"status": "APP_FAILURE", "reason": f"UNEXPECTED_WRAPPER_EXIT_{we}"}
            p10 = unpromoted
        elif not verdict_ok:
            ex = {"status": "APP_FAILURE", "reason": "RUNNER_RECORD_MISSING_OR_INVALID"}
            repro["reasons"].append("verdict.json: " + str(vprob))
        else:
            cs = checks()
            repro["checks"] = cs
            allok = all(c["ok"] for c in cs)
            outcome = vobj["outcome"]
            if we == 0:
                if allok:
                    repro.update(status="MATCH", badge=not self.synthetic)
                else:
                    ex = {"status": "APP_FAILURE", "reason": "CONTRADICTORY_ZERO_EXIT"}
                    repro["reasons"].append("wrapper exit 0 but the raw records do not satisfy the profile conditions")
            else:  # wrapper exit 1
                if outcome in ("S3-FAIL(packaging)", "S3-FAIL(infrastructure)"):
                    repro["status"] = "NOT_EVALUATED"
                    repro["reasons"].append("runner reported an S3-FAIL record; no replay comparison was made")
                else:
                    repro["status"] = "DIFFERENT"
                    repro["reasons"].append("wrapper reported a failed replay or comparison")
        if we == 0 and ex["status"] == "APP_FAILURE":
            repro.update(status="NOT_EVALUATED", badge=False)
        return {"execution": ex, "p10": p10, "reproduction": repro, "artifacts": arts,
                "wrapper_exit": we, "wrapper_exit_meaning": WRAPPER_EXIT_MEANING.get(we), "synthetic": self.synthetic,
                "interrupted": bool(interrupted)}
