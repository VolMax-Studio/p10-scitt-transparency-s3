// Package cborx is a minimal CBOR encoder and a strict decoder, just enough for COSE_Sign1 admission checks and Receipt emission.
// Definite lengths only; shortest-form integers are produced by the encoder and required by the decoder; no floats, no indefinite items.
package cborx

import (
	"errors"
	"fmt"
	"unicode/utf8"
)

// ---- encoder

func Head(major byte, n uint64) []byte {
	m := major << 5
	switch {
	case n < 24:
		return []byte{m | byte(n)}
	case n < 1<<8:
		return []byte{m | 24, byte(n)}
	case n < 1<<16:
		return []byte{m | 25, byte(n >> 8), byte(n)}
	case n < 1<<32:
		return []byte{m | 26, byte(n >> 24), byte(n >> 16), byte(n >> 8), byte(n)}
	}
	return []byte{m | 27, byte(n >> 56), byte(n >> 48), byte(n >> 40), byte(n >> 32), byte(n >> 24), byte(n >> 16), byte(n >> 8), byte(n)}
}

func Uint(n uint64) []byte { return Head(0, n) }
func Int(n int64) []byte {
	if n >= 0 {
		return Head(0, uint64(n))
	}
	return Head(1, uint64(-1-n))
}
func Bstr(b []byte) []byte { return append(Head(2, uint64(len(b))), b...) }
func Tstr(s string) []byte { return append(Head(3, uint64(len(s))), s...) }
func Tag(n uint64, inner []byte) []byte { return append(Head(6, n), inner...) }

var Null = []byte{0xf6}

func Arr(items ...[]byte) []byte {
	out := Head(4, uint64(len(items)))
	for _, i := range items {
		out = append(out, i...)
	}
	return out
}

// Map takes alternating encoded key, value items; the order given is the order written.
func Map(kv ...[]byte) []byte {
	if len(kv)%2 != 0 {
		panic("cborx.Map: odd number of items")
	}
	out := Head(5, uint64(len(kv)/2))
	for _, i := range kv {
		out = append(out, i...)
	}
	return out
}

// ---- decoder

type Kind int

const (
	KUint Kind = iota
	KNint
	KBytes
	KText
	KArray
	KMap
	KTag
	KSimple
)

type Item struct {
	Kind  Kind
	U     uint64 // KUint: value; KNint: -1-U; KTag: tag number; KSimple: simple value
	Bytes []byte // KBytes, KText (raw bytes)
	Arr   []Item
	Map   [][2]Item
	Inner *Item // KTag
	Raw   []byte
}

var (
	ErrTrailing = errors.New("trailing bytes after the CBOR item")
	ErrMalform  = errors.New("malformed or unsupported CBOR")
)

const maxDepth = 16

// Decode parses exactly one item that spans all of b.
func Decode(b []byte) (Item, error) {
	it, n, err := decode(b, 0)
	if err != nil {
		return Item{}, err
	}
	if n != len(b) {
		return Item{}, ErrTrailing
	}
	return it, nil
}

func decode(b []byte, depth int) (Item, int, error) {
	if depth > maxDepth {
		return Item{}, 0, fmt.Errorf("%w: nesting too deep", ErrMalform)
	}
	if len(b) == 0 {
		return Item{}, 0, fmt.Errorf("%w: truncated", ErrMalform)
	}
	major, ai := b[0]>>5, b[0]&0x1f
	pos := 1
	var arg uint64
	switch {
	case ai < 24:
		arg = uint64(ai)
	case ai >= 24 && ai <= 27:
		w := 1 << (ai - 24)
		if len(b) < pos+w {
			return Item{}, 0, fmt.Errorf("%w: truncated argument", ErrMalform)
		}
		for i := 0; i < w; i++ {
			arg = arg<<8 | uint64(b[pos+i])
		}
		pos += w
		min := [4]uint64{24, 1 << 8, 1 << 16, 1 << 32}[ai-24]
		if major != 7 && arg < min {
			return Item{}, 0, fmt.Errorf("%w: non-shortest integer", ErrMalform)
		}
	default:
		return Item{}, 0, fmt.Errorf("%w: indefinite length or reserved additional info", ErrMalform)
	}
	switch major {
	case 0:
		return Item{Kind: KUint, U: arg, Raw: b[:pos]}, pos, nil
	case 1:
		return Item{Kind: KNint, U: arg, Raw: b[:pos]}, pos, nil
	case 2, 3:
		if arg > uint64(len(b)-pos) {
			return Item{}, 0, fmt.Errorf("%w: truncated string", ErrMalform)
		}
		end := pos + int(arg)
		it := Item{Kind: KBytes, Bytes: b[pos:end], Raw: b[:end]}
		if major == 3 {
			it.Kind = KText
			if !utf8.Valid(it.Bytes) {
				return Item{}, 0, fmt.Errorf("%w: text string is not valid UTF-8", ErrMalform)
			}
		}
		return it, end, nil
	case 4, 5:
		if arg > uint64(len(b)-pos) { // each element needs at least one byte
			return Item{}, 0, fmt.Errorf("%w: truncated container", ErrMalform)
		}
		it := Item{Kind: KArray}
		if major == 5 {
			it.Kind = KMap
		}
		count := int(arg)
		if major == 5 {
			count *= 2
		}
		var els []Item
		for i := 0; i < count; i++ {
			e, n, err := decode(b[pos:], depth+1)
			if err != nil {
				return Item{}, 0, err
			}
			els = append(els, e)
			pos += n
		}
		if major == 4 {
			it.Arr = els
		} else {
			for i := 0; i < len(els); i += 2 {
				it.Map = append(it.Map, [2]Item{els[i], els[i+1]})
			}
		}
		it.Raw = b[:pos]
		return it, pos, nil
	case 6:
		in, n, err := decode(b[pos:], depth+1)
		if err != nil {
			return Item{}, 0, err
		}
		pos += n
		return Item{Kind: KTag, U: arg, Inner: &in, Raw: b[:pos]}, pos, nil
	default: // 7
		if ai >= 24 || (ai != 20 && ai != 21 && ai != 22 && ai != 23) {
			return Item{}, 0, fmt.Errorf("%w: unsupported simple/float value", ErrMalform)
		}
		return Item{Kind: KSimple, U: arg, Raw: b[:pos]}, pos, nil
	}
}

func (i Item) IsNull() bool { return i.Kind == KSimple && i.U == 22 }

// Get returns the value for an unsigned-integer map key; ok is false if absent. dup reports a duplicated key (of any kind compared by Raw bytes).
func (i Item) Get(label uint64) (v Item, ok bool) {
	for _, kv := range i.Map {
		if kv[0].Kind == KUint && kv[0].U == label {
			return kv[1], true
		}
	}
	return Item{}, false
}

// HasDuplicateKeys reports whether any two map keys have identical encodings.
func (i Item) HasDuplicateKeys() bool {
	seen := map[string]bool{}
	for _, kv := range i.Map {
		k := string(kv[0].Raw)
		if seen[k] {
			return true
		}
		seen[k] = true
	}
	return false
}
