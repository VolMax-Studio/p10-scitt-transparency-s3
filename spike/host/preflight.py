#!/usr/bin/env python3
"""NON-NORMATIVE FEASIBILITY SPIKE. Host preflight for the traced S3-C chain.

Each required toolchain/source is checked against ITS OWN frozen pin; nothing assumes one Lean executable satisfies every pin:
  * S1 / S2a / S2b checkouts: HEAD == pinned commit, clean working tree.
  * S2b frozen files: SHA-256 against scripts/PINS.txt FILE entries; S2a files against frozen/UPSTREAM_HASHES.txt.
  * S1 verifier manifest SHA-256 against the S2b/S2a recorded value; the S1 static OPEN-S13 check (no Lean).
  * Lean candidate directories: `lean` against the S2a manifest (lean_toolchain_artifact_digest) AND the S1 manifest
    (lean_toolchain_artifact_sha256); `lake`, `leanchecker`, `libleanshared.so` against the S1 manifest; version string against the S1 manifest.
    Only `lean` is required by the S2b launchers on this chain; the others are reported against the S1 pins.
  * Rust: `rustc -V` inside spike/s3-entry (its rust-toolchain.toml pins 1.82.0) must be 1.82.0.
  * Native link prerequisites the S2b cc_wrapper does not repair: a working `cc ... -luv` link.
  * spike/s3-entry/Cargo.lock: every locked crate (except the entry itself) is identical (name, version, checksum) to the S2b Cargo.lock.

A failed REQUIRED check means: stop and report the exact prerequisite. No substitution.
usage: preflight.py --s1 D --s2a D --s2b D [--lean-bin-dir D] --out report.json
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile

PINS = {
    "s1": ("e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1", "v0.1.0-s1-ratified"),
    "s2a": ("741d56d36d7b2bfe2e9e0080a1cba4393e4a47da", "v0.1.0-s2a-ratified"),
    "s2b": ("8eaa91cad1ffa963158b365c6d0d7316f4965e89", "v0.1.0-s2b-complete"),
}
S1_MANIFEST_SHA256 = "06bf9129bf480c79ed5281ec2e944ac5613d1c340552ce5a415f5bf4c8965907"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sh(argv, cwd=None):
    p = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s1", required=True)
    ap.add_argument("--s2a", required=True)
    ap.add_argument("--s2b", required=True)
    ap.add_argument("--lean-bin-dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    spike = os.path.dirname(here)
    res = []

    def chk(cid, ok, detail, required=True):
        res.append({"id": cid, "ok": bool(ok), "required": required, "detail": detail})
        print(("ok   " if ok else ("FAIL " if required else "info ")) + cid + ((" :: " + detail) if detail and (not ok or not required) else ""))

    dirs = {"s1": a.s1, "s2a": a.s2a, "s2b": a.s2b}
    for k, d in dirs.items():
        rc, head, _ = sh(["git", "-C", d, "rev-parse", "HEAD"])
        chk(f"{k}-commit", rc == 0 and head == PINS[k][0], f"{head} (want {PINS[k][0]})")
        rc, st, _ = sh(["git", "-C", d, "status", "--porcelain"])
        chk(f"{k}-clean", rc == 0 and st == "", st[:200] or "clean")
        rc, peeled, _ = sh(["git", "-C", d, "rev-parse", PINS[k][1] + "^{}"])
        chk(f"{k}-tag-peels-to-pin", rc == 0 and peeled == PINS[k][0], f"{PINS[k][1]} -> {peeled or 'tag not present locally'}", required=False)

    # S2b frozen files vs PINS.txt
    bad = []
    for ln in open(os.path.join(a.s2b, "scripts", "PINS.txt"), encoding="utf-8"):
        p = ln.split()
        if len(p) == 3 and p[0] == "FILE":
            if sha256_file(os.path.join(a.s2b, p[2])) != p[1]:
                bad.append(p[2])
    chk("s2b-frozen-files-vs-PINS.txt", not bad, "differ: " + ",".join(bad))
    # S2a files vs UPSTREAM_HASHES
    bad = []
    for ln in open(os.path.join(a.s2b, "frozen", "UPSTREAM_HASHES.txt"), encoding="utf-8"):
        m = re.match(r"^([0-9a-f]{64})  (\S+)$", ln.strip())
        if m and "S1_GIT_TREE" not in m.group(2):
            if sha256_file(os.path.join(a.s2a, m.group(2))) != m.group(1):
                bad.append(m.group(2))
    chk("s2a-files-vs-UPSTREAM_HASHES", not bad, "differ: " + ",".join(bad))
    chk("s1-verifier-manifest-sha256", sha256_file(os.path.join(a.s1, "manifest", "VerifierManifestS1.json")) == S1_MANIFEST_SHA256, S1_MANIFEST_SHA256)
    rc, so, se = sh([sys.executable, "-B", os.path.join(a.s2b, "harness", "repro_open_s13.py"), "static", "--s1-root", a.s1])
    chk("s1-static-open-s13-check", rc == 0 and "STATIC CHECKS PASSED" in so, (se or so)[-200:])

    # Lean: each binary against its own manifest
    m2a = json.load(open(os.path.join(a.s2a, "manifest", "VerifierManifestS2aV0.json")))
    m1 = json.load(open(os.path.join(a.s1, "manifest", "VerifierManifestS1.json")))
    cands = []
    if a.lean_bin_dir:
        cands.append(a.lean_bin_dir)
    if os.environ.get("P10_LEAN_BIN_DIR"):
        cands.append(os.environ["P10_LEAN_BIN_DIR"])
    cands.append(os.path.join(a.s1, ".toolchain", "lean4-4.33.0", "bin"))
    w = shutil.which("lean")
    if w:
        cands.append(os.path.dirname(os.path.realpath(w)))
    found = None
    for d in cands:
        lean = os.path.join(d, "lean")
        if not os.path.isfile(lean):
            continue
        got = sha256_file(lean)
        ok2a = got == m2a["lean_toolchain_artifact_digest"]
        ok1 = got == m1["lean_toolchain_artifact_sha256"]
        chk(f"lean[{d}]-vs-S2a-manifest", ok2a, f"{got} (S2a pin {m2a['lean_toolchain_artifact_digest']})", required=False)
        chk(f"lean[{d}]-vs-S1-manifest", ok1, f"{got} (S1 pin {m1['lean_toolchain_artifact_sha256']})", required=False)
        for name, key in (("lake", "lake_executable_sha256"), ("leanchecker", "leanchecker_executable_sha256")):
            pth = os.path.join(d, name)
            g = sha256_file(pth) if os.path.isfile(pth) else None
            chk(f"{name}[{d}]-vs-S1-manifest", g == m1[key], f"{g} (S1 pin {m1[key]})", required=False)
        lib = os.path.join(os.path.dirname(d), "lib", "lean", "libleanshared.so")
        g = sha256_file(lib) if os.path.isfile(lib) else None
        chk(f"libleanshared[{d}]-vs-S1-manifest", g == m1["lean_shared_library_sha256"], f"{g} (S1 pin {m1['lean_shared_library_sha256']})", required=False)
        rc, so, se = sh([lean, "--version"])
        chk(f"lean[{d}]-version-vs-S1-manifest", so == m1["lean_version_string"], f"{so!r}", required=False)
        if ok2a and not found:
            found = d
    chk("lean-executable-pinned-by-S2a-manifest-available", found is not None,
        f"candidate dir {found}" if found else "no candidate directory contains a `lean` with SHA-256 " + m2a["lean_toolchain_artifact_digest"] +
        " (conda-forge lean4 4.33.0 build h6c1889d_0); pass --lean-bin-dir or set P10_LEAN_BIN_DIR")

    # Rust
    rc, so, se = sh(["rustc", "-V"], cwd=os.path.join(spike, "s3-entry"))
    chk("rustc-1.82.0 (spike/s3-entry/rust-toolchain.toml)", rc == 0 and so.startswith("rustc 1.82.0 "), so or se)
    # native link prerequisite (-luv) not repaired by cc_wrapper.sh
    with tempfile.TemporaryDirectory() as t:
        open(os.path.join(t, "x.c"), "w").write("int main(void){return 0;}\n")
        rc, so, se = sh(["cc", os.path.join(t, "x.c"), "-luv", "-o", os.path.join(t, "x")])
    chk("native-link-libuv (cc -luv)", rc == 0, se[-200:])
    rc, so, se = sh(["cc", "--version"])
    chk("native-cc-version", rc == 0, so.splitlines()[0] if so else se, required=False)
    chk("python-version", True, sys.version.split()[0] + " (the S2b acceptance environment pins CPython 3.12.3 for its oracle; the spike chain uses only the standard library)", required=False)

    # lock subset
    def locked(path):
        txt = open(path, encoding="utf-8").read()
        out = {}
        for blk in txt.split("[[package]]")[1:]:
            n = re.search(r'name = "([^"]+)"', blk)
            v = re.search(r'version = "([^"]+)"', blk)
            c = re.search(r'checksum = "([^"]+)"', blk)
            out[n.group(1)] = (v.group(1), c.group(1) if c else None)
        return out
    l2b, lsp = locked(os.path.join(a.s2b, "Cargo.lock")), locked(os.path.join(spike, "s3-entry", "Cargo.lock"))
    diff = [n for n, v in lsp.items() if n not in ("s3-spike-entry",) and l2b.get(n) != v]
    chk("spike-Cargo.lock-subset-of-S2b-Cargo.lock", not diff, "differ: " + ",".join(diff))

    json.dump(res, open(a.out, "w"), indent=1)
    failed = [r for r in res if r["required"] and not r["ok"]]
    print(f"\npreflight: {len(res)} checks, {len(failed)} required failed")
    for r in failed:
        print("  MISSING/WRONG:", r["id"], "->", r["detail"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
