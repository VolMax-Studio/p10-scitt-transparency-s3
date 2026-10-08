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
	"os/exec"
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
	opInsert := fs.String("operator-insert", "", "producer mode: ORDINAL:FILE[,...] register the operator statement FILE through the same facade right after producer ordinal ORDINAL (not a producer role)")
	producer := fs.String("producer", "", "RUNTIME ISSUER TOOLING: executable called as `PRODUCER --ordinal K --next-index N --run OUT` before each registration; it creates and signs statement N from what has been registered so far and prints one JSON line {\"file\",\"origin\",\"detached\"} or {\"done\":true} (replaces --statements; the arguments are --ordinal K --next-index N --run OUT)")
	detached := fs.String("detached", "", "optional directory of NNNNNN.payload files: detached statement payloads held by the issuer (never sent to the facade)")
	tsOrigin := fs.String("ts-origin", "", "comma list of indices submitted by the operator (bootstrap), kept apart from issuer submissions")
	out := fs.String("out", "", "output directory (empty)")
	retries := fs.Int("retries", 3, "re-POSTs of the same bytes after a transport error")
	timeout := fs.Duration("timeout", 30*time.Second, "deadline of each wait for a published checkpoint")
	fs.Parse(args)
	if *facade == "" || *pub == "" || *vkey == "" || *origin == "" || (*stmts == "") == (*producer == "") || *out == "" {
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
	hc := &http.Client{Timeout: 90 * time.Second}
	var logl []map[string]any
	if prev, err := os.ReadFile(filepath.Join(*out, "submit-log.json")); err == nil { // continue an earlier invocation's log
		json.Unmarshal(prev, &logl)
	}
	nsub := 0
	process := func(i int, ordinal int, source string, stmt []byte, sub string, detPayload []byte) {
		name := fmt.Sprintf("%06d", i)
		writeFile(filepath.Join(*out, sub, "submissions", name+".cose"), stmt) // retained BEFORE the request
		if detPayload != nil {
			writeFile(filepath.Join(*out, sub, "detached", name+".payload"), detPayload)
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
		cp, raw, err := p.WaitCheckpointSize(ctx, rs.Index+1, *timeout)
		if err != nil {
			die("statement %d: %v", i, err)
		}
		writeFile(filepath.Join(*out, "public-checkpoints", name+".checkpoint"), raw)
		logl = append(logl, map[string]any{"index": rs.Index, "origin": sub, "tree_size_in_receipt": rs.TreeSize, "public_checkpoint_size": cp.Size,
			"facade_checkpoint_equals_public": bytes.Equal(fcp, raw), "duplicate": rs.Duplicate, "recovered": rs.Recovered,
			"producer_ordinal": ordinal, "source": source})
		nsub++
	}
	if *producer != "" {
		// The producer's role ORDINAL, the statement's actual LOG INDEX and the size of the authenticated PREFIX are separate quantities. The next expected append
		// position is derived from the verified public checkpoint before every registration (single sequential writer); the facade's answer is validated against it.
		inserts := map[int]string{} // after producer ordinal K: register this operator statement through the same facade, not counted as a producer role
		for _, kv := range strings.Split(*opInsert, ",") {
			if kv == "" {
				continue
			}
			parts := strings.SplitN(kv, ":", 2)
			k, err := strconv.Atoi(parts[0])
			if err != nil || len(parts) != 2 {
				die("bad --operator-insert %q (want ORDINAL:FILE)", kv)
			}
			inserts[k] = parts[1]
		}
		nextIndex := func() int {
			cp, _, err := p.WaitCurrent(ctx, *timeout)
			if err != nil {
				die("next expected index: %v", err)
			}
			return int(cp.Size)
		}
		for ordinal := 0; ; ordinal++ {
			next := nextIndex()
			cmd := exec.Command(*producer, "--ordinal", strconv.Itoa(ordinal), "--next-index", strconv.Itoa(next), "--run", *out)
			cmd.Stderr = os.Stderr
			o, err := cmd.Output()
			if err != nil {
				die("producer ordinal %d: %v", ordinal, err)
			}
			var pr struct {
				Done     bool   `json:"done"`
				File     string `json:"file"`
				Origin   string `json:"origin"`
				Detached string `json:"detached"`
			}
			if err := json.Unmarshal(bytes.TrimSpace(o), &pr); err != nil {
				die("producer ordinal %d: bad output %q: %v", ordinal, o, err)
			}
			if pr.Done {
				break
			}
			if pr.Origin != "issuer" && pr.Origin != "operator" {
				die("producer ordinal %d: origin must be issuer or operator", ordinal)
			}
			stmt, err := os.ReadFile(pr.File)
			if err != nil {
				die("%v", err)
			}
			var det []byte
			if pr.Detached != "" {
				if det, err = os.ReadFile(pr.Detached); err != nil {
					die("%v", err)
				}
			}
			process(next, ordinal, "producer", stmt, pr.Origin, det)
			if f, ok := inserts[ordinal]; ok { // lifecycle production is paused; the same operator registers one statement, sequentially
				ins, err := os.ReadFile(f)
				if err != nil {
					die("%v", err)
				}
				process(nextIndex(), -1, "operator-insert", ins, "operator", nil)
			}
		}
	} else {
		files, _ := filepath.Glob(filepath.Join(*stmts, "*.cose"))
		sort.Strings(files)
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
			sub := "issuer"
			if ops[i] {
				sub = "operator"
			}
			var det []byte
			if *detached != "" {
				det, _ = os.ReadFile(filepath.Join(*detached, fmt.Sprintf("%06d.payload", i)))
			}
			process(i, -1, "fixture-file", stmt, sub, det)
		}
	}
	b, _ := json.MarshalIndent(logl, "", " ")
	writeFile(filepath.Join(*out, "submit-log.json"), append(b, '\n'))
	fmt.Printf("submitted %d statements\n", nsub)
}

func export(args []string) {
	fs := flag.NewFlagSet("export", flag.ExitOnError)
	pub := fs.String("public", "", "public read endpoint base URL")
	vkey := fs.String("note-vkey", "", "pinned note verifier key")
	origin := fs.String("origin", "", "expected checkpoint origin")
	size := fs.Uint64("expect-size", 0, "the log must have exactly this many entries")
	out := fs.String("out", "", "output directory (empty)")
	timeout := fs.Duration("timeout", 30*time.Second, "deadline of the wait for the checkpoint, and separately of the verified export")
	fs.Parse(args)
	if *pub == "" || *vkey == "" || *origin == "" || *size == 0 || *out == "" {
		die("export: missing flag")
	}
	ctx := context.Background()
	p, err := capture.NewPublic(*pub, *vkey, *origin, filepath.Join(*out, "public"))
	if err != nil {
		die("%v", err)
	}
	cp, _, err := p.WaitCheckpointSize(ctx, *size, *timeout)
	if err != nil {
		die("%v", err)
	}
	ectx, cancel := context.WithTimeout(ctx, *timeout)
	defer cancel()
	res, err := p.Export(ectx, cp)
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
