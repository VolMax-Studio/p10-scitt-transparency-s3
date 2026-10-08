// Package facade is the S3-owned SCITT registration front-end over a Tessera v1.0.4 POSIX log (CANDIDATE PROTOTYPE, NOT A SCRAPI-COMPLIANT TS).
//
// Registration of one Signed Statement: structural admission -> size limit on LeafEncodeV0(statement) -> persistent duplicate prevention ->
// Tessera append -> wait for a PUBLISHED checkpoint covering the entry -> verify that checkpoint's note signature (pinned key, expected origin)
// -> inclusion proof built from the public tiles for exactly that checkpoint's size -> reconstructed root must equal the checkpoint root and the
// public entry bundle must hold the submitted bytes -> issue the COSE Receipt (stable key, detached payload) over that root -> persist the
// Receipt together with the original signed checkpoint -> answer.
//
// Duplicate prevention does not rely on Tessera's best-effort antispam (deliberately not enabled). The truth is the log itself: at start the
// facade scans every integrated entry and keys it by SHA-256(leaf_input); registrations are serialized by one mutex (prereg I5/I6).
package facade

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/transparency-dev/formats/log"
	"github.com/transparency-dev/merkle/proof"
	"github.com/transparency-dev/merkle/rfc6962"
	"github.com/transparency-dev/tessera"
	"github.com/transparency-dev/tessera/api"
	"github.com/transparency-dev/tessera/api/layout"
	"github.com/transparency-dev/tessera/client"
	"github.com/transparency-dev/tessera/storage/posix"
	"golang.org/x/mod/sumdb/note"

	"github.com/volmax-studio/p10-s3-prototype/internal/admit"
	"github.com/volmax-studio/p10-s3-prototype/internal/leafenc"
	"github.com/volmax-studio/p10-s3-prototype/internal/receipt"
)

type Config struct {
	StorageDir, StateDir string
	Origin               string
	NoteSKeyFile         string // secret note key (outside the repository)
	NoteVKey             string // PINNED verifier key; checkpoints are accepted only if signed by it
	CosePEM, TsIss       string
	ExpectThumbprint     string // hex; the Receipt key must be the one committed in the instance
	PublicURL            string // base URL of this facade's own public read endpoint
	PublicReadURL        string // TEST HOOK: base URL the facade reads the public log through (default PublicURL), e.g. a fault-injecting proxy
	BatchSize            uint
	BatchAge             time.Duration
	CheckpointInterval   time.Duration
	CheckpointRepublish  time.Duration // 0: Tessera default
	PublishTimeout       time.Duration // deadline of the WHOLE finalization (checkpoint wait, tiles, entry bundle), counted from its start
	FetchTimeout         time.Duration // deadline of each single public HTTP read (0: none; the operation deadline still applies)
	MaxLeafInput         int
	FaultPoint           string // TEST ONLY: self-SIGKILL at pre-add | submitted | integrated | receipt-stored | pre-response
	FaultOnRequest       int    // 1-based count of admitted registration requests in this process
}

type Service struct {
	cfg      Config
	app      *tessera.Appender
	shutdown func(context.Context) error
	rd       tessera.LogReader
	verif    note.Verifier
	iss      *receipt.Issuer
	fetch    *client.HTTPFetcher
	mu       sync.Mutex
	known    map[[32]byte]uint64
	jf       *os.File
	nreq     int
	Scanned  uint64
}

type Result struct {
	Index       uint64 `json:"index"`
	TreeSize    uint64 `json:"tree_size"`
	LeafHash    string `json:"leaf_hash"`
	Root        string `json:"root"`
	ReceiptB64  string `json:"receipt_b64"`
	CheckpointB64 string `json:"checkpoint_b64"`
	Duplicate   bool   `json:"duplicate"`          // the bytes were already in the log; nothing was appended
	Recovered   bool   `json:"recovered,omitempty"` // the entry was found integrated without a stored Receipt (crash after integration); the Receipt was issued now
	ReceiptReused bool `json:"receipt_reused,omitempty"`
}

type HTTPError struct {
	Status int
	Code   string
	Detail string
}

func (e *HTTPError) Error() string { return fmt.Sprintf("%d %s: %s", e.Status, e.Code, e.Detail) }

func Open(ctx context.Context, cfg Config) (*Service, error) {
	skey, err := os.ReadFile(cfg.NoteSKeyFile)
	if err != nil {
		return nil, err
	}
	signer, err := note.NewSigner(string(bytes.TrimSpace(skey)))
	if err != nil {
		return nil, fmt.Errorf("note signer: %v", err)
	}
	if signer.Name() != cfg.Origin {
		return nil, fmt.Errorf("checkpoint origin is the signer name: %q != expected origin %q", signer.Name(), cfg.Origin)
	}
	verif, err := note.NewVerifier(cfg.NoteVKey)
	if err != nil {
		return nil, fmt.Errorf("pinned note verifier key: %v", err)
	}
	probe, err := note.Sign(&note.Note{Text: "pin-check\n"}, signer)
	if err != nil {
		return nil, err
	}
	if _, err := note.Open(probe, note.VerifierList(verif)); err != nil {
		return nil, fmt.Errorf("the signing key is not the pinned note key: %v", err)
	}
	iss, err := receipt.LoadIssuer(cfg.CosePEM, cfg.TsIss)
	if err != nil {
		return nil, err
	}
	if tp := iss.Thumbprint(); hex.EncodeToString(tp[:]) != cfg.ExpectThumbprint {
		return nil, fmt.Errorf("Receipt key thumbprint %x is not the committed %s", tp, cfg.ExpectThumbprint)
	}
	readURL := cfg.PublicURL
	if cfg.PublicReadURL != "" {
		readURL = cfg.PublicReadURL
	}
	u, err := url.Parse(readURL)
	if err != nil {
		return nil, err
	}
	fetch, err := client.NewHTTPFetcher(u, &http.Client{Timeout: cfg.FetchTimeout})
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Join(cfg.StateDir, "receipts"), 0o755); err != nil {
		return nil, err
	}
	drv, err := posix.New(ctx, posix.Config{Path: cfg.StorageDir})
	if err != nil {
		return nil, err
	}
	// Antispam is deliberately NOT enabled: it is best-effort and would give a false sense of deduplication.
	opts := tessera.NewAppendOptions().WithCheckpointSigner(signer).WithBatching(cfg.BatchSize, cfg.BatchAge).WithCheckpointInterval(cfg.CheckpointInterval)
	if cfg.CheckpointRepublish > 0 {
		opts = opts.WithCheckpointRepublishInterval(cfg.CheckpointRepublish)
	}
	app, shutdown, rd, err := tessera.NewAppender(ctx, drv, opts)
	if err != nil {
		return nil, err
	}
	s := &Service{cfg: cfg, app: app, shutdown: shutdown, rd: rd, verif: verif, iss: iss, fetch: fetch, known: map[[32]byte]uint64{}}
	if s.jf, err = os.OpenFile(filepath.Join(cfg.StateDir, "journal.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err != nil {
		return nil, err
	}
	if err := s.scan(ctx); err != nil {
		return nil, err
	}
	s.journal(map[string]any{"event": "start", "log_entries": s.Scanned})
	return s, nil
}

func (s *Service) Close(ctx context.Context) error {
	err := s.shutdown(ctx)
	s.jf.Close()
	return err
}

// scan rebuilds the duplicate index from the integrated entries of the log itself (authoritative; survives any crash of the facade).
func (s *Service) scan(ctx context.Context) error {
	size, err := s.rd.IntegratedSize(ctx)
	if err != nil {
		return fmt.Errorf("integrated size: %v", err)
	}
	for ri := range layout.Range(0, size, size) {
		raw, err := s.rd.ReadEntryBundle(ctx, ri.Index, ri.Partial)
		if err != nil {
			return fmt.Errorf("entry bundle %d: %v", ri.Index, err)
		}
		var b api.EntryBundle
		if err := b.UnmarshalText(raw); err != nil {
			return fmt.Errorf("entry bundle %d: %v", ri.Index, err)
		}
		for j := ri.First; j < ri.First+ri.N; j++ {
			idx := ri.Index*layout.EntryBundleWidth + uint64(j)
			h := sha256.Sum256(b.Entries[j])
			if prev, dup := s.known[h]; dup {
				return fmt.Errorf("INVARIANT VIOLATED: identical leaf inputs at indices %d and %d; refusing to start", prev, idx)
			}
			s.known[h] = idx
		}
	}
	s.Scanned = size
	return nil
}

func (s *Service) journal(m map[string]any) {
	m["t"] = time.Now().UTC().Format(time.RFC3339Nano)
	b, _ := json.Marshal(m)
	s.jf.Write(append(b, '\n'))
	s.jf.Sync()
}

func (s *Service) fault(point string) {
	if s.cfg.FaultPoint == point && s.nreq == s.cfg.FaultOnRequest {
		s.journal(map[string]any{"event": "fault", "point": point})
		syscall.Kill(os.Getpid(), syscall.SIGKILL)
		select {} // SIGKILL cannot be handled; never continue
	}
}

// Register performs one registration. stmt is the exact statement byte string; it is never re-encoded.
func (s *Service) Register(ctx context.Context, stmt []byte) (*Result, *HTTPError) {
	ctx = context.WithoutCancel(ctx) // an abandoned client request must not abort a half-done append
	s.mu.Lock()
	defer s.mu.Unlock()
	li := leafenc.Encode(stmt)
	if len(li) > s.cfg.MaxLeafInput {
		s.journal(map[string]any{"event": "reject", "code": "E_TOO_LARGE", "leaf_input_len": len(li)})
		return nil, &HTTPError{http.StatusRequestEntityTooLarge, "E_TOO_LARGE", fmt.Sprintf("LeafEncodeV0(statement) is %d bytes, limit %d (statement limit %d)", len(li), s.cfg.MaxLeafInput, s.cfg.MaxLeafInput-leafenc.HeaderLen)}
	}
	if _, aerr := admit.Check(stmt); aerr != nil {
		s.journal(map[string]any{"event": "reject", "code": aerr.Code})
		return nil, &HTTPError{http.StatusBadRequest, aerr.Code, aerr.Detail}
	}
	s.nreq++
	h := sha256.Sum256(li)
	hx := hex.EncodeToString(h[:])
	if idx, ok := s.known[h]; ok {
		s.journal(map[string]any{"event": "duplicate", "leaf_input_sha256": hx, "index": idx})
		return s.finalizeBounded(ctx, idx, li, true)
	}
	s.journal(map[string]any{"event": "intent", "leaf_input_sha256": hx})
	s.fault("pre-add")
	fut := s.app.Add(ctx, tessera.NewEntry(li))
	s.fault("submitted")
	ix, err := fut()
	if err != nil {
		return nil, &HTTPError{http.StatusInternalServerError, "E_APPEND", err.Error()}
	}
	s.known[h] = ix.Index
	s.journal(map[string]any{"event": "integrated", "leaf_input_sha256": hx, "index": ix.Index, "tessera_is_dup": ix.IsDup})
	s.fault("integrated")
	return s.finalizeBounded(ctx, ix.Index, li, false)
}

// finalizeBounded runs the finalization under its own deadline. The incoming ctx is already detached from the client connection (WithoutCancel, so a
// disconnect does not abort a half-done registration), which also removed any request deadline: the bound is created here, explicitly, and covers every public
// read below. A failure releases the registration mutex (the caller's defer), stores nothing, and leaves the entry in the log so that a retry of the
// same statement finalizes at its existing index without another append.
func (s *Service) finalizeBounded(ctx context.Context, idx uint64, li []byte, dup bool) (*Result, *HTTPError) {
	fctx, cancel := context.WithTimeout(ctx, s.cfg.PublishTimeout)
	defer cancel()
	res, herr := s.finalize(fctx, idx, li, dup)
	if herr != nil {
		s.journal(map[string]any{"event": "finalize-failed", "index": idx, "code": herr.Code, "http": herr.Status})
	}
	return res, herr
}

// readTracker wraps the public reads of one finalization. A failed read (transport error, per-request timeout, non-200 status other than 404) is recorded
// here instead of being inferred from error text, because the library wraps such errors with %v and the cause would be lost. A read failure is never
// reported as a data problem: it is a bounded 504, nothing is stored, and the same statement can be retried.
type readTracker struct{ err error }

func (t *readTracker) note(err error) error {
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		t.err = err
	}
	return err
}

func (t *readTracker) checkpoint(f *client.HTTPFetcher) func(context.Context) ([]byte, error) {
	return func(ctx context.Context) ([]byte, error) { b, err := f.ReadCheckpoint(ctx); return b, t.note(err) }
}
func (t *readTracker) tile(f *client.HTTPFetcher) client.TileFetcherFunc {
	return func(ctx context.Context, l, i uint64, p uint8) ([]byte, error) { b, err := f.ReadTile(ctx, l, i, p); return b, t.note(err) }
}
func (t *readTracker) bundle(f *client.HTTPFetcher) client.EntryBundleFetcherFunc {
	return func(ctx context.Context, i uint64, p uint8) ([]byte, error) { b, err := f.ReadEntryBundle(ctx, i, p); return b, t.note(err) }
}

func (t *readTracker) failure(ctx context.Context, stage string) *HTTPError {
	if t.err == nil && ctx.Err() == nil {
		return nil
	}
	code := "E_PUBLIC_READ_FAILED"
	if ctx.Err() != nil {
		code = "E_PUBLIC_READ_TIMEOUT"
	}
	return &HTTPError{http.StatusGatewayTimeout, code, fmt.Sprintf("public read failed or timed out (%s): %v", stage, t.err)}
}

type meta struct {
	Index      uint64 `json:"index"`
	TreeSize   uint64 `json:"tree_size"`
	LeafHash   string `json:"leaf_hash"`
	Root       string `json:"root"`
	Recovered  bool   `json:"recovered"`
	IssuedAt   string `json:"issued_at"`
	LeafInputSHA256 string `json:"leaf_input_sha256"`
}

func (s *Service) rpath(idx uint64, suffix string) string {
	return filepath.Join(s.cfg.StateDir, "receipts", fmt.Sprintf("%06d.%s", idx, suffix))
}

func writeAtomic(path string, data []byte) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	f.Close()
	if err := os.Rename(tmp, path); err != nil {
		return err
	}
	d, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

func (s *Service) finalize(ctx context.Context, idx uint64, li []byte, dup bool) (*Result, *HTTPError) {
	lh := rfc6962.DefaultHasher.HashLeaf(li)
	lsha := sha256.Sum256(li)
	// a stored Receipt (meta is written last) is returned as issued
	if mb, err := os.ReadFile(s.rpath(idx, "json")); err == nil {
		var m meta
		rec, e1 := os.ReadFile(s.rpath(idx, "receipt.cbor"))
		cp, e2 := os.ReadFile(s.rpath(idx, "checkpoint"))
		if json.Unmarshal(mb, &m) != nil || e1 != nil || e2 != nil || m.LeafHash != hex.EncodeToString(lh) || m.LeafInputSHA256 != hex.EncodeToString(lsha[:]) {
			return nil, &HTTPError{http.StatusInternalServerError, "E_STATE_CORRUPT", fmt.Sprintf("stored registration record for index %d does not match", idx)}
		}
		return &Result{Index: idx, TreeSize: m.TreeSize, LeafHash: m.LeafHash, Root: m.Root, ReceiptB64: base64.StdEncoding.EncodeToString(rec),
			CheckpointB64: base64.StdEncoding.EncodeToString(cp), Duplicate: dup, ReceiptReused: true}, nil
	}
	recovered := dup // known but no stored Receipt: issued after a crash between integration and Receipt storage
	rt := &readTracker{}
	var cpRaw []byte
	var size uint64
	var root []byte
	for cpRaw == nil {
		rt.err = nil
		raw, err := rt.checkpoint(s.fetch)(ctx)
		if err == nil {
			cp, _, _, perr := log.ParseCheckpoint(raw, s.cfg.Origin, s.verif)
			if perr != nil { // bad signature, wrong origin, malformed: fail closed, never issue a Receipt for an unverified checkpoint
				return nil, &HTTPError{http.StatusBadGateway, "E_CHECKPOINT_UNVERIFIED", perr.Error()}
			}
			if cp.Size > idx {
				cpRaw, size, root = raw, cp.Size, cp.Hash
				continue
			}
		}
		// not published yet (404 or smaller tree) or a read failure: poll again until the operation deadline
		select {
		case <-ctx.Done():
			if f := rt.failure(ctx, "checkpoint"); f != nil {
				return nil, f
			}
			return nil, &HTTPError{http.StatusGatewayTimeout, "E_PUBLICATION_TIMEOUT", fmt.Sprintf("no verified checkpoint covering index %d within %s", idx, s.cfg.PublishTimeout)}
		case <-time.After(50 * time.Millisecond):
		}
	}
	rt.err = nil
	pb, err := client.NewProofBuilder(ctx, size, rt.tile(s.fetch))
	if err != nil {
		return nil, &HTTPError{http.StatusInternalServerError, "E_PROOF", err.Error()}
	}
	path, err := pb.InclusionProof(ctx, idx)
	if err != nil {
		if f := rt.failure(ctx, "hash tiles"); f != nil {
			return nil, f
		}
		return nil, &HTTPError{http.StatusInternalServerError, "E_PROOF", err.Error()}
	}
	got, err := proof.RootFromInclusionProof(rfc6962.DefaultHasher, idx, size, lh, path)
	if err != nil || !bytes.Equal(got, root) {
		return nil, &HTTPError{http.StatusInternalServerError, "E_ROOT_MISMATCH", fmt.Sprintf("reconstructed root %x != checkpoint root %x (%v)", got, root, err)}
	}
	bundle, err := client.GetEntryBundle(ctx, rt.bundle(s.fetch), idx/layout.EntryBundleWidth, size)
	if err != nil {
		if f := rt.failure(ctx, "entry bundle"); f != nil {
			return nil, f
		}
	}
	if err != nil || int(idx%layout.EntryBundleWidth) >= len(bundle.Entries) || !bytes.Equal(bundle.Entries[idx%layout.EntryBundleWidth], li) {
		return nil, &HTTPError{http.StatusInternalServerError, "E_PUBLIC_ENTRY_MISMATCH", fmt.Sprintf("public entry bundle does not hold the submitted bytes at index %d (%v)", idx, err)}
	}
	rec, err := s.iss.Issue(size, idx, path, root)
	if err != nil {
		return nil, &HTTPError{http.StatusInternalServerError, "E_RECEIPT", err.Error()}
	}
	if err := s.iss.Verify(rec, root); err != nil {
		return nil, &HTTPError{http.StatusInternalServerError, "E_RECEIPT", err.Error()}
	}
	m := meta{Index: idx, TreeSize: size, LeafHash: hex.EncodeToString(lh), Root: hex.EncodeToString(root), Recovered: recovered, IssuedAt: time.Now().UTC().Format(time.RFC3339Nano), LeafInputSHA256: hex.EncodeToString(lsha[:])}
	mb, _ := json.MarshalIndent(m, "", " ")
	for _, w := range []struct {
		suffix string
		data   []byte
	}{{"receipt.cbor", rec}, {"checkpoint", cpRaw}, {"json", append(mb, '\n')}} { // meta last: its presence marks a complete record
		if err := writeAtomic(s.rpath(idx, w.suffix), w.data); err != nil {
			return nil, &HTTPError{http.StatusInternalServerError, "E_STATE_WRITE", err.Error()}
		}
	}
	s.journal(map[string]any{"event": "receipt", "index": idx, "tree_size": size, "recovered": recovered})
	s.fault("receipt-stored")
	return &Result{Index: idx, TreeSize: size, LeafHash: m.LeafHash, Root: m.Root, ReceiptB64: base64.StdEncoding.EncodeToString(rec),
		CheckpointB64: base64.StdEncoding.EncodeToString(cpRaw), Duplicate: dup, Recovered: recovered}, nil
}

func isTransient(err error) bool {
	var ue *url.Error
	return errors.As(err, &ue) || errors.Is(err, io.ErrUnexpectedEOF)
}

// Handler is the REGISTRATION endpoint (separate listener from the public read endpoint).
func (s *Service) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /register", func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(io.LimitReader(r.Body, int64(s.cfg.MaxLeafInput)+1))
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		res, herr := s.Register(r.Context(), body)
		w.Header().Set("Content-Type", "application/json")
		if herr != nil {
			w.WriteHeader(herr.Status)
			json.NewEncoder(w).Encode(map[string]string{"error": herr.Code, "detail": herr.Detail})
			return
		}
		s.fault("pre-response")
		if res.Duplicate {
			w.WriteHeader(http.StatusOK)
		} else {
			w.WriteHeader(http.StatusCreated)
		}
		json.NewEncoder(w).Encode(res)
	})
	mux.HandleFunc("GET /config", func(w http.ResponseWriter, r *http.Request) {
		tp := s.iss.Thumbprint()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{"origin": s.cfg.Origin, "note_vkey": s.cfg.NoteVKey, "ts_iss": s.cfg.TsIss, "cose_key_thumbprint": hex.EncodeToString(tp[:]),
			"max_leaf_input": s.cfg.MaxLeafInput, "max_statement": s.cfg.MaxLeafInput - leafenc.HeaderLen, "antispam": false, "log_entries_at_start": s.Scanned,
			"tessera": "github.com/transparency-dev/tessera v1.0.4 6bca8e8d5e23c9941f2b8a08f512b373f7131730", "storage": "posix"})
	})
	return mux
}
