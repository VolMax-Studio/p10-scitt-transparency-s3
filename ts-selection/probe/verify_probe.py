import sys, json, os, glob
sys.path.insert(0, "/home/user/volmax-studio/s2b-8eaa91c/tests/differential")
import gen_corpus as G
out = "/home/user/cand/probe-out"
r = json.load(open(out + "/probe-result.json"))
subs = [open(f, "rb").read() for f in sorted(glob.glob(out + "/retained/submissions/*.cose"))]
orig = [open(f, "rb").read() for f in sorted(glob.glob("/home/user/p10-scitt-transparency-s3/tests/offline/g5/fixtures/volmax-owner-capture/prefix/*.cose"))]
hs = [G.leaf_hash(s) for s in subs]
ok = True
def chk(name, cond, detail=""):
    global ok; ok &= bool(cond); print(("ok   " if cond else "FAIL ") + name + ((" :: " + detail) if detail and not cond else ""))
chk("submissions equal the committed prefix files", subs == orig)
for i, x in enumerate(r["registrations"]):
    chk(f"[{i}] index == position and tree_size == index+1", x["index"] == i and x["tree_size"] == i + 1, f"{x['index']} {x['tree_size']}")
    chk(f"[{i}] Tessera leaf hash == S2b leaf_hash(LeafEncodeV0)", x["leaf_hash"] == hs[i].hex())
    chk(f"[{i}] checkpoint root == S2b RFC 9162 MTH of the first {i+1} leaves", x["root"] == G.mth(hs[: i + 1]).hex())
    path = [h.hex() for h in G.path(i, hs[: i + 1])]
    chk(f"[{i}] inclusion path == S2b path", (x["inclusion_path"] or []) == path)
    chk(f"[{i}] not a duplicate", x["is_dup"] is False)
exp = [open(f, "rb").read() for f in sorted(glob.glob(out + "/retained/export/*.leaf_input"))]
chk("exported entry count == 5", len(exp) == 5)
chk("exported entries == LeafEncodeV0(submitted) byte for byte", exp == [G.leaf_input(s) for s in subs])
H = 17 + 4 + 32 + 8
chk("statement recovered from the exported entry == submitted bytes", [e[H:] for e in exp] == subs)
print("ALL OK" if ok else "SOME FAILED")
