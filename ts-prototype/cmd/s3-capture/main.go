// s3-capture: capture client. `submit` plays the issuer/operator submitter (it retains what it sent and what the facade returned, and the original
// signed checkpoint from the PUBLIC endpoint before the next registration); `export` reads the public log over HTTP only. The two are separate
// subcommands with separate outputs so that submissions, returned Receipts and public exports are independent sources. Prototype, non-normative.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/volmax-studio/p10-s3-prototype/internal/capture"
)

func die(f string, a ...any) {
	fmt.Fprintf(os.Stderr, "s3-capture: "+f+"\n", a...)
	os.Exit(1)
}

func writeFile(p string, b []byte) {
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		die("%v", err)
	}
	if err := os.WriteFile(p, b, 0o644); err != nil {
		die("%v", err)
	}
}

func main() {
	if len(os.Args) < 2 {
		die("usage: s3-capture submit|export [flags]")
	}
	switch os.Args[1] {
	case "submit":
		submit(os.Args[2:])
	case "export":
		export(os.Args[2:])
	default:
		die("unknown subcommand %q", os.Args[1])
	}
}

type resp struct {
	Index         uint64 `json:"index"`
	TreeSize      uint64 `json:"tree_size"`
	ReceiptB64    string `json:"receipt_b64"`
	CheckpointB64 string `json:"checkpoint_b64"`
	Duplicate     bool   `json:"duplicate"`
	Recovered     bool   `json:"recovered"`
}

func submit(args []string) {
	fs := flag.NewFlagSet("submit", flag.ExitOnError)
	facade := fs.String("facade", "", "registration endpoint base URL")
	pub := fs.String("public", "", "public read endpoint base URL")
	vkey := fs.String("note-vkey", "", "pinned note verifier key")
	origin := fs.String("origin", "", "expected checkpoint origin")
	stmts := fs.String("statements", "", "directory of NNNNNN.cose files to submit, in index order (the submitter's own files)")
	detached := fs.String("detached", "", "optional directory of NNNNNN.payload files: detached statement payloads held by the issuer (never sent to the facade)")
	tsOrigin := fs.String("ts-origin", "", "comma list of indices submitted by the operator (bootstrap), kept apart from issuer submissions")
	out := fs.String("out", "", "output directory (empty)")
	retries := fs.Int("retries", 3, "re-POSTs of the same bytes after a transport error")
	fs.Parse(args)
	if *facade == "" || *pub == "" || *vkey == "" || *origin == "" || *stmts == "" || *out == "" {
		die("submit: missing flag")
	}
	ctx := context.Background()
	p, err := capture.NewPublic(*pub, *vkey, *origin, "")
	if err != nil {
		die("%v", err)
	}
	ops := map[int]bool{}
	for _, s := range strings.Split(*tsOrigin, ",") {
		if s != "" {
			n, _ := strconv.Atoi(s)
			ops[n] = true
		}
	}
	files, _ := filepath.Glob(filepath.Join(*stmts, "*.cose"))
	sort.Strings(files)
	hc := &http.Client{Timeout: 90 * time.Second}
	var logl []map[string]any
	if prev, err := os.ReadFile(filepath.Join(*out, "submit-log.json")); err == nil { // continue an earlier invocation's log
		json.Unmarshal(prev, &logl)
	}
	for _, f := range files {
		// the file name NNNNNN.cose is the statement's expected log index (a later invocation may continue an earlier one)
		i, err := strconv.Atoi(strings.TrimSuffix(filepath.Base(f), ".cose"))
		if err != nil || i < 0 {
			die("statement file %q is not named NNNNNN.cose", f)
		}
		stmt, err := os.ReadFile(f)
		if err != nil {
			die("%v", err)
		}
		name := fmt.Sprintf("%06d", i)
		sub := "issuer"
		if ops[i] {
			sub = "operator"
		}
		writeFile(filepath.Join(*out, sub, "submissions", name+".cose"), stmt) // retained BEFORE the request
		if *detached != "" {
			if d, err := os.ReadFile(filepath.Join(*detached, name+".payload")); err == nil {
				writeFile(filepath.Join(*out, sub, "detached", name+".payload"), d)
			}
		}
		var body []byte
		var status int
		for try := 0; ; try++ {
			r, err := hc.Post(strings.TrimRight(*facade, "/")+"/register", "application/cose", bytes.NewReader(stmt))
			if err == nil {
				body, _ = io.ReadAll(r.Body)
				r.Body.Close()
				status = r.StatusCode
				break
			}
			if try >= *retries {
				die("statement %d: %v", i, err)
			}
			time.Sleep(time.Second)
		}
		writeFile(filepath.Join(*out, "returned", name+".response.json"), body)
		if status != 200 && status != 201 {
			die("statement %d: facade answered %d: %s", i, status, body)
		}
		var rs resp
		if err := json.Unmarshal(body, &rs); err != nil {
			die("statement %d: %v", i, err)
		}
		if rs.Index != uint64(i) {
			die("statement %d: registered at index %d, expected %d", i, rs.Index, i)
		}
		rec, _ := base64.StdEncoding.DecodeString(rs.ReceiptB64)
		fcp, _ := base64.StdEncoding.DecodeString(rs.CheckpointB64)
		writeFile(filepath.Join(*out, "returned", name+".receipt.cbor"), rec)
		writeFile(filepath.Join(*out, "returned", name+".facade-checkpoint"), fcp)
		// the ORIGINAL signed checkpoint from the public read endpoint, retained before the next registration
		cp, raw, err := p.WaitCheckpointSize(ctx, rs.Index+1, 30*time.Second)
		if err != nil {
			die("statement %d: %v", i, err)
		}
		writeFile(filepath.Join(*out, "public-checkpoints", name+".checkpoint"), raw)
		logl = append(logl, map[string]any{"index": rs.Index, "origin": sub, "tree_size_in_receipt": rs.TreeSize, "public_checkpoint_size": cp.Size,
			"facade_checkpoint_equals_public": bytes.Equal(fcp, raw), "duplicate": rs.Duplicate, "recovered": rs.Recovered})
	}
	b, _ := json.MarshalIndent(logl, "", " ")
	writeFile(filepath.Join(*out, "submit-log.json"), append(b, '\n'))
	fmt.Printf("submitted %d statements\n", len(files))
}

func export(args []string) {
	fs := flag.NewFlagSet("export", flag.ExitOnError)
	pub := fs.String("public", "", "public read endpoint base URL")
	vkey := fs.String("note-vkey", "", "pinned note verifier key")
	origin := fs.String("origin", "", "expected checkpoint origin")
	size := fs.Uint64("expect-size", 0, "the log must have exactly this many entries")
	out := fs.String("out", "", "output directory (empty)")
	fs.Parse(args)
	if *pub == "" || *vkey == "" || *origin == "" || *size == 0 || *out == "" {
		die("export: missing flag")
	}
	ctx := context.Background()
	p, err := capture.NewPublic(*pub, *vkey, *origin, filepath.Join(*out, "public"))
	if err != nil {
		die("%v", err)
	}
	cp, _, err := p.WaitCheckpointSize(ctx, *size, 30*time.Second)
	if err != nil {
		die("%v", err)
	}
	res, err := p.Export(ctx, cp)
	if err != nil {
		die("%v", err)
	}
	for i, li := range res.LeafInputs {
		writeFile(filepath.Join(*out, "export", fmt.Sprintf("%06d.leaf_input", i)), li)
	}
	b, _ := json.MarshalIndent(map[string]any{"size": res.Size, "root": res.Root, "origin": *origin, "entries_proved_into_checkpoint_root": len(res.LeafInputs)}, "", " ")
	writeFile(filepath.Join(*out, "export-result.json"), append(b, '\n'))
	fmt.Printf("exported %d verified entries (root %s)\n", res.Size, res.Root)
}
