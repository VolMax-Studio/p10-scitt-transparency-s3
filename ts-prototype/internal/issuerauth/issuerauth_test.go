package issuerauth

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/volmax-studio/p10-s3-prototype/internal/admit"
	"github.com/volmax-studio/p10-s3-prototype/internal/cborx"
	"github.com/volmax-studio/p10-s3-prototype/internal/receipt"
)

type kp struct {
	k  *ecdsa.PrivateKey
	tp [32]byte
}

func newKey(t *testing.T) kp {
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return kp{k, Thumbprint(k.X.FillBytes(make([]byte, 32)), k.Y.FillBytes(make([]byte, 32)))}
}

func coseKey(k *ecdsa.PrivateKey) []byte {
	return cborx.Map(cborx.Uint(1), cborx.Uint(2), cborx.Int(-1), cborx.Uint(1), cborx.Int(-2), cborx.Bstr(k.X.FillBytes(make([]byte, 32))), cborx.Int(-3), cborx.Bstr(k.Y.FillBytes(make([]byte, 32))))
}

func prot(alg int64, iss string, extra ...[]byte) []byte {
	kv := []([]byte){}
	if alg != 0 {
		kv = append(kv, cborx.Uint(1), cborx.Int(alg))
	}
	kv = append(kv, cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr(iss), cborx.Uint(2), cborx.Tstr("urn:test:sub")))
	return cborx.Map(append(kv, extra...)...)
}

func sign(k *ecdsa.PrivateKey, p, payload []byte) []byte {
	d := sha256.Sum256(receipt.SigStructure(p, payload))
	r, s, _ := ecdsa.Sign(rand.Reader, k, d[:])
	return append(r.FillBytes(make([]byte, 32)), s.FillBytes(make([]byte, 32))...)
}

func stmt(p []byte, payloadItem []byte, sig []byte) []byte {
	return cborx.Tag(18, cborx.Arr(cborx.Bstr(p), cborx.Map(), payloadItem, cborx.Bstr(sig)))
}

func table(t *testing.T, ks map[string]kp, rk kp) *Table {
	dir := t.TempDir()
	var es []entryJSON
	for iss, k := range ks {
		f := iss + ".cbor"
		os.WriteFile(filepath.Join(dir, f), coseKey(k.k), 0o644)
		es = append(es, entryJSON{iss, hex.EncodeToString(k.tp[:]), f})
	}
	b, _ := json.Marshal(map[string]any{"format": Format, "issuers": es})
	os.WriteFile(filepath.Join(dir, "issuers.json"), b, 0o644)
	tb, err := Load(filepath.Join(dir, "issuers.json"), rk.tp, "https://ts.example/x")
	if err != nil {
		t.Fatal(err)
	}
	return tb
}

func code(e *Error) string {
	if e == nil {
		return "OK"
	}
	return e.Code
}

func TestVerify(t *testing.T) {
	a, b, rk := newKey(t), newKey(t), newKey(t)
	tb := table(t, map[string]kp{"alice": a, "bob": b}, rk)
	payload := []byte("signed payload")
	good := func(iss string, k kp) []byte {
		p := prot(-7, iss)
		return stmt(p, cborx.Bstr(payload), sign(k.k, p, payload))
	}
	// the facade runs structural admission first; every case below also passes it, which is asserted
	check := func(name string, st, det []byte, have bool, want string) {
		if _, ae := admit.Check(st); ae != nil {
			t.Fatalf("%s: does not pass structural admission: %v", name, ae)
		}
		if got := code(tb.Verify(st, det, have)); got != want {
			t.Errorf("%s: got %s want %s", name, got, want)
		}
	}
	check("valid attached", good("alice", a), nil, false, "OK")
	check("valid other issuer", good("bob", b), nil, false, "OK")
	// detached
	pd := prot(-7, "alice")
	dst := stmt(pd, cborx.Null, sign(a.k, pd, payload))
	check("valid detached", dst, payload, true, "OK")
	check("detached, payload missing", dst, nil, false, "E_PAYLOAD_PART_MISSING")
	check("detached, wrong payload", dst, []byte("other"), true, "E_SIGNATURE_INVALID")
	check("detached, empty payload where non-empty was signed", dst, []byte{}, true, "E_SIGNATURE_INVALID")
	check("attached with payload part", good("alice", a), payload, true, "E_PAYLOAD_PART_UNEXPECTED")
	pe := prot(-7, "alice")
	est := stmt(pe, cborx.Null, sign(a.k, pe, []byte{}))
	check("detached empty payload signed as empty", est, []byte{}, true, "OK")
	// tampering
	g := good("alice", a)
	flipSig := append([]byte(nil), g...)
	flipSig[len(flipSig)-3] ^= 1
	check("signature bit flipped", flipSig, nil, false, "E_SIGNATURE_INVALID")
	flipPay := append([]byte(nil), g...)
	for i := range flipPay {
		if string(flipPay[i:min(i+len(payload), len(flipPay))]) == string(payload) {
			flipPay[i] ^= 1
			break
		}
	}
	check("payload tampered", flipPay, nil, false, "E_SIGNATURE_INVALID")
	// protected header tampered after signing: same signature, header differs (iss value changed to a different known issuer of the same length)
	p1 := prot(-7, "alice")
	sg := sign(a.k, p1, payload)
	check("protected header differs from the signed one", stmt(prot(-7, "alice", cborx.Uint(3), cborx.Tstr("text/plain")), cborx.Bstr(payload), sg), nil, false, "E_SIGNATURE_INVALID")
	// identity-to-key mismatch: signed by bob's key, claims alice
	pm := prot(-7, "alice")
	check("signed by another issuer's key", stmt(pm, cborx.Bstr(payload), sign(b.k, pm, payload)), nil, false, "E_SIGNATURE_INVALID")
	// unknown issuer (valid signature by an unconfigured key)
	c := newKey(t)
	pc := prot(-7, "carol")
	check("unknown iss", stmt(pc, cborx.Bstr(payload), sign(c.k, pc, payload)), nil, false, "E_ISSUER_UNKNOWN")
	// signature length
	check("short signature", stmt(pm, cborx.Bstr(payload), []byte{1, 2, 3}), nil, false, "E_SIGNATURE_INVALID")
	check("zero signature", stmt(pm, cborx.Bstr(payload), make([]byte, 64)), nil, false, "E_SIGNATURE_INVALID")
	// algorithms and labels
	for name, alg := range map[string]int64{"ES384": -35, "ES512": -36, "EdDSA": -8, "RS256": -257} {
		p := prot(alg, "alice")
		check("alg "+name, stmt(p, cborx.Bstr(payload), sign(a.k, p, payload)), nil, false, "E_ALG_UNSUPPORTED")
	}
	pn := prot(0, "alice")
	check("alg missing", stmt(pn, cborx.Bstr(payload), sign(a.k, pn, payload)), nil, false, "E_ALG_UNSUPPORTED")
	pt := cborx.Map(cborx.Uint(1), cborx.Tstr("ES256"), cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr("alice"), cborx.Uint(2), cborx.Tstr("s")))
	check("alg not an integer", stmt(pt, cborx.Bstr(payload), sign(a.k, pt, payload)), nil, false, "E_ALG_UNSUPPORTED")
	for name, ex := range map[string][]byte{"crit": cborx.Uint(2), "x5chain": cborx.Uint(33), "x5t": cborx.Uint(34), "unknown label": cborx.Uint(99)} {
		p := prot(-7, "alice", ex, cborx.Bstr([]byte("v")))
		check("label "+name, stmt(p, cborx.Bstr(payload), sign(a.k, p, payload)), nil, false, "E_PROTECTED_LABEL_UNSUPPORTED")
	}
	// kid
	pk := prot(-7, "alice", cborx.Uint(4), cborx.Bstr(a.tp[:]))
	check("kid equal to the configured thumbprint", stmt(pk, cborx.Bstr(payload), sign(a.k, pk, payload)), nil, false, "OK")
	pk2 := prot(-7, "alice", cborx.Uint(4), cborx.Bstr(b.tp[:]))
	check("kid names another issuer's key", stmt(pk2, cborx.Bstr(payload), sign(a.k, pk2, payload)), nil, false, "E_KID_MISMATCH")
	pk3 := prot(-7, "alice", cborx.Uint(4), cborx.Tstr("alice"))
	check("kid not a byte string", stmt(pk3, cborx.Bstr(payload), sign(a.k, pk3, payload)), nil, false, "E_KID_MISMATCH")
	// the original protected bytes are what is signed: a re-ordered (still valid) map must verify only with its own signature
	reord := cborx.Map(cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr("alice"), cborx.Uint(2), cborx.Tstr("s")), cborx.Uint(1), cborx.Int(-7))
	check("non-canonical map order, signed as submitted", stmt(reord, cborx.Bstr(payload), sign(a.k, reord, payload)), nil, false, "OK")
	check("non-canonical map order, signature of the canonical form", stmt(reord, cborx.Bstr(payload), sign(a.k, prot(-7, "alice"), payload)), nil, false, "E_SIGNATURE_INVALID")
}

func TestTableLoadRefusals(t *testing.T) {
	a, b, rk := newKey(t), newKey(t), newKey(t)
	dir := t.TempDir()
	write := func(name string, b []byte) { os.WriteFile(filepath.Join(dir, name), b, 0o644) }
	write("a.cbor", coseKey(a.k))
	write("b.cbor", coseKey(b.k))
	write("rk.cbor", coseKey(rk.k))
	write("junk.cbor", []byte{0xa0})
	priv := cborx.Map(cborx.Uint(1), cborx.Uint(2), cborx.Int(-1), cborx.Uint(1), cborx.Int(-2), cborx.Bstr(a.k.X.FillBytes(make([]byte, 32))), cborx.Int(-3), cborx.Bstr(a.k.Y.FillBytes(make([]byte, 32))), cborx.Int(-4), cborx.Bstr(a.k.D.FillBytes(make([]byte, 32))))
	write("priv.cbor", priv)
	hx := func(k kp) string { return hex.EncodeToString(k.tp[:]) }
	cases := map[string][]entryJSON{
		"no issuers":              {},
		"thumbprint mismatch":     {{"a", hx(b), "a.cbor"}},
		"duplicate iss":           {{"a", hx(a), "a.cbor"}, {"a", hx(b), "b.cbor"}},
		"shared key":              {{"a", hx(a), "a.cbor"}, {"a2", hx(a), "a.cbor"}},
		"receipt key as issuer":   {{"a", hx(rk), "rk.cbor"}},
		"iss equals ts_iss":       {{"https://ts.example/x", hx(a), "a.cbor"}},
		"not an EC2 key":          {{"a", hx(a), "junk.cbor"}},
		"private material in key": {{"a", hx(a), "priv.cbor"}},
		"missing key file":        {{"a", hx(a), "nope.cbor"}},
	}
	for name, es := range cases {
		b, _ := json.Marshal(map[string]any{"format": Format, "issuers": es})
		write("t.json", b)
		if _, err := Load(filepath.Join(dir, "t.json"), rk.tp, "https://ts.example/x"); err == nil {
			t.Errorf("%s: table was accepted", name)
		}
	}
	write("t.json", []byte(`{"format":"other","issuers":[]}`))
	if _, err := Load(filepath.Join(dir, "t.json"), rk.tp, "x"); err == nil {
		t.Error("wrong format accepted")
	}
	write("t.json", []byte(`{"format":"`+Format+`","issuers":[{"iss":"a","key_thumbprint":"`+hx(a)+`","cose_key_file":"a.cbor","extra":1}]}`))
	if _, err := Load(filepath.Join(dir, "t.json"), rk.tp, "x"); err == nil {
		t.Error("unknown field accepted")
	}
	if _, err := Load(filepath.Join(dir, "absent.json"), rk.tp, "x"); err == nil {
		t.Error("missing table accepted")
	}
}
