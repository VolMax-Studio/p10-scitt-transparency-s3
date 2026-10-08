// Capability probe for transparency-dev/tessera v1.0.4 (non-normative; selection evidence only; NOT a transparency service).
// Appends LeafEncodeV0 leaf inputs sequentially to a POSIX-storage log, records per-registration (index, checkpoint, inclusion proof),
// exports the full ordered prefix from the entry bundles on disk, and runs three side probes (entry-size boundary, duplicates, restart).
package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/transparency-dev/formats/log"
	"github.com/transparency-dev/merkle/rfc6962"
	"github.com/transparency-dev/tessera"
	"github.com/transparency-dev/tessera/api"
	"github.com/transparency-dev/tessera/api/layout"
	"github.com/transparency-dev/tessera/client"
	"github.com/transparency-dev/tessera/storage/posix"
	"golang.org/x/mod/sumdb/note"
)

const formatID = "application/scitt-statement+cose"

// LeafEncodeV0 (frozen spec s2): "P10-LeafEncodeV0" 0x00 || uint32_be(32) || format_id || uint64_be(len) || statement
func leafEncodeV0(stmt []byte) []byte {
	b := []byte("P10-LeafEncodeV0\x00")
	b = binary.BigEndian.AppendUint32(b, uint32(len(formatID)))
	b = append(b, formatID...)
	b = binary.BigEndian.AppendUint64(b, uint64(len(stmt)))
	return append(b, stmt...)
}

type reg struct {
	Index        uint64   `json:"index"`
	TreeSize     uint64   `json:"tree_size"`
	Root         string   `json:"root"`
	LeafHash     string   `json:"leaf_hash"`
	Path         []string `json:"inclusion_path"`
	CheckpointB64 string  `json:"checkpoint_b64"`
	IsDup        bool     `json:"is_dup"`
	AwaitMillis  int64    `json:"await_millis"`
}

type env struct {
	ctx    context.Context
	dir    string
	signer note.Signer
	verif  note.Verifier
}

func (e *env) open(batchAge, cpInterval time.Duration) (*tessera.Appender, func(context.Context) error, tessera.LogReader, *tessera.PublicationAwaiter) {
	drv, err := posix.New(e.ctx, posix.Config{Path: e.dir})
	must(err)
	opts := tessera.NewAppendOptions().WithCheckpointSigner(e.signer).WithBatching(1, batchAge).WithCheckpointInterval(cpInterval)
	app, shutdown, rd, err := tessera.NewAppender(e.ctx, drv, opts)
	must(err)
	return app, shutdown, rd, tessera.NewPublicationAwaiter(e.ctx, rd.ReadCheckpoint, 50*time.Millisecond)
}

func (e *env) tileFetch(ctx context.Context, level, index uint64, p uint8) ([]byte, error) {
	return os.ReadFile(filepath.Join(e.dir, layout.TilePath(level, index, p)))
}

func (e *env) register(app *tessera.Appender, aw *tessera.PublicationAwaiter, leafInput []byte) (reg, error) {
	t0 := time.Now()
	idx, cpRaw, err := aw.Await(e.ctx, app.Add(e.ctx, tessera.NewEntry(leafInput)))
	if err != nil {
		return reg{}, err
	}
	n, err := note.Open(cpRaw, note.VerifierList(e.verif))
	must(err)
	var cp log.Checkpoint
	_, err = cp.Unmarshal([]byte(n.Text))
	must(err)
	pb, err := client.NewProofBuilder(e.ctx, cp.Size, e.tileFetch)
	must(err)
	proof, err := pb.InclusionProof(e.ctx, idx.Index)
	must(err)
	r := reg{Index: idx.Index, TreeSize: cp.Size, Root: hex.EncodeToString(cp.Hash), LeafHash: hex.EncodeToString(rfc6962.DefaultHasher.HashLeaf(leafInput)),
		CheckpointB64: base64.StdEncoding.EncodeToString(cpRaw), IsDup: idx.IsDup, AwaitMillis: time.Since(t0).Milliseconds()}
	for _, h := range proof {
		r.Path = append(r.Path, hex.EncodeToString(h))
	}
	return r, nil
}

func (e *env) export(size uint64) [][]byte {
	var all [][]byte
	for ri := range layout.Range(0, size, size) {
		raw, err := os.ReadFile(filepath.Join(e.dir, layout.EntriesPath(ri.Index, ri.Partial)))
		must(err)
		var b api.EntryBundle
		must(b.UnmarshalText(raw))
		all = append(all, b.Entries[ri.First:ri.First+ri.N]...)
	}
	return all
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "probe error:", err)
		os.Exit(1)
	}
}

func main() {
	stmts := flag.String("statements", "", "directory with prefix/NNNNNN.cose files (submitted statements, in order)")
	out := flag.String("out", "", "output directory (empty)")
	restartAt := flag.Int("restart-before", 3, "shut the appender down and reopen the same storage directory before registering this statement index (-1: never)")
	flag.Parse()
	ctx := context.Background()
	skey, vkey, err := note.GenerateKey(rand.Reader, "p10-s3-probe-log")
	must(err)
	signer, err := note.NewSigner(skey)
	must(err)
	verif, err := note.NewVerifier(vkey)
	must(err)
	res := map[string]any{}

	// ---- main probe: sequential registration, restart, export
	e := &env{ctx: ctx, dir: filepath.Join(*out, "log"), signer: signer, verif: verif}
	files, _ := filepath.Glob(filepath.Join(*stmts, "*.cose"))
	sort.Strings(files)
	app, shutdown, _, aw := e.open(10*time.Millisecond, 200*time.Millisecond)
	var regs []reg
	var submitted [][]byte
	for i, f := range files {
		s, err := os.ReadFile(f)
		must(err)
		submitted = append(submitted, s)
		if i == *restartAt { // restart in the middle: shut down cleanly and reopen the same storage directory
			must(shutdown(ctx))
			app, shutdown, _, aw = e.open(10*time.Millisecond, 200*time.Millisecond)
			res["restart_before_statement_index"] = i
		}
		r, err := e.register(app, aw, leafEncodeV0(s))
		must(err)
		regs = append(regs, r)
	}
	must(shutdown(ctx))
	must(os.MkdirAll(filepath.Join(*out, "retained", "submissions"), 0o755))
	must(os.MkdirAll(filepath.Join(*out, "retained", "export"), 0o755))
	must(os.MkdirAll(filepath.Join(*out, "retained", "receipt-inputs"), 0o755))
	for i, s := range submitted {
		must(os.WriteFile(filepath.Join(*out, "retained", "submissions", fmt.Sprintf("%06d.cose", i)), s, 0o644))
		j, _ := json.MarshalIndent(regs[i], "", " ")
		must(os.WriteFile(filepath.Join(*out, "retained", "receipt-inputs", fmt.Sprintf("%06d.json", i)), j, 0o644))
	}
	exported := e.export(uint64(len(submitted)))
	res["exported_entries"] = len(exported)
	for i, le := range exported {
		must(os.WriteFile(filepath.Join(*out, "retained", "export", fmt.Sprintf("%06d.leaf_input", i)), le, 0o644))
	}
	res["registrations"] = regs
	res["verifier_key"] = vkey

	// ---- side probe 1: entry-size boundary (leaf_input limit is 65535 bytes)
	e2 := &env{ctx: ctx, dir: filepath.Join(*out, "log-size"), signer: signer, verif: verif}
	app2, sd2, _, aw2 := e2.open(10*time.Millisecond, 200*time.Millisecond)
	sizes := map[string]string{}
	for _, n := range []int{65535 - 61, 65535 - 61 + 1} { // statement bytes: leaf_input = 61 + n
		pad := make([]byte, n)
		_, err := e2.register(app2, aw2, leafEncodeV0(pad))
		sizes[fmt.Sprintf("statement_bytes_%d_leaf_input_%d", n, 61+n)] = errStr(err)
	}
	must(sd2(ctx))
	res["entry_size_boundary"] = sizes

	// ---- side probe 2: duplicates without the antispam option
	e3 := &env{ctx: ctx, dir: filepath.Join(*out, "log-dup"), signer: signer, verif: verif}
	app3, sd3, _, aw3 := e3.open(10*time.Millisecond, 200*time.Millisecond)
	d := leafEncodeV0([]byte("same statement bytes"))
	r1, err := e3.register(app3, aw3, d)
	must(err)
	r2, err := e3.register(app3, aw3, d)
	must(err)
	must(sd3(ctx))
	res["duplicates_without_antispam"] = map[string]any{"first_index": r1.Index, "second_index": r2.Index, "second_is_dup": r2.IsDup}
	_ = strings.Join
	j, _ := json.MarshalIndent(res, "", " ")
	must(os.WriteFile(filepath.Join(*out, "probe-result.json"), j, 0o644))
	fmt.Println(string(j)[:400], "...")
}

func errStr(err error) string {
	if err == nil {
		return "accepted"
	}
	return "rejected: " + err.Error()
}
