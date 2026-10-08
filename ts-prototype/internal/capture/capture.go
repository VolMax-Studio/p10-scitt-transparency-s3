// Package capture is the capture client's HTTP-only view of the log: it reads checkpoints, hash tiles and entry bundles from the PUBLIC read
// endpoint, retains every response byte-for-byte, and verifies what it read (checkpoint note signature with the pinned key and expected origin;
// every exported leaf proves into the checkpoint root through the fetched tiles). It has no access to the storage directory and takes no
// submission files as input.
package capture

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"time"

	"github.com/transparency-dev/formats/log"
	"github.com/transparency-dev/merkle/proof"
	"github.com/transparency-dev/merkle/rfc6962"
	"github.com/transparency-dev/tessera/api"
	"github.com/transparency-dev/tessera/api/layout"
	"github.com/transparency-dev/tessera/client"
	"golang.org/x/mod/sumdb/note"
)

type Public struct {
	Base    *url.URL
	HC      *http.Client
	SaveDir string // raw responses are written to SaveDir/<resource path> when set
	Verif   note.Verifier
	Origin  string
}

func NewPublic(base, vkey, origin, saveDir string) (*Public, error) {
	u, err := url.Parse(base)
	if err != nil {
		return nil, err
	}
	if u.Path == "" || u.Path[len(u.Path)-1] != '/' {
		u.Path += "/"
	}
	v, err := note.NewVerifier(vkey)
	if err != nil {
		return nil, fmt.Errorf("pinned note verifier key: %v", err)
	}
	return &Public{Base: u, HC: &http.Client{Timeout: 20 * time.Second}, SaveDir: saveDir, Verif: v, Origin: origin}, nil
}

func (p *Public) get(ctx context.Context, rel string) ([]byte, error) {
	u, _ := p.Base.Parse(rel)
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	r, err := p.HC.Do(req)
	if err != nil {
		return nil, err
	}
	defer r.Body.Close()
	if r.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("get(%q): %w", u, os.ErrNotExist)
	}
	if r.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("get(%q): status %d", u, r.StatusCode)
	}
	b, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	if p.SaveDir != "" {
		dst := filepath.Join(p.SaveDir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return nil, err
		}
		if err := os.WriteFile(dst, b, 0o644); err != nil {
			return nil, err
		}
	}
	return b, nil
}

func (p *Public) ReadCheckpoint(ctx context.Context) ([]byte, error) { return p.get(ctx, layout.CheckpointPath) }

func (p *Public) ReadTile(ctx context.Context, l, i uint64, pp uint8) ([]byte, error) {
	b, err := p.get(ctx, layout.TilePath(l, i, pp))
	if errors.Is(err, os.ErrNotExist) && pp > 0 { // the partial tile was superseded by the full one
		return p.get(ctx, layout.TilePath(l, i, 0))
	}
	return b, err
}

func (p *Public) ReadEntryBundle(ctx context.Context, i uint64, pp uint8) ([]byte, error) {
	b, err := p.get(ctx, layout.EntriesPath(i, pp))
	if errors.Is(err, os.ErrNotExist) && pp > 0 {
		return p.get(ctx, layout.EntriesPath(i, 0))
	}
	return b, err
}

// Checkpoint fetches and VERIFIES (pinned key, expected origin) the current checkpoint; raw is the exact served bytes.
func (p *Public) Checkpoint(ctx context.Context) (*log.Checkpoint, []byte, error) {
	raw, err := p.ReadCheckpoint(ctx)
	if err != nil {
		return nil, nil, err
	}
	cp, _, _, err := log.ParseCheckpoint(raw, p.Origin, p.Verif)
	if err != nil {
		return nil, raw, fmt.Errorf("%w: %v", ErrCheckpointUnverified, err)
	}
	return cp, raw, nil
}

// ErrCheckpointUnverified: the served checkpoint is not signed by the pinned key for the expected origin (or is malformed). Never retried.
var ErrCheckpointUnverified = errors.New("checkpoint failed verification")

// WaitCheckpointSize polls until a verified checkpoint of exactly size has been published.
func (p *Public) WaitCheckpointSize(ctx context.Context, size uint64, timeout time.Duration) (*log.Checkpoint, []byte, error) {
	deadline := time.Now().Add(timeout)
	for {
		cp, raw, err := p.Checkpoint(ctx)
		if errors.Is(err, ErrCheckpointUnverified) {
			return nil, nil, err
		}
		if err == nil && cp.Size == size {
			return cp, raw, nil
		}
		if err == nil && cp.Size > size {
			return nil, nil, fmt.Errorf("the log has %d entries, expected %d (an extra writer, or a registration not yet accounted for)", cp.Size, size)
		}
		if time.Now().After(deadline) {
			return nil, nil, fmt.Errorf("no verified checkpoint of size %d within %s (last: %v)", size, timeout, err)
		}
		time.Sleep(100 * time.Millisecond)
	}
}

// ExportResult describes a verified export of [0,size).
type ExportResult struct {
	Size       uint64   `json:"size"`
	Root       string   `json:"root"`
	LeafInputs [][]byte `json:"-"`
}

// Export reads every entry bundle and checks each entry against the checkpoint through the public tiles.
func (p *Public) Export(ctx context.Context, cp *log.Checkpoint) (*ExportResult, error) {
	var leaves [][]byte
	for ri := range layout.Range(0, cp.Size, cp.Size) {
		raw, err := p.ReadEntryBundle(ctx, ri.Index, ri.Partial)
		if err != nil {
			return nil, err
		}
		var b api.EntryBundle
		if err := b.UnmarshalText(raw); err != nil {
			return nil, fmt.Errorf("entry bundle %d: %v", ri.Index, err)
		}
		if len(b.Entries) < int(ri.First+ri.N) {
			return nil, fmt.Errorf("entry bundle %d holds %d entries, need %d", ri.Index, len(b.Entries), ri.First+ri.N)
		}
		leaves = append(leaves, b.Entries[ri.First:ri.First+ri.N]...)
	}
	if uint64(len(leaves)) != cp.Size {
		return nil, fmt.Errorf("exported %d entries for a tree of size %d", len(leaves), cp.Size)
	}
	pb, err := client.NewProofBuilder(ctx, cp.Size, p.ReadTile)
	if err != nil {
		return nil, err
	}
	for i, li := range leaves {
		path, err := pb.InclusionProof(ctx, uint64(i))
		if err != nil {
			return nil, fmt.Errorf("proof for %d: %v", i, err)
		}
		root, err := proof.RootFromInclusionProof(rfc6962.DefaultHasher, uint64(i), cp.Size, rfc6962.DefaultHasher.HashLeaf(li), path)
		if err != nil || !bytes.Equal(root, cp.Hash) {
			return nil, fmt.Errorf("exported entry %d does not prove into the checkpoint root (%v)", i, err)
		}
	}
	return &ExportResult{Size: cp.Size, Root: fmt.Sprintf("%x", cp.Hash), LeafInputs: leaves}, nil
}
