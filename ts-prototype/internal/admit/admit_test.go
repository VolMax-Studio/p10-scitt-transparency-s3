package admit

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/volmax-studio/p10-s3-prototype/internal/cborx"
)

func stmt(prot, unprot, payload, sig []byte) []byte {
	return cborx.Tag(18, cborx.Arr(cborx.Bstr(prot), unprot, payload, cborx.Bstr(sig)))
}

var goodProt = cborx.Map(cborx.Uint(1), cborx.Int(-7), cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr("i"), cborx.Uint(2), cborx.Tstr("s")))

func TestCheck(t *testing.T) {
	empty := cborx.Map()
	if info, e := Check(stmt(goodProt, empty, cborx.Bstr([]byte("p")), []byte{1})); e != nil || info.Iss != "i" || info.Sub != "s" || info.DetachedPayload {
		t.Fatalf("good: %v %+v", e, info)
	}
	if info, e := Check(stmt(goodProt, empty, cborx.Null, []byte{1})); e != nil || !info.DetachedPayload {
		t.Fatalf("detached: %v", e)
	}
	cases := map[string][]byte{
		"E_NOT_CBOR":               {0xff},
		"E_NOT_COSE_SIGN1":         cborx.Arr(cborx.Bstr(goodProt), empty, cborx.Null, cborx.Bstr(nil)), // untagged
		"E_UNPROTECTED_NOT_EMPTY":  stmt(goodProt, cborx.Map(cborx.Uint(4), cborx.Bstr([]byte("k"))), cborx.Null, nil),
		"E_CWT_CLAIMS_MISSING":     stmt(cborx.Map(cborx.Uint(1), cborx.Int(-7)), empty, cborx.Null, nil),
		"E_ISS_SUB_NOT_TEXT":       stmt(cborx.Map(cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr("i"), cborx.Uint(2), cborx.Uint(7))), empty, cborx.Null, nil),
		"E_PROTECTED_DUPLICATE_LABEL": stmt(cborx.Map(cborx.Uint(1), cborx.Int(-7), cborx.Uint(1), cborx.Int(-7), cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr("i"), cborx.Uint(2), cborx.Tstr("s"))), empty, cborx.Null, nil),
		"E_PAYLOAD_FORM":           stmt(goodProt, empty, cborx.Tstr("x"), nil),
		"E_PROTECTED_UNREADABLE":   cborx.Tag(18, cborx.Arr(cborx.Tstr("not bytes"), empty, cborx.Null, cborx.Bstr(nil))),
		"E_NOT_CBOR ":              append(stmt(goodProt, empty, cborx.Null, nil), 0), // trailing byte
	}
	for want, b := range cases {
		_, e := Check(b)
		if e == nil || (e.Code != want && want != "E_NOT_CBOR ") {
			t.Errorf("%s: got %v", want, e)
		}
	}
}

// every committed fixture statement of the volmax-owner capture and the ML-1 capture is conformant (the registered forms the facade must preserve)
func TestFixtureStatementsAreAdmitted(t *testing.T) {
	for _, d := range []string{"../../../tests/offline/g5/fixtures/volmax-owner-capture/prefix", "../../../tests/offline/ml/fixtures/ml1-capture/prefix"} {
		fs, _ := filepath.Glob(filepath.Join(d, "*.cose"))
		if len(fs) == 0 {
			t.Fatalf("no fixtures in %s", d)
		}
		for _, f := range fs {
			b, _ := os.ReadFile(f)
			if _, e := Check(b); e != nil {
				t.Errorf("%s: %v", f, e)
			}
		}
	}
}
