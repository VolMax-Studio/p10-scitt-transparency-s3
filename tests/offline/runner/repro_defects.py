#!/usr/bin/env python3
"""TEST HARNESS (not acceptance code): reproduces the reviewed runner defects against ANY runner directory (older or corrected) and records the observed behaviour,
so that before/after can be compared. Expectations about what is right live in the regression tests, not here; this script only observes.

  R1a  a direct `--_inner "unshare -n"` call without any isolation: what does the runner report about the network?
  R1b  a direct `--_inner` call with a non-empty output directory
  R2   (--heavy) the supplied capture directory is modified AFTER G5 returned (a wrapper G5 swaps material/iB.json in the ORIGINAL directory): which bytes does the chain use?
  R3   stage-output readers: unknown S2b class, Unavailable without reason, duplicate JSON key, S2A reject with garbage repr
  R4   S2A `pb` decode=false with a frozen coverage REJECT (c1_profileDecode): which outcome is reported?

usage: repro_defects.py --runner-dir DIR --s1 D --s2a D --s2b D --entry BIN --g5 BIN --capture D --anchor HEX --work DIR --out FILE [--lean-bin-dir D] [--heavy] [--label before|after]
"""
import argparse, hashlib, json, os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
for k in ("runner-dir", "s1", "s2a", "s2b", "entry", "g5", "capture", "anchor", "work", "out"): ap.add_argument("--" + k, required=True)
ap.add_argument("--lean-bin-dir"); ap.add_argument("--heavy", action="store_true"); ap.add_argument("--label", default="")
A = ap.parse_args()
os.environ["S3C_RUNNER_DIR"] = os.path.abspath(A.runner_dir)
RUN = os.path.join(os.path.abspath(A.runner_dir), "s3c_verify.py")
os.makedirs(A.work, exist_ok=True)
rd = lambda p: open(p, "rb").read()
sha = lambda b: hashlib.sha256(b).hexdigest()
rep = {"label": A.label, "runner_dir": A.runner_dir, "harness_process_interfaces": [n for _, n in socket.if_nameindex()]}


def argv(out, capture=None, anchor=None, g5=None, extra=()):
    a = [sys.executable, "-B", RUN, "--capture", capture or A.capture, "--anchor", anchor or A.anchor, "--out", out, "--s1", A.s1, "--s2a", A.s2a, "--s2b", A.s2b,
         "--entry", A.entry, "--g5", g5 or A.g5] + (["--lean-bin-dir", A.lean_bin_dir] if A.lean_bin_dir else []) + list(extra)
    return a


def load(out):
    v = os.path.join(out, "verdict.json"); i = os.path.join(out, "run-info.json")
    return (json.load(open(v)) if os.path.exists(v) else None), (json.load(open(i)) if os.path.exists(i) else {})


# R1a / R1b ------------------------------------------------------------------------------------------------------------------------------
o = os.path.join(A.work, "r1a"); p = subprocess.run(argv(o, anchor="0" * 64, extra=["--_inner", "unshare -n"]), capture_output=True, text=True); v, i = load(o)
rep["R1a_direct_inner_without_isolation"] = {"exit": p.returncode, "outcome": (v or {}).get("outcome"), "stage": (v or {}).get("stage"), "reason": (v or {}).get("reason"),
                                              "run_info_network_isolated": i.get("network_isolated"), "run_info_isolation_label": i.get("isolation")}
o = os.path.join(A.work, "r1b"); os.makedirs(o); open(os.path.join(o, "stale-file"), "w").write("x")
p = subprocess.run(argv(o, anchor="0" * 64, extra=["--_inner", "unshare -n"]), capture_output=True, text=True); v, i = load(o)
rep["R1b_direct_inner_non_empty_out"] = {"exit": p.returncode, "outcome": (v or {}).get("outcome"), "stale_file_still_present": os.path.exists(os.path.join(o, "stale-file")), "ran_stages": [c["name"] for c in i.get("commands", [])]}
o = os.path.join(A.work, "r1c"); os.makedirs(o); open(os.path.join(o, "stale-file"), "w").write("x")
p = subprocess.run(argv(o, anchor="0" * 64), capture_output=True, text=True)
rep["R1c_normal_path_non_empty_out"] = {"exit": p.returncode}

# R3 / R4 (stub stages) -------------------------------------------------------------------------------------------------------------------
sys.path.insert(0, HERE)
import test_stages as T
T.S2B_REAL = A.s2b
stub = {}
def case(name, setup):
    tmp = tempfile.mkdtemp(); f = T.Fake(tmp); setup(f); r = f.run("x")
    stub[name] = {"outcome": r["outcome"], "stage": r["stage"], "reason": r["reason"]}; shutil.rmtree(tmp, ignore_errors=True)
case("R3_unknown_s2b_class_Typo", lambda f: f.set_entry(rc=10, result={"status": "Invalid", "reason": {"class": "Typo", "reason": "X"}}, files=False))
case("R3_unavailable_without_reason", lambda f: f.set_entry(rc=11, result={"status": "Unavailable"}, files=False))
def dup(f):
    d = f.root; open(os.path.join(d, "dup.json"), "w").write('{"status":"Verified","status":"Invalid","reason":{"class":"Binding","reason":"X"}}')
    open(f.entry, "w").write(f"#!{sys.executable}\nimport shutil, sys\na = sys.argv; out = a[a.index('--out') + 1]\nimport os; os.makedirs(out, exist_ok=True)\nshutil.copy({json.dumps(os.path.join(d, 'dup.json'))}, os.path.join(out, 'result.json'))\nsys.exit(10)\n")
case("R3_duplicate_json_key_in_result", dup)
def garbage(f):
    L = list(f.base_lines); L[3] = json.dumps({"op": "cov", "result": {"outcome": "reject", "repr": "garbage"}}); f.set_s2a(L)
case("R3_s2a_reject_with_garbage_repr", garbage)
def pbdec(f):
    L = list(f.base_lines); L[2] = json.dumps({"op": "pb", "decode": False})
    L[3] = json.dumps({"op": "cov", "result": {"outcome": "reject", "repr": "P10S2.CoverageOutcome.reject (P10S2.RejectReason.c1_profileDecode)"}}); f.set_s2a(L)
case("R4_pb_decode_false_with_frozen_coverage_reject", pbdec)
def tbdec(f):
    L = list(f.base_lines); L[0] = json.dumps({"op": "tb", "decode": False}); L[3] = json.dumps({"op": "cov", "error": "tB does not strict-decode"}); f.set_s2a(L)
case("R4_transcript_decode_false_cov_error", tbdec)
def instdec(f):
    L = list(f.base_lines); L[1] = json.dumps({"op": "inst", "decode": False}); L[3] = json.dumps({"op": "cov", "error": "instB does not strict-decode"}); f.set_s2a(L)
case("R4_instance_decode_false_cov_error", instdec)
rep["stub_stage_cases"] = stub

# R2 (heavy: a real chain run) ------------------------------------------------------------------------------------------------------------
if A.heavy:
    wd = os.path.join(A.work, "r2"); os.makedirs(wd)
    orig = os.path.join(wd, "capture"); shutil.copytree(A.capture, orig, symlinks=True)
    mutant = os.path.join(A.s2a, "vectors", "P1", "iB.json")
    wrapper = os.path.join(wd, "g5-wrapper.sh")
    open(wrapper, "w").write('#!/usr/bin/env bash\nout=$("$G5_REAL" "$@"); rc=$?\necho "$out"\nif [ $rc = 0 ]; then cp "$MUTANT" "$ORIG_CAPTURE/material/iB.json"; fi\nexit $rc\n')
    os.chmod(wrapper, 0o755)
    pins = os.path.join(wd, "pinned-nopin.json"); P = json.load(open(os.path.join(os.path.abspath(A.runner_dir), "PINNED_INPUTS.json")))
    if "executables" in P:
        for k in P["executables"]: P["executables"][k]["sha256"] = None
    json.dump(P, open(pins, "w"))
    env = dict(os.environ, G5_REAL=A.g5, ORIG_CAPTURE=orig, MUTANT=mutant)
    out = os.path.join(wd, "out")
    extra = ["--pinned", pins] if "executables" in P else []
    p = subprocess.run(argv(out, capture=orig, g5=wrapper, extra=extra), capture_output=True, text=True, env=env); v, i = load(out)
    idx = json.load(open(os.path.join(A.capture, "capture.json")))
    indexed = {"s1_instance": idx["material"]["s1_instance"]["sha256"], "profile_artifact": idx["material"]["profile_artifact"]["sha256"],
               "instance_commitment": idx["material"]["instance_commitment"]["sha256"], "request": idx["request"]["sha256"]}
    got = i.get("input_sha256", {})
    rep["R2_capture_modified_after_G5"] = {"exit": p.returncode, "outcome": (v or {}).get("outcome"), "stage": (v or {}).get("stage"), "reason": (v or {}).get("reason"),
                                           "bytes_used_equal_anchored_bytes": {k: got.get(k) == indexed[k] for k in indexed},
                                           "original_directory_iB_changed": sha(rd(os.path.join(orig, "material", "iB.json"))) != indexed["s1_instance"]}
json.dump(rep, open(A.out, "w"), indent=1, sort_keys=True)
print(json.dumps(rep, indent=1, sort_keys=True))
