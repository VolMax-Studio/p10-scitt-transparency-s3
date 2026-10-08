// Package issuerauth authenticates the issuer of a Signed Statement against PRECONFIGURED keys (spec/registration-interface.md). It is the facade's
// one implemented registration check beyond structure: ES256 over the COSE Sig_structure built from the protected-header bytes exactly as submitted and the
// exact signed payload. It is authentication, not authorization, and it never reads the log: statements already registered (including declaration
// statements) confer no trust. The registered bytes are never touched.
package issuerauth

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"os"
	"path/filepath"
	"sort"

	"github.com/volmax-studio/p10-s3-prototype/internal/cborx"
	"github.com/volmax-studio/p10-s3-prototype/internal/receipt"
)

// Error carries the registration error code and HTTP status of spec/registration-interface.md §5.
type Error struct {
	Status int
	Code   string
	Detail string
}

func (e *Error) Error() string { return e.Code + ": " + e.Detail }

func fail(status int, code, f string, a ...any) *Error {
	return &Error{status, code, fmt.Sprintf(f, a...)}
}

type issuer struct {
	key *ecdsa.PublicKey
	tp  [32]byte
}

// Table is the preconfigured issuer table.
type Table struct {
	byIss  map[string]issuer
	Sha256 string // SHA-256 of the table file
}

type entryJSON struct {
	Iss        string `json:"iss"`
	Thumbprint string `json:"key_thumbprint"`
	KeyFile    string `json:"cose_key_file"`
}

const Format = "S3-ISSUER-TABLE-V0"

// Thumbprint is SHA-256 of {1:2, -1:1, -2:x, -3:y} in that order (the construction of the instance commitment and of the Receipt key thumbprint).
func Thumbprint(x, y []byte) [32]byte {
	return sha256.Sum256(cborx.Map(cborx.Uint(1), cborx.Uint(2), cborx.Int(-1), cborx.Uint(1), cborx.Int(-2), cborx.Bstr(x), cborx.Int(-3), cborx.Bstr(y)))
}

// negKey finds the entry for the negative label -n (n >= 1); a CBOR negative integer -1-u is stored with U == u.
func negKey(it cborx.Item, n uint64) (cborx.Item, bool) {
	for _, kv := range it.Map {
		if kv[0].Kind == cborx.KNint && kv[0].U == n-1 {
			return kv[1], true
		}
	}
	return cborx.Item{}, false
}

// parseCOSEKey accepts exactly a public EC2/P-256 COSE_Key (optional alg == -7) and returns the key.
func parseCOSEKey(raw []byte) (*ecdsa.PublicKey, []byte, []byte, error) {
	it, err := cborx.Decode(raw)
	if err != nil || it.Kind != cborx.KMap {
		return nil, nil, nil, errors.New("not a CBOR map")
	}
	if it.HasDuplicateKeys() {
		return nil, nil, nil, errors.New("duplicate label")
	}
	n := len(it.Map)
	kty, ok1 := it.Get(1)
	crv, ok2 := negKey(it, 1)
	x, ok3 := negKey(it, 2)
	y, ok4 := negKey(it, 3)
	if !ok1 || !ok2 || !ok3 || !ok4 || kty.Kind != cborx.KUint || kty.U != 2 || crv.Kind != cborx.KUint || crv.U != 1 || x.Kind != cborx.KBytes || y.Kind != cborx.KBytes || len(x.Bytes) != 32 || len(y.Bytes) != 32 {
		return nil, nil, nil, errors.New("must be an EC2 P-256 public key with 32-byte x and y")
	}
	want := 4
	if alg, ok := it.Get(3); ok {
		want = 5
		if alg.Kind != cborx.KNint || alg.U != 6 { // -7
			return nil, nil, nil, errors.New("alg, if present, must be -7")
		}
	}
	if n != want {
		return nil, nil, nil, errors.New("unexpected extra labels (private material or ambiguity)")
	}
	pk := &ecdsa.PublicKey{Curve: elliptic.P256(), X: new(big.Int).SetBytes(x.Bytes), Y: new(big.Int).SetBytes(y.Bytes)}
	if !pk.Curve.IsOnCurve(pk.X, pk.Y) {
		return nil, nil, nil, errors.New("point is not on P-256")
	}
	return pk, x.Bytes, y.Bytes, nil
}

// Load reads and validates the table. receiptThumbprint and tsIss are the facade's own Receipt-key thumbprint and Receipt issuer string: roles must not coincide.
func Load(path string, receiptThumbprint [32]byte, tsIss string) (*Table, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f struct {
		Format  string      `json:"format"`
		Issuers []entryJSON `json:"issuers"`
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&f); err != nil {
		return nil, fmt.Errorf("issuer table: %v", err)
	}
	if f.Format != Format {
		return nil, fmt.Errorf("issuer table: format %q, want %q", f.Format, Format)
	}
	if len(f.Issuers) == 0 {
		return nil, errors.New("issuer table: no issuers")
	}
	t := &Table{byIss: map[string]issuer{}}
	sum := sha256.Sum256(raw)
	t.Sha256 = hex.EncodeToString(sum[:])
	seenTP := map[[32]byte]string{}
	for _, e := range f.Issuers {
		if e.Iss == "" || e.Iss == tsIss {
			return nil, fmt.Errorf("issuer table: iss %q is empty or equals the Receipt issuer string", e.Iss)
		}
		if _, dup := t.byIss[e.Iss]; dup {
			return nil, fmt.Errorf("issuer table: duplicate iss %q", e.Iss)
		}
		kb, err := os.ReadFile(filepath.Join(filepath.Dir(path), e.KeyFile))
		if err != nil {
			return nil, fmt.Errorf("issuer table: %q: %v", e.Iss, err)
		}
		pk, x, y, err := parseCOSEKey(kb)
		if err != nil {
			return nil, fmt.Errorf("issuer table: %q key: %v", e.Iss, err)
		}
		tp := Thumbprint(x, y)
		if hex.EncodeToString(tp[:]) != e.Thumbprint {
			return nil, fmt.Errorf("issuer table: %q: key thumbprint %x differs from the declared %s", e.Iss, tp, e.Thumbprint)
		}
		if tp == receiptThumbprint {
			return nil, fmt.Errorf("issuer table: %q uses the Receipt-signing key", e.Iss)
		}
		if other, dup := seenTP[tp]; dup {
			return nil, fmt.Errorf("issuer table: %q and %q share a key", other, e.Iss)
		}
		seenTP[tp] = e.Iss
		t.byIss[e.Iss] = issuer{pk, tp}
	}
	return t, nil
}

// Entries lists (iss, thumbprint hex) sorted by iss, for /config and the run record.
func (t *Table) Entries() [][2]string {
	var out [][2]string
	for iss, e := range t.byIss {
		out = append(out, [2]string{iss, hex.EncodeToString(e.tp[:])})
	}
	sort.Slice(out, func(i, j int) bool { return out[i][0] < out[j][0] })
	return out
}

// Verify authenticates a statement that already passed structural admission. detached is the separately supplied payload (nil if none was supplied).
// It performs no state change.
func (t *Table) Verify(stmt []byte, detached []byte, haveDetached bool) *Error {
	top, err := cborx.Decode(stmt)
	if err != nil || top.Kind != cborx.KTag || top.Inner == nil || top.Inner.Kind != cborx.KArray || len(top.Inner.Arr) != 4 {
		return fail(http.StatusBadRequest, "E_NOT_COSE_SIGN1", "statement is not a COSE_Sign1")
	}
	a := top.Inner.Arr
	prot, payload, sig := a[0].Bytes, a[2], a[3].Bytes
	// payload form (spec §3)
	var signed []byte
	if payload.IsNull() {
		if !haveDetached {
			return fail(http.StatusBadRequest, "E_PAYLOAD_PART_MISSING", "the COSE payload is null and no payload part was supplied")
		}
		signed = detached
	} else {
		if haveDetached {
			return fail(http.StatusBadRequest, "E_PAYLOAD_PART_UNEXPECTED", "a payload part was supplied for a statement with an attached payload")
		}
		signed = payload.Bytes
	}
	// protected header profile (spec §4.4)
	ph, err := cborx.Decode(prot)
	if err != nil || ph.Kind != cborx.KMap {
		return fail(http.StatusBadRequest, "E_PROTECTED_UNREADABLE", "protected header")
	}
	for _, kv := range ph.Map {
		if kv[0].Kind != cborx.KUint || (kv[0].U != 1 && kv[0].U != 3 && kv[0].U != 4 && kv[0].U != 15) {
			return fail(http.StatusBadRequest, "E_PROTECTED_LABEL_UNSUPPORTED", "protected label %x is not one of 1, 3, 4, 15", kv[0].Raw)
		}
	}
	alg, ok := ph.Get(1)
	if !ok || alg.Kind != cborx.KNint || alg.U != 6 {
		return fail(http.StatusBadRequest, "E_ALG_UNSUPPORTED", "protected alg (label 1) must be the integer -7 (ES256)")
	}
	claims, _ := ph.Get(15)
	issItem, _ := claims.Get(1)
	iss, known := t.byIss[string(issItem.Bytes)]
	if !known {
		return fail(http.StatusForbidden, "E_ISSUER_UNKNOWN", "iss %q is not in the issuer table", string(issItem.Bytes))
	}
	if kid, has := ph.Get(4); has && (kid.Kind != cborx.KBytes || !bytes.Equal(kid.Bytes, iss.tp[:])) {
		return fail(http.StatusBadRequest, "E_KID_MISMATCH", "kid is not the thumbprint of the key configured for this iss")
	}
	if len(sig) != 64 {
		return fail(http.StatusForbidden, "E_SIGNATURE_INVALID", "signature is %d bytes, want 64", len(sig))
	}
	r, s := new(big.Int).SetBytes(sig[:32]), new(big.Int).SetBytes(sig[32:])
	d := sha256.Sum256(receipt.SigStructure(prot, signed))
	if !ecdsa.Verify(iss.key, d[:], r, s) {
		return fail(http.StatusForbidden, "E_SIGNATURE_INVALID", "the signature does not verify under the key configured for iss %q", string(issItem.Bytes))
	}
	return nil
}
