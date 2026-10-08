package receipt

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"testing"

	"github.com/volmax-studio/p10-s3-prototype/internal/cborx"
)

func tempIssuer(t *testing.T, iss string) *Issuer {
	k, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	der, _ := x509.MarshalPKCS8PrivateKey(k)
	p := filepath.Join(t.TempDir(), "k.pem")
	os.WriteFile(p, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), 0o600)
	i, err := LoadIssuer(p, iss)
	if err != nil {
		t.Fatal(err)
	}
	return i
}

// The Receipt must equal, in every byte except the signature, the Receipt that the ratified S2b test tooling produced for the same inputs (ML-1 fixture).
func TestShapeEqualsFixtureReceipt(t *testing.T) {
	fx, err := os.ReadFile("../../../tests/offline/ml/fixtures/ml1-capture/receipts/000006.receipt.cbor")
	if err != nil {
		t.Skip("fixture receipt not present")
	}
	top, err := cborx.Decode(fx)
	if err != nil {
		t.Fatal(err)
	}
	a := top.Inner.Arr
	prot, _ := cborx.Decode(a[0].Bytes)
	claims, _ := prot.Get(15)
	issS, _ := claims.Get(1)
	// the proof is the bstr-wrapped array inside {396:{-1:[bstr]}}
	m396, _ := a[1].Get(396)
	pb := m396.Map[0][1].Arr[0].Bytes
	pr, err := cborx.Decode(pb)
	if err != nil {
		t.Fatal(err)
	}
	size, idx := pr.Arr[0].U, pr.Arr[1].U
	var path [][]byte
	for _, h := range pr.Arr[2].Arr {
		path = append(path, h.Bytes)
	}
	i := tempIssuer(t, string(issS.Bytes))
	root := bytes.Repeat([]byte{7}, 32)
	got, err := i.Issue(size, idx, path, root)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != len(fx) || !bytes.Equal(got[:len(got)-64], fx[:len(fx)-64]) {
		t.Fatalf("Receipt differs from the fixture Receipt outside the signature\n got %x\nwant %x", got[:len(got)-64], fx[:len(fx)-64])
	}
	if err := i.Verify(got, root); err != nil {
		t.Fatal(err)
	}
	if err := i.Verify(got, bytes.Repeat([]byte{8}, 32)); err == nil {
		t.Fatal("verified against the wrong root")
	}
}

func TestLowSAndDetached(t *testing.T) {
	i := tempIssuer(t, "x")
	for n := 0; n < 50; n++ {
		r, _ := i.Issue(1, 0, nil, bytes.Repeat([]byte{1}, 32))
		top, _ := cborx.Decode(r)
		sig := top.Inner.Arr[3].Bytes
		if !top.Inner.Arr[2].IsNull() || len(sig) != 64 || sig[32] >= 0x80 {
			t.Fatalf("not detached/low-S: %x", sig)
		}
	}
}
