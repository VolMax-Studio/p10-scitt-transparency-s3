#!/usr/bin/env python3
"""Public-read timeout tests (PROTOTYPE checks, not frozen-chain verdicts).

A stall proxy sits between the facade and its own public read endpoint (and between the capture client and it). It accepts a request but withholds the
response. Scenarios: stalled checkpoint, stalled hash tile, stalled entry bundle (facade side); stalled checkpoint with a client that disconnects early;
stalled checkpoint for `s3-capture export`.

  --mode pre   record the DEFECT of the unfixed build (expectations: no bounded failure)
  --mode post  require bounded failure (<= publish-timeout + slack), no Receipt issued or stored, mutex released (a stored-Receipt resubmission is answered at once),
               then restore the endpoint and retry the SAME statement: it must finalize at its existing index without another append

usage: timeout_tests.py --mode pre|post --bin DIR --py PY --s2b DIR --keys-dir DIR --note-keys DIR --fixture DIR --out DIR [--publish-timeout 3] [--only checkpoint,tile,entries,disconnect,client]
"""
import argparse, json, os, signal, subprocess, sys, threading, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stall_proxy import StallProxy

ap = argparse.ArgumentParser()
for k in ("mode", "bin", "py", "s2b", "keys-dir", "note-keys", "fixture", "out"): ap.add_argument("--" + k, required=True)
ap.add_argument("--publish-timeout", type=float, default=3.0)
ap.add_argument("--fetch-timeout", type=float, default=1.0)
ap.add_argument("--hang-wait", type=float, default=12.0, help="how long the test waits for a response before declaring it unbounded")
ap.add_argument("--only", default="checkpoint,tile,entries,disconnect,client")
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.s2b, "tests", "differential"))
import gen_corpus as G
meta = json.load(open(os.path.join(a.fixture, "PUBLIC_META.json")))
TS_ISS, THUMB = meta["identity"]["ts_iss"], meta["identity"]["ts_key_thumbprint"]
VKEY = open(os.path.join(a.note_keys, "note.vkey")).read().strip(); ORIGIN = VKEY.split("+")[0]
TS_PUB = os.path.join(a.fixture, "public", "ts.public.cose_key.cbor")
OUT = os.path.abspath(a.out); os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
POST = a.mode == "post"

def stmt(i):
    prot = G.cmap([(G.uint(1), G.integer(-7)), (G.uint(15), G.cmap([(G.uint(1), G.tstr("timeout-test")), (G.uint(2), G.tstr(f"urn:volmax:s3-test:timeout-{i}"))]))])
    return G.tag(18, G.arr([G.bstr(prot), G.cmap([]), G.bstr(f"payload-{i}".encode()), G.bstr(b"\0" * 64)]))

class Facade:
    def __init__(self, name, port, proxy_port):
        self.name, self.reg, self.pub, self.pp = name, port, port + 1, proxy_port
        self.dir = os.path.join(OUT, name); os.makedirs(self.dir, exist_ok=True); self.proc = None
    def start(self):
        cmd = [os.path.join(a.bin, "s3-facade"), "--storage", f"{self.dir}/log", "--state", f"{self.dir}/state", "--origin", ORIGIN,
               "--note-skey-file", os.path.join(a.note_keys, "note.skey"), "--note-vkey", VKEY, "--cose-key", os.path.join(a.keys_dir, "ts.pem"), "--ts-iss", TS_ISS,
               "--expect-thumbprint", THUMB, "--register-addr", f"127.0.0.1:{self.reg}", "--public-addr", f"127.0.0.1:{self.pub}", "--checkpoint-interval", "100ms",
               "--publish-timeout", f"{a.publish_timeout}s", "--public-read-url", f"http://127.0.0.1:{self.pp}/"]
        if POST: cmd += ["--fetch-timeout", f"{a.fetch_timeout}s"]
        self.err = open(os.path.join(self.dir, "facade.err"), "wb")
        self.proc = subprocess.Popen(cmd, stderr=self.err, stdout=subprocess.DEVNULL)
        for _ in range(100):
            if self.proc.poll() is not None: raise RuntimeError("facade exited on start")
            try: urllib.request.urlopen(self.url() + "/config", timeout=2); return
            except Exception: time.sleep(0.1)
        raise RuntimeError("not ready")
    def url(self): return f"http://127.0.0.1:{self.reg}"
    def purl(self): return f"http://127.0.0.1:{self.pub}"
    def post(self, data, timeout):
        t0 = time.monotonic()
        rq = urllib.request.Request(self.url() + "/register", data=data, method="POST", headers={"Content-Type": "application/cose"})
        try:
            r = urllib.request.urlopen(rq, timeout=timeout); return r.status, json.loads(r.read()), time.monotonic() - t0
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read()), time.monotonic() - t0
        except Exception as e: return None, {"client_error": repr(e)[:100]}, time.monotonic() - t0
    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try: self.proc.wait(20)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
    def kill(self):
        if self.proc and self.proc.poll() is None: self.proc.kill(); self.proc.wait()
    def journal(self):
        p = f"{self.dir}/state/journal.jsonl"; return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    def stored(self, i): return [os.path.exists(f"{self.dir}/state/receipts/{i:06d}.{x}") for x in ("receipt.cbor", "checkpoint", "json")]

def client(cmd, *args):
    t0 = time.monotonic()
    r = subprocess.run([os.path.join(a.bin, "s3-capture"), cmd, *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()[-200:], time.monotonic() - t0

def submit_files(f, run, items, first, proxy_port):
    d = os.path.join(run, f"_st{first}"); os.makedirs(d, exist_ok=True)
    for i, s in enumerate(items): open(f"{d}/{first+i:06d}.cose", "wb").write(s)
    return client("submit", "--facade", f.url(), "--public", f"http://127.0.0.1:{proxy_port}", "--note-vkey", VKEY, "--origin", ORIGIN, "--statements", d, "--out", run)

def finish_and_check(f, run, n):
    rc, o, _ = client("export", "--public", f.purl(), "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", str(n), "--out", run)
    if rc: return False, o
    r = subprocess.run([a.py, "-B", os.path.join(HERE, "s3check.py"), "--run", run, "--s2b", a.s2b, "--note-vkey", VKEY, "--origin", ORIGIN, "--ts-pub", TS_PUB, "--ts-iss", TS_ISS,
                        "--out", os.path.join(run, "s3check.json"), "--expect", str(n), "--allow-retry"], capture_output=True, text=True)
    open(os.path.join(run, "s3check.out"), "w").write(r.stdout + r.stderr)
    return r.returncode == 0, "s3check " + ("ALL OK" if r.returncode == 0 else "FAILURES")

def facade_scenario(kind, port):
    px = StallProxy(upstream_port=port + 1)
    f = Facade(f"fs-{kind}", port, px.port); f.start(); res = {"stalled_resource": kind}; ok = True
    try:
        run = os.path.join(f.dir, "run"); s0, s1 = stmt(0), stmt(1)
        rc, o, _ = submit_files(f, run, [s0], 0, px.port); assert rc == 0, o
        px.stall(kind)
        box = {}
        def first(): box["r"] = f.post(s1, a.hang_wait)
        def probe():                                   # resubmission of the already-registered S0: needs only the mutex, no network
            time.sleep(1.0); box["probe"] = f.post(s0, a.hang_wait)
        th = [threading.Thread(target=first), threading.Thread(target=probe)]
        [t.start() for t in th]; [t.join() for t in th]
        st, body, el = box["r"]; pst, pbody, pel = box["probe"]
        res["stalled_request_withheld_by_proxy"] = len(px.stalled)
        res["first_registration"] = {"http": st, "error": body.get("error") or body.get("client_error"), "elapsed_s": round(el, 2)}
        res["probe_stored_receipt_resubmission"] = {"http": pst, "elapsed_s": round(pel, 2)}
        res["receipt_files_for_index_1 (receipt,checkpoint,meta)"] = f.stored(1)
        if POST:
            bound = a.publish_timeout + 2.0
            cond = [st == 504 and el <= bound, pst == 200 and pbody.get("duplicate") and pel <= bound + 1.0, not any(f.stored(1))]
            res["bounded_failure"], res["mutex_released_probe_answered"], res["no_receipt_stored"] = cond
            ok &= all(cond)
        else:   # defect reproduction: the request never completes within hang_wait although publish-timeout is far shorter
            res["defect_reproduced_no_bounded_failure"] = st is None and el >= a.hang_wait - 0.5
            res["defect_reproduced_mutex_held_probe_blocked"] = pst is None and pel >= a.hang_wait - 1.5
            ok &= res["defect_reproduced_no_bounded_failure"] and res["defect_reproduced_mutex_held_probe_blocked"]
        # restore the endpoint
        px.release()
        if POST:
            time.sleep(0.3)
            jn_before = [j for j in f.journal() if j["event"] == "intent"]
            rc, o, _ = submit_files(f, run, [s1], 1, px.port)       # the SAME statement, through the real client
            fin, detail = finish_and_check(f, run, 2) if rc == 0 else (False, o)
            sl = json.load(open(f"{run}/submit-log.json"))[-1] if rc == 0 else {}
            jn_after = [j for j in f.journal() if j["event"] == "intent"]
            res["retry_after_restore"] = {"client_rc": rc, "index": sl.get("index"), "duplicate": sl.get("duplicate"), "recovered": sl.get("recovered"),
                                          "intents_before": len(jn_before), "intents_after": len(jn_after), "checks": detail}
            ok &= rc == 0 and sl.get("index") == 1 and sl.get("duplicate") is True and len(jn_after) == len(jn_before) and fin
        else:
            time.sleep(1.0)
            res["after_release_pre_fix_note"] = "stalled connections were closed by the proxy on release; the facade's blocked finalization could only continue then"
        res["journal_events"] = [j["event"] for j in f.journal()]
        return ok, res
    finally:
        f.kill(); px.close()

def disconnect_scenario(port):
    px = StallProxy(upstream_port=port + 1)
    f = Facade("fs-disconnect", port, px.port); f.start(); res = {}; ok = True
    try:
        run = os.path.join(f.dir, "run"); s0, s1 = stmt(10), stmt(11)
        rc, o, _ = submit_files(f, run, [s0], 0, px.port); assert rc == 0, o
        px.stall("checkpoint")
        t0 = time.time()
        st, body, el = f.post(s1, 1.0)                  # the client gives up after 1 s (disconnect)
        res["client"] = {"http": st, "client_error": body.get("client_error"), "elapsed_s": round(el, 2)}
        time.sleep(a.publish_timeout + 1.5)
        j = f.journal(); ev = [x["event"] for x in j]
        fin = [x for x in j if x["event"] == "finalize-failed"]
        res["facade_kept_going_after_disconnect_until_its_own_deadline"] = bool(fin)
        if fin:
            t_int = [x for x in j if x["event"] == "integrated"][-1]["t"]
            from datetime import datetime
            d = (datetime.fromisoformat(fin[0]["t"].replace("Z", "+00:00")) - datetime.fromisoformat(t_int.replace("Z", "+00:00"))).total_seconds()
            res["integrated_to_finalize_failed_s"] = round(d, 2); res["finalize_failed_code"] = fin[0].get("code")
            ok &= d >= a.publish_timeout - 0.3 and d <= a.publish_timeout + 1.5
        pst, pbody, pel = f.post(s0, 5.0)
        res["mutex_released_probe"] = {"http": pst, "elapsed_s": round(pel, 2)}
        res["no_receipt_stored"] = not any(f.stored(1))
        ok &= bool(fin) and pst == 200 and pel < 2.0 and res["no_receipt_stored"] and st is None
        return (ok if POST else False), res
    finally:
        f.kill(); px.close()

def client_scenario(port):
    px = StallProxy(upstream_port=port + 1)
    f = Facade("fs-client", port, px.port); f.start(); res = {}; ok = True
    try:
        run = os.path.join(f.dir, "run")
        rc, o, _ = submit_files(f, run, [stmt(20)], 0, px.port); assert rc == 0, o
        px.stall("checkpoint")
        args = ["--public", f"http://127.0.0.1:{px.port}", "--note-vkey", VKEY, "--origin", ORIGIN, "--expect-size", "1", "--out", os.path.join(run, "x")]
        if POST: args += ["--timeout", "3s"]
        rc, o, el = client("export", *args)
        res["export_with_stalled_checkpoint"] = {"rc": rc, "elapsed_s": round(el, 2), "out": o[-100:]}
        if POST: ok &= rc != 0 and el <= 3 + 2.0
        else: res["note"] = "no --timeout flag in the unfixed build: bounded only by the 20 s per-request HTTP timeout"
        return ok, res
    finally:
        f.kill(); px.close()

results = {"mode": a.mode, "publish_timeout_s": a.publish_timeout, "fetch_timeout_s": a.fetch_timeout if POST else None}
port = 19600
for k in a.only.split(","):
    t0 = time.time()
    try:
        if k in ("checkpoint", "tile", "entries"): ok, r = facade_scenario(k, port)
        elif k == "disconnect": ok, r = disconnect_scenario(port)
        elif k == "client": ok, r = client_scenario(port)
        else: raise SystemExit("unknown scenario " + k)
    except Exception as ex: ok, r = False, {"exception": repr(ex)}
    port += 10
    results[k] = {"ok": bool(ok), "seconds": round(time.time() - t0, 1), **r}
    print(k, "OK" if ok else "NOT OK", f"{time.time()-t0:.1f}s", flush=True)
json.dump(results, open(os.path.join(OUT, f"timeout-tests-{a.mode}.json"), "w"), indent=1, default=str)
good = all(v["ok"] for k, v in results.items() if isinstance(v, dict) and "ok" in v)
print(("DEFECT REPRODUCED (all scenarios)" if good else "NOT AS EXPECTED") if not POST else ("ALL PASS" if good else "FAILURES"))
sys.exit(0 if good else 1)
