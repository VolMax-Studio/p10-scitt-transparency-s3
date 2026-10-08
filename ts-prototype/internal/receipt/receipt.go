// Package receipt issues RFC 9942-style COSE Receipts (VDS 1 = RFC9162_SHA256) in the exact form the frozen S2b verifier consumes:
// tagged COSE_Sign1; protected {1:-7, 395:1, 15:{1:ts_iss}}; unprotected {396:{-1:[bstr(CBOR [tree_size, leaf_index, [path...]])]}};
// DETACHED payload (null); signature (ES256, P1363, low-S) over Sig_structure("Signature1", protected, h'', root).
package receipt

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"os"

	"github.com/volmax-studio/p10-s3-prototype/internal/cborx"
)

type Issuer struct {
	key   *ecdsa.PrivateKey
	TsIss string
}

func LoadIssuer(pemPath, tsIss string) (*Issuer, error) {
	raw, err := os.ReadFile(pemPath)
	if err != nil {
		return nil, err
	}
	blk, _ := pem.Decode(raw)
	if blk == nil {
		return nil, errors.New("receipt key: no PEM block")
	}
	var k any
	if k, err = x509.ParsePKCS8PrivateKey(blk.Bytes); err != nil {
		if k, err = x509.ParseECPrivateKey(blk.Bytes); err != nil {
			return nil, fmt.Errorf("receipt key: %v", err)
		}
	}
	ek, ok := k.(*ecdsa.PrivateKey)
	if !ok || ek.Curve != elliptic.P256() {
		return nil, errors.New("receipt key must be an ECDSA P-256 key")
	}
	return &Issuer{key: ek, TsIss: tsIss}, nil
}

func (i *Issuer) xy() ([]byte, []byte) {
	return i.key.PublicKey.X.FillBytes(make([]byte, 32)), i.key.PublicKey.Y.FillBytes(make([]byte, 32))
}

// Thumbprint is SHA-256 of the canonical-order COSE_Key {1:2, -1:1, -2:x, -3:y} (same construction as the S2b test tooling and the instance commitment).
func (i *Issuer) Thumbprint() [32]byte {
	x, y := i.xy()
	return sha256.Sum256(cborx.Map(cborx.Uint(1), cborx.Uint(2), cborx.Int(-1), cborx.Uint(1), cborx.Int(-2), cborx.Bstr(x), cborx.Int(-3), cborx.Bstr(y)))
}

func (i *Issuer) Protected() []byte {
	return cborx.Map(cborx.Uint(1), cborx.Int(-7), cborx.Uint(395), cborx.Uint(1), cborx.Uint(15), cborx.Map(cborx.Uint(1), cborx.Tstr(i.TsIss)))
}

func SigStructure(protected, payload []byte) []byte {
	return cborx.Arr(cborx.Tstr("Signature1"), cborx.Bstr(protected), cborx.Bstr(nil), cborx.Bstr(payload))
}

var n256 = elliptic.P256().Params().N

// Issue signs the reconstructed root. The caller guarantees root == RFC 9162 root reconstructed from (leaf hash, index, size, path).
func (i *Issuer) Issue(treeSize, index uint64, path [][]byte, root []byte) ([]byte, error) {
	if len(root) != 32 {
		return nil, errors.New("root must be 32 bytes")
	}
	prot := i.Protected()
	d := sha256.Sum256(SigStructure(prot, root))
	r, s, err := ecdsa.Sign(rand.Reader, i.key, d[:])
	if err != nil {
		return nil, err
	}
	if s.Cmp(new(big.Int).Rsh(n256, 1)) > 0 { // low-S
		s = new(big.Int).Sub(n256, s)
	}
	sig := append(r.FillBytes(make([]byte, 32)), s.FillBytes(make([]byte, 32))...)
	var ph [][]byte
	for _, h := range path {
		ph = append(ph, cborx.Bstr(h))
	}
	proof := cborx.Arr(cborx.Uint(treeSize), cborx.Uint(index), cborx.Arr(ph...))
	unprot := cborx.Map(cborx.Uint(396), cborx.Map(cborx.Int(-1), cborx.Arr(cborx.Bstr(proof))))
	return cborx.Tag(18, cborx.Arr(cborx.Bstr(prot), unprot, cborx.Null, cborx.Bstr(sig))), nil
}

// Verify checks a Receipt's signature against root with the issuer's own public key (used by tests; the frozen verifier is the authority).
func (i *Issuer) Verify(rec, root []byte) error {
	top, err := cborx.Decode(rec)
	if err != nil || top.Kind != cborx.KTag || top.Inner.Kind != cborx.KArray || len(top.Inner.Arr) != 4 {
		return errors.New("not a tagged COSE_Sign1")
	}
	a := top.Inner.Arr
	if !a[2].IsNull() || len(a[3].Bytes) != 64 {
		return errors.New("payload must be detached and the signature 64 bytes")
	}
	d := sha256.Sum256(SigStructure(a[0].Bytes, root))
	if !ecdsa.Verify(&i.key.PublicKey, d[:], new(big.Int).SetBytes(a[3].Bytes[:32]), new(big.Int).SetBytes(a[3].Bytes[32:])) {
		return errors.New("signature does not verify")
	}
	return nil
}
