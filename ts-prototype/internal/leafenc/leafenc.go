// Package leafenc implements LeafEncodeV0 (frozen S2 spec, as consumed by the pinned S2b verifier) for the single admitted format id.
package leafenc

import (
	"bytes"
	"encoding/binary"
	"errors"
)

const (
	FormatID = "application/scitt-statement+cose"
	// HeaderLen = len("P10-LeafEncodeV0\x00") + 4 + len(FormatID) + 8
	HeaderLen = 17 + 4 + 32 + 8
	// MaxLeafInput is the Tessera entry limit (tessera.DefaultEntrySizeLimit = 1<<16 - 1) and therefore bounds LeafEncodeV0(statement).
	MaxLeafInput = 1<<16 - 1
	MaxStatement = MaxLeafInput - HeaderLen // 65474
)

var prefix = append(append([]byte("P10-LeafEncodeV0\x00"), 0, 0, 0, byte(len(FormatID))), FormatID...)

func Encode(stmt []byte) []byte {
	b := append([]byte(nil), prefix...)
	b = binary.BigEndian.AppendUint64(b, uint64(len(stmt)))
	return append(b, stmt...)
}

var ErrFormat = errors.New("not a LeafEncodeV0 leaf input for the admitted format id")

// Decode returns the statement bytes of a LeafEncodeV0 leaf input; the returned slice aliases the input.
func Decode(li []byte) ([]byte, error) {
	if len(li) < HeaderLen || !bytes.Equal(li[:len(prefix)], prefix) {
		return nil, ErrFormat
	}
	n := binary.BigEndian.Uint64(li[len(prefix):HeaderLen])
	if n != uint64(len(li)-HeaderLen) {
		return nil, ErrFormat
	}
	return li[HeaderLen:], nil
}
