#!/usr/bin/env python3
"""Facade / public-read tests (PROTOTYPE checks, not frozen-chain verdicts). Starts real s3-facade processes and talks to them over HTTP only.

  T1 size limit on LeafEncodeV0(statement): 65474 accepted, 65475 refused (413), nothing appended on refusal
  T2 structural admission refusals (400, codes) append nothing
  T3 persistent duplicate prevention: same bytes -> same index, same stored Receipt, also after a clean restart; public read whitelist
  T4 abrupt termination (self-SIGKILL) at pre-add | submitted | integrated | receipt-stored | pre-response, then restart and retry by the capture client
  T5 chaos: external SIGKILL at random times while the capture client submits N statements; exactly-once invariant at the end
  T6 pinned-key / origin enforcement: wrong pin or origin refuses to start; the capture client rejects a wrong key/origin; a forged checkpoint on the public
     endpoint (valid format, wrong key) makes the facade fail closed (502, no Receipt issued, none stored)

usage: facade_tests.py --bin DIR --py PYTHON --s2b DIR --keys-dir DIR --note-keys DIR --fixture DIR --out DIR [--only T1,T4] [--chaos-n 30] [--seed 1]
"""
import argparse, json, os, random, shutil, signal, subprocess, sys, threading, time, urllib.request, urllib.error, glob

ap = argparse.ArgumentParser()
for k in ("bin", "py", "s2b", "keys-dir", "note-keys", "fixture", "out"):
    ap.add_argument("--" + k, required=True)
ap.add_argument("--only", default="T1,T2,T3,T4,T5,T6")
ap.add_argument("--chaos-n", type=int, default=30)
ap.add_argument("--seed", type=int, default=1)
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
import gen_corpus as G

meta = json.load(open(os.path.join(a.fixture, "PUBLIC_META.json")))
TS_ISS, THUMB = meta["identity"]["ts_iss"], meta["identity"]["ts_key_thumbprint"]
VKEY = open(os.path.join(a.note_keys, "note.vkey")).read().strip()
ORIGIN = VKEY.split("+")[0]
TS_PUB = os.path.join(a.fixture, "public", "ts.public.cose_key.cbor")
OUT = os.path.abspath(a.out); os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
results = {}

def stmt(i, size=None, prot_extra=None, unprot=None, sub=None):
    """structurally conformant COSE_Sign1 (signature bytes are dummy: the facade does not verify issuer signatures)"""
    sub = sub or f"urn:volmax:s3-test:facade-test-{i}"
    prot = G.cmap([(G.uint(1), G.integer(-7)), (G.uint(15), G.cmap([(G.uint(1), G.tstr("facade-test")), (G.uint(2), G.tstr(sub))]))] + (prot_extra or []))
    def build(n):
        payload = (f"payload-{i}-".encode() + b"x" * n)
        return G.tag(18, G.arr([G.bstr(prot), unprot if unprot is not None else G.cmap([]), G.bstr(payload), G.bstr(b"\0" * 64)]))
    if size is None:
        return build(8)
    base = len(build(0)); assert size >= base
    for d in range(0, 8):   # the payload byte-string header grows with its length: search the padding that hits the exact size
        s = build(size - base - d)
        if len(s) == size: return s
    raise AssertionError("cannot build a statement of the requested size")

class Facade:
    def __init__(self, name, port, batch="1:10ms", cpint="200ms", extra=()):
        self.name, self.reg, self.pub = name, port, port + 1
        self.dir = os.path.join(OUT, name); os.makedirs(self.dir, exist_ok=True)
        self.batch, self.cpint, self.extra, self.proc = batch, cpint, list(extra), None
        self.starts = 0
    def start(self, fault=None, on_req=1):
        bs, ba = self.batch.split(":")
        cmd = [os.path.join(a.bin, "s3-facade"), "--storage", f"{self.dir}/log", "--state", f"{self.dir}/state", "--origin", ORIGIN,
               "--note-skey-file", os.path.join(a.note_keys, "note.skey"), "--note-vkey", VKEY, "--cose-key", os.path.join(a.keys_dir, "ts.pem"),
               "--ts-iss", TS_ISS, "--expect-thumbprint", THUMB, "--register-addr", f"127.0.0.1:{self.reg}", "--public-addr", f"127.0.0.1:{self.pub}",
               "--batch-size", bs, "--batch-age", ba, "--checkpoint-interval", self.cpint] + self.extra
        if fault: cmd += ["--fault-point", fault, "--fault-on-request", str(on_req)]
        self.starts += 1
        self.err = open(os.path.join(self.dir, f"facade-{self.starts}.err"), "wb")
        self.proc = subprocess.Popen(cmd, stderr=self.err, stdout=subprocess.DEVNULL)
        for _ in range(100):
            if self.proc.poll() is not None: raise RuntimeError(f"{self.name}: facade exited rc={self.proc.returncode} on start")
            try:
                self.config(); return
            except Exception: time.sleep(0.1)
        raise RuntimeError("facade did not become ready")
    def url(self): return f"http://127.0.0.1:{self.reg}"
    def purl(self): return f"http://127.0.0.1:{self.pub}"
    def config(self): return json.load(urllib.request.urlopen(self.url() + "/config", timeout=2))
    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try: self.proc.wait(20)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
    def kill(self):
        if self.proc and self.proc.poll() is None: self.proc.kill(); self.proc.wait()
    def post(self, data, timeout=60):
        rq = urllib.request.Request(self.url() + "/register", data=data, method="POST", headers={"Content-Type": "application/cose"})
        try:
            r = urllib.request.urlopen(rq, timeout=timeout); return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    def get_public(self, path, method="GET"):
        try:
            r = urllib.request.urlopen(urllib.request.Request(self.purl() + path, method=method), timeout=5); return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, b""
    def checkpoint_size(self):
        st, b = self.get_public("/checkpoint")
        return int(b.decode().split("\n")[1]) if st == 200 else None
    def journal(self):
        p = f"{self.dir}/state/journal.jsonl"
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

def client(cmd, *args):
    r = subprocess.run([os.path.join(a.bin, "s3-capture"), cmd, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

def write_stmts(d, items, first=0):
    os.makedirs(d, exist_ok=True)
    for i, s in enumerate(items): open(f"{d}/{first + i:06d}.cose", "wb").write(s)

def s3check(run, n, allow_retry=False):
    rep = os.path.join(run, "s3check.json")
    r = subprocess.run([a.py, "-B", os.path.join(HERE, "s3check.py"), "--run", run, "--s2b", a.s2b, "--note-vkey", VKEY, "--origin", ORIGIN, "--ts-pub", TS_PUB,
                        "--ts-iss", TS_ISS, "--out", rep, "--expect", str(n)] + (["--allow-retry"] if allow_retry else []), capture_output=True, text=True)
    open(os.path.join(run, "s3check.out"), "w").write(r.stdout + r.stderr)
    return r.returncode == 0, json.load(open(rep)) if os.path.exists(rep) else None

def submit_and_export(f, items, run, first, total, retries=3, allow_retry=False):
    """submit items[first:] (file name = log index) with the capture client, then export `total` entries and run the independent checks"""
    sd = os.path.join(run, f"_statements_from_{first}"); write_stmts(sd, items[first:], first)
    rc, o = client("submit", "--facade", f.url(), "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--statements", sd, "--out", run, "--retries", str(retries))
    if rc: return False, "submit: " + o
    rc, o = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", str(total), "--out", run)
    if rc: return False, "export: " + o
    ok, rep = s3check(run, total, allow_retry)
    return ok, rep

def exported(run): return [open(p, "rb").read() for p in sorted(glob.glob(f"{run}/export/*.leaf_input"))]

# ------------------------------------------------------------------------------------------------ T1
def T1():
    f = Facade("t1", 19100); f.start(); res = {}
    try:
        ok_stmt, big = stmt(0, 65474), stmt(1, 65475)
        s1, j1 = f.post(ok_stmt); res["statement_65474"] = {"http": s1, "leaf_input_len": 65474 + 61, "index": j1.get("index")}
        sz = f.checkpoint_size()
        s2, j2 = f.post(big); res["statement_65475"] = {"http": s2, "error": j2.get("error"), "leaf_input_len": 65475 + 61}
        time.sleep(0.6)
        res["checkpoint_size_after_refusal"] = f.checkpoint_size()
        s3, j3 = f.post(b"x" * 70000); res["body_70000_bytes"] = {"http": s3, "error": j3.get("error")}
        ok = s1 == 201 and s2 == 413 and j2.get("error") == "E_TOO_LARGE" and s3 == 413 and res["checkpoint_size_after_refusal"] == sz == 1
        # the stored/returned bytes of the largest accepted statement are exact
        run = os.path.join(f.dir, "run"); rc, o = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", "1", "--out", run)
        e = exported(run); ok &= rc == 0 and len(e) == 1 and e[0] == G.leaf_input(ok_stmt) and len(e[0]) == 65535
        res["max_entry_exported_exactly"] = rc == 0 and len(e) == 1 and e[0] == G.leaf_input(ok_stmt)
        return ok, res
    finally: f.stop()

# ------------------------------------------------------------------------------------------------ T2
def T2():
    f = Facade("t2", 19110); f.start(); res = {}
    try:
        good = stmt(0)
        cases = {
            "E_UNPROTECTED_NOT_EMPTY": stmt(1, unprot=G.cmap([(G.uint(4), G.bstr(b"kid"))])),
            "E_NOT_COSE_SIGN1": G.arr([G.bstr(b""), G.cmap([]), G.NULL, G.bstr(b"")]),
            "E_NOT_CBOR": b"\xff\xff",
            "E_CWT_CLAIMS_MISSING": G.tag(18, G.arr([G.bstr(G.cmap([(G.uint(1), G.integer(-7))])), G.cmap([]), G.bstr(b"p"), G.bstr(b"s")])),
            "E_ISS_SUB_NOT_TEXT": G.tag(18, G.arr([G.bstr(G.cmap([(G.uint(15), G.cmap([(G.uint(1), G.tstr("i")), (G.uint(2), G.uint(5))]))])), G.cmap([]), G.bstr(b"p"), G.bstr(b"s")])),
            "E_NOT_CBOR(trailing)": good + b"\x00",
        }
        ok = True
        s0, j0 = f.post(good); ok &= s0 == 201
        for want, b in cases.items():
            st, j = f.post(b); got = j.get("error"); res[want] = {"http": st, "error": got}
            ok &= st == 400 and got == want.split("(")[0]
        time.sleep(0.6); res["checkpoint_size_after_refusals"] = f.checkpoint_size(); ok &= res["checkpoint_size_after_refusals"] == 1
        return ok, res
    finally: f.stop()

# ------------------------------------------------------------------------------------------------ T3
def T3():
    f = Facade("t3", 19120); f.start(); res = {}
    try:
        s = [stmt(i) for i in range(3)]
        codes = [f.post(x) for x in s]
        again = f.post(s[1])
        res["resubmit"] = {"http": again[0], "duplicate": again[1]["duplicate"], "same_index": again[1]["index"] == 1, "same_receipt_bytes": again[1]["receipt_b64"] == codes[1][1]["receipt_b64"], "receipt_reused": again[1].get("receipt_reused")}
        f.stop(); f.start()  # clean restart: the duplicate index is rebuilt from the log
        after = f.post(s[0])
        res["resubmit_after_restart"] = {"http": after[0], "duplicate": after[1]["duplicate"], "index": after[1]["index"], "same_receipt_bytes": after[1]["receipt_b64"] == codes[0][1]["receipt_b64"], "log_entries_at_start": f.config()["log_entries_at_start"]}
        time.sleep(0.6); res["checkpoint_size"] = f.checkpoint_size()
        ok = (all(c[0] == 201 for c in codes) and again[0] == 200 and again[1]["duplicate"] and again[1]["index"] == 1 and res["resubmit"]["same_receipt_bytes"]
              and after[0] == 200 and after[1]["duplicate"] and after[1]["index"] == 0 and res["resubmit_after_restart"]["same_receipt_bytes"] and res["checkpoint_size"] == 3)
        # public read whitelist
        pr = {"checkpoint": f.get_public("/checkpoint")[0], "tile_level0_partial": f.get_public("/tile/0/000.p/3")[0], "entries_partial": f.get_public("/tile/entries/000.p/3")[0],
              "state_dir": f.get_public("/.state/treeState")[0], "dir_listing": f.get_public("/tile/0/")[0], "root": f.get_public("/")[0],
              "traversal": f.get_public("/tile/0/..%2f..%2fcheckpoint")[0], "POST_checkpoint": None}
        rq = urllib.request.Request(f.purl() + "/checkpoint", data=b"x", method="POST")
        try: urllib.request.urlopen(rq); pr["POST_checkpoint"] = 200
        except urllib.error.HTTPError as e: pr["POST_checkpoint"] = e.code
        res["public_read"] = pr
        ok &= pr["checkpoint"] == 200 and pr["tile_level0_partial"] == 200 and pr["entries_partial"] == 200 and pr["state_dir"] == 404 and pr["dir_listing"] == 404 and pr["root"] == 404 and pr["traversal"] == 404 and pr["POST_checkpoint"] == 405
        # the registration endpoint serves no log data and the public endpoint accepts no registration
        st = urllib.request.Request(f.url() + "/checkpoint")
        try: urllib.request.urlopen(st); rs = 200
        except urllib.error.HTTPError as e: rs = e.code
        res["registration_endpoint_serves_no_log_data"] = rs; ok &= rs in (404, 405)
        return ok, res
    finally: f.stop()

# ------------------------------------------------------------------------------------------------ T4
POINTS = ["pre-add", "submitted", "integrated", "receipt-stored", "pre-response"]
def T4():
    res, allok = {}, True
    for n, fp in enumerate(POINTS):
        # batching with a long max age keeps an appended entry un-integrated for a while, so 'submitted' kills BEFORE integration
        f = Facade(f"t4-{fp}", 19200 + 10 * n, batch="100:1s"); f.start()
        run = os.path.join(f.dir, "run"); items = [stmt(100 + i) for i in range(4)]
        info = {}
        try:
            # S0,S1 normally
            sd = os.path.join(run, "_pre"); write_stmts(sd, items[:2])
            rc, o = client("submit", "--facade", f.url(), "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--statements", sd, "--out", run)
            assert rc == 0, o
            f.stop(); f.start(fault=fp, on_req=1)           # next admitted registration kills the process
            st = None
            try: st = f.post(items[2], timeout=60)
            except Exception as e: info["client_saw"] = repr(e)[:80]
            f.proc.wait(10); info["process_returncode"] = f.proc.returncode  # -9 = SIGKILL
            # what the log holds after the crash (plain restart, no retry yet)
            f.start(); info["log_entries_after_crash_restart"] = f.config()["log_entries_at_start"]
            info["entry_survived_crash"] = info["log_entries_after_crash_restart"] == 3
            f.stop()
            # now the REAL capture-client path continues: the crashed statement (2) is submitted again by the client, then statement 3
            f.start()
            ok, rep = submit_and_export(f, items, run, first=2, total=4, retries=5, allow_retry=True)
            if ok is not True: info["detail"] = str(rep)[:400]
            e = exported(run)
            info["exactly_once"] = [e.count(G.leaf_input(x)) for x in items]
            sl = json.load(open(f"{run}/submit-log.json")) if os.path.exists(f"{run}/submit-log.json") else []
            info["submit_log"] = [{k: x[k] for k in ("index", "duplicate", "recovered")} for x in sl]
            info["leaves_in_log"] = len(e)
            ok = ok is True and len(e) == 4 and all(c == 1 for c in info["exactly_once"]) and info["process_returncode"] == -9
            # the retried statement's Receipt is the stored one when it had been stored
            stored = open(f"{f.dir}/state/receipts/000002.receipt.cbor", "rb").read()
            ret = open(f"{run}/returned/000002.receipt.cbor", "rb").read()
            info["returned_receipt_equals_stored"] = stored == ret
            ok &= info["returned_receipt_equals_stored"]
            info["journal_events"] = [x["event"] for x in f.journal()]
        except Exception as ex:
            ok = False; info["exception"] = repr(ex)
        finally: f.stop()
        info["ok"] = ok; allok &= ok; res[fp] = info
    return allok, res

# ------------------------------------------------------------------------------------------------ T5
def T5():
    rnd = random.Random(a.seed)
    f = Facade("t5", 19300, batch="1:10ms", cpint="100ms"); f.start()
    run = os.path.join(f.dir, "run"); n = a.chaos_n; items = [stmt(500 + i) for i in range(n)]
    stop, kills = threading.Event(), []
    def killer():
        time.sleep(0.3)
        while not stop.is_set():
            time.sleep(rnd.uniform(0.05, 0.6))
            if stop.is_set(): break
            f.kill(); kills.append(round(time.time(), 3))
            time.sleep(rnd.uniform(0.0, 0.2))
            try: f.start()
            except Exception as ex: kills.append(f"restart failed: {ex!r}")
    th = threading.Thread(target=killer); th.start()
    res = {"seed": a.seed, "statements": n}
    try:
        sd = os.path.join(run, "_statements"); write_stmts(sd, items)
        rc, o = client("submit", "--facade", f.url(), "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--statements", sd, "--out", run, "--retries", "60")
        res["submit_rc"] = rc; res["submit_out"] = o[-300:]
    finally:
        stop.set(); th.join()
        if f.proc.poll() is not None: f.start()
    rc, o = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", str(n), "--out", run)
    res["export_rc"] = rc
    ok, rep = s3check(run, n, True) if rc == 0 else (False, None)
    e = exported(run)
    res["leaves_in_log"] = len(e); res["distinct"] = len(set(e)); res["each_statement_exactly_once_in_order"] = e == [G.leaf_input(x) for x in items]
    res["kills"] = len([k for k in kills if not isinstance(k, str)]); res["restart_failures"] = [k for k in kills if isinstance(k, str)]
    j = f.journal(); ev = [x["event"] for x in j]
    res["journal_counts"] = {k: ev.count(k) for k in sorted(set(ev))}
    if os.path.exists(f"{run}/submit-log.json"):
        sl = json.load(open(f"{run}/submit-log.json")); res["retried_or_recovered"] = {"duplicate_flag": sum(x["duplicate"] for x in sl), "recovered_flag": sum(x["recovered"] for x in sl)}
    f.stop()
    return (res["submit_rc"] == 0 and rc == 0 and ok is True and res["each_statement_exactly_once_in_order"]), res

def T6():
    import base64, hashlib, subprocess as sp
    from cryptography.hazmat.primitives.asymmetric import ed25519
    res = {}; ok = True
    # (a) facade started with a pin that is not its signing key / with the wrong origin
    f = Facade("t6a", 19400); 
    for label, extra_env in (("wrong_pinned_vkey", "vkey"), ("wrong_origin", "origin")):
        other = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        name = ORIGIN
        kb = b"\x01" + other; vk = f"{name}+{hashlib.sha256(name.encode()+b'\n'+kb).digest()[:4].hex()}+{base64.b64encode(kb).decode()}"
        cmd = [os.path.join(a.bin, "s3-facade"), "--storage", f"{f.dir}/log-{label}", "--state", f"{f.dir}/state-{label}", "--origin", ORIGIN if label != "wrong_origin" else "other/origin",
               "--note-skey-file", os.path.join(a.note_keys, "note.skey"), "--note-vkey", vk if label == "wrong_pinned_vkey" else VKEY, "--cose-key", os.path.join(a.keys_dir, "ts.pem"),
               "--ts-iss", TS_ISS, "--expect-thumbprint", THUMB, "--register-addr", "127.0.0.1:19402", "--public-addr", "127.0.0.1:19403"]
        r = sp.run(cmd, capture_output=True, text=True, timeout=30)
        res[label] = {"returncode": r.returncode, "stderr_tail": r.stderr.strip().splitlines()[-1][:160]}
        ok &= r.returncode != 0
    # wrong Receipt-key thumbprint
    cmd = [os.path.join(a.bin, "s3-facade"), "--storage", f"{f.dir}/log-tp", "--state", f"{f.dir}/state-tp", "--origin", ORIGIN, "--note-skey-file", os.path.join(a.note_keys, "note.skey"), "--note-vkey", VKEY,
           "--cose-key", os.path.join(a.keys_dir, "ts.pem"), "--ts-iss", TS_ISS, "--expect-thumbprint", "00" * 32, "--register-addr", "127.0.0.1:19402", "--public-addr", "127.0.0.1:19403"]
    r = sp.run(cmd, capture_output=True, text=True, timeout=30); res["wrong_receipt_key_thumbprint"] = {"returncode": r.returncode, "stderr_tail": r.stderr.strip().splitlines()[-1][:160]}; ok &= r.returncode != 0
    # (b) capture client with a wrong pin / origin
    f = Facade("t6b", 19410); f.start()
    try:
        for x in range(2): f.post(stmt(900 + x))
        time.sleep(0.6)
        other2 = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw(); kb2 = b"\x01" + other2
        bad_vk = f"{ORIGIN}+{hashlib.sha256(ORIGIN.encode()+b'\n'+kb2).digest()[:4].hex()}+{base64.b64encode(kb2).decode()}"   # well-formed, but not the log's key
        rc1, o1 = client("export", "--public", f.purl(), "--note-vkey", bad_vk, "--origin", ORIGIN, "--expect-size", "2", "--out", os.path.join(f.dir, "bad1"))
        rc2, o2 = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", "other/origin", "--expect-size", "2", "--out", os.path.join(f.dir, "bad2"))
        rc3, o3 = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", "3", "--out", os.path.join(f.dir, "bad3"))
        rc4, o4 = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", "2", "--out", os.path.join(f.dir, "good"))
        res["client_wrong_pinned_key"] = {"rc": rc1, "out": o1.strip()[-120:]}; res["client_wrong_origin"] = {"rc": rc2, "out": o2.strip()[-120:]}
        res["client_wrong_expected_size"] = {"rc": rc3, "out": o3.strip()[-120:]}; res["client_correct"] = {"rc": rc4}
        ok &= rc1 != 0 and rc2 != 0 and rc3 != 0 and rc4 == 0
        # (c) forged checkpoint on the public endpoint: right origin, right format, signed by ANOTHER key
        f.stop()
        rogue = ed25519.Ed25519PrivateKey.generate(); rp = rogue.public_key().public_bytes_raw()
        kh = hashlib.sha256(ORIGIN.encode() + b"\n" + b"\x01" + rp).digest()[:4]
        text = f"{ORIGIN}\n99\n{base64.b64encode(b'r' * 32).decode()}\n".encode()
        forged = text + b"\n" + ("\u2014 " + ORIGIN + " " + base64.b64encode(kh + rogue.sign(text)).decode() + "\n").encode()
        open(f"{f.dir}/log/checkpoint", "wb").write(forged)
        f.cpint = "1h"; f.extra = ["--checkpoint-republish", "2h"]; f.start()   # no republication for an hour: the forged checkpoint stays what the public endpoint serves
        st, j = f.post(stmt(902))
        res["forged_checkpoint"] = {"http": st, "error": j.get("error"), "detail": str(j.get("detail"))[:140],
                                    "receipt_stored_for_index_2": os.path.exists(f"{f.dir}/state/receipts/000002.receipt.cbor")}
        ok &= st == 502 and j.get("error") == "E_CHECKPOINT_UNVERIFIED" and not res["forged_checkpoint"]["receipt_stored_for_index_2"]
    finally: f.stop()
    return ok, res

for t in a.only.split(","):
    t0 = time.time()
    try: ok, r = globals()[t]()
    except Exception as ex: ok, r = False, {"exception": repr(ex)}
    results[t] = {"ok": bool(ok), "seconds": round(time.time() - t0, 1), **({"observations": r} if isinstance(r, dict) else {"s3check": r})}
    print(t, "PASS" if ok else "FAIL", f"{time.time()-t0:.1f}s")
json.dump(results, open(os.path.join(OUT, "facade-tests.json"), "w"), indent=1, default=str)
print("ALL PASS" if all(v["ok"] for v in results.values()) else "FAILURES")
sys.exit(0 if all(v["ok"] for v in results.values()) else 1)
