package cborx

import (
	"bytes"
	"testing"
)

func TestRoundTripAndStrictness(t *testing.T) {
	enc := Map(Uint(1), Int(-7), Uint(395), Uint(1), Uint(15), Map(Uint(1), Tstr("é")))
	it, err := Decode(enc)
	if err != nil || it.Kind != KMap || len(it.Map) != 3 {
		t.Fatalf("decode: %v %+v", err, it)
	}
	if v, ok := it.Get(395); !ok || v.U != 1 {
		t.Fatal("Get(395)")
	}
	if !bytes.Equal(it.Raw, enc) {
		t.Fatal("Raw")
	}
	for name, bad := range map[string][]byte{
		"trailing":      append(append([]byte{}, enc...), 0),
		"non-shortest":  {0x18, 0x05},
		"indefinite":    {0x9f, 0xff},
		"truncated str": {0x43, 1, 2},
		"bad utf8":      {0x62, 0xff, 0xfe},
		"float":         {0xf9, 0, 0},
		"huge array":    {0x9b, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
	} {
		if _, err := Decode(bad); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
	dup := Map(Uint(1), Uint(1), Uint(1), Uint(2))
	d, _ := Decode(dup)
	if !d.HasDuplicateKeys() {
		t.Error("duplicate keys not detected")
	}
}
