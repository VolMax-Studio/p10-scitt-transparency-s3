package leafenc

import (
	"bytes"
	"testing"
)

func TestEncodeDecode(t *testing.T) {
	if HeaderLen != 61 || MaxStatement != 65474 {
		t.Fatalf("constants %d %d", HeaderLen, MaxStatement)
	}
	s := []byte("statement")
	li := Encode(s)
	if len(li) != 61+len(s) || !bytes.HasPrefix(li, []byte("P10-LeafEncodeV0\x00\x00\x00\x00 application/scitt-statement+cose")) {
		t.Fatalf("shape %q", li[:40])
	}
	got, err := Decode(li)
	if err != nil || !bytes.Equal(got, s) {
		t.Fatal("round trip")
	}
	li[len(li)-1] ^= 0
	if _, err := Decode(li[:len(li)-1]); err == nil {
		t.Fatal("length mismatch accepted")
	}
	if _, err := Decode(append([]byte("X"), li[1:]...)); err == nil {
		t.Fatal("bad prefix accepted")
	}
}
