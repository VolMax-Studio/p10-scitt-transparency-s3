// Package admit is the facade's STRUCTURAL admission check for a Signed Statement (prereg I2/I4). It is a front-end policy of this prototype, not a
// frozen-chain rule. It does NOT verify the issuer signature (no trust anchors are configured), does not parse the payload and applies no
// Registration Policy beyond structure; bytes that pass are registered unchanged.
package admit

import (
	"fmt"

	"github.com/volmax-studio/p10-s3-prototype/internal/cborx"
)

type Error struct {
	Code   string
	Detail string
}

func (e *Error) Error() string { return e.Code + ": " + e.Detail }

func fail(code, f string, a ...any) *Error { return &Error{code, fmt.Sprintf(f, a...)} }

// Info is what admission learned about an accepted statement.
type Info struct {
	Iss, Sub        string
	DetachedPayload bool
}

// Check requires: one tagged (18) COSE_Sign1 array of 4; protected = bstr holding exactly one CBOR map (no duplicate labels) with label 15 (CWT claims)
// being a map with text-string iss (1) and sub (2); unprotected header exactly the empty map; payload bstr or null; signature bstr; no trailing bytes.
func Check(stmt []byte) (*Info, *Error) {
	top, err := cborx.Decode(stmt)
	if err != nil {
		return nil, fail("E_NOT_CBOR", "%v", err)
	}
	if top.Kind != cborx.KTag || top.U != 18 || top.Inner.Kind != cborx.KArray || len(top.Inner.Arr) != 4 {
		return nil, fail("E_NOT_COSE_SIGN1", "expected tag 18 over a 4-element array")
	}
	a := top.Inner.Arr
	if a[0].Kind != cborx.KBytes {
		return nil, fail("E_PROTECTED_UNREADABLE", "protected header is not a byte string")
	}
	if !(a[1].Kind == cborx.KMap && len(a[1].Map) == 0) {
		return nil, fail("E_UNPROTECTED_NOT_EMPTY", "the unprotected header must be the empty map (registered form is not normalized)")
	}
	info := &Info{}
	switch {
	case a[2].Kind == cborx.KBytes:
	case a[2].IsNull():
		info.DetachedPayload = true
	default:
		return nil, fail("E_PAYLOAD_FORM", "payload must be a byte string or null")
	}
	if a[3].Kind != cborx.KBytes {
		return nil, fail("E_SIGNATURE_FORM", "signature must be a byte string")
	}
	prot, err := cborx.Decode(a[0].Bytes)
	if err != nil || prot.Kind != cborx.KMap {
		return nil, fail("E_PROTECTED_UNREADABLE", "protected header does not decode to one CBOR map")
	}
	if prot.HasDuplicateKeys() {
		return nil, fail("E_PROTECTED_DUPLICATE_LABEL", "duplicate label in the protected header")
	}
	claims, ok := prot.Get(15)
	if !ok || claims.Kind != cborx.KMap {
		return nil, fail("E_CWT_CLAIMS_MISSING", "protected header lacks label 15 as a map")
	}
	if claims.HasDuplicateKeys() {
		return nil, fail("E_PROTECTED_DUPLICATE_LABEL", "duplicate label in the CWT claims")
	}
	iss, ok1 := claims.Get(1)
	sub, ok2 := claims.Get(2)
	if !ok1 || !ok2 || iss.Kind != cborx.KText || sub.Kind != cborx.KText {
		return nil, fail("E_ISS_SUB_NOT_TEXT", "CWT claims iss (1) and sub (2) must be text strings")
	}
	info.Iss, info.Sub = string(iss.Bytes), string(sub.Bytes)
	return info, nil
}
