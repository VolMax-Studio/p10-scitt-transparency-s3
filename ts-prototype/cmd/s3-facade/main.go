// s3-facade: candidate registration front-end over Tessera v1.0.4 (POSIX), with a SEPARATE static public read listener. Prototype, non-normative.
package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/volmax-studio/p10-s3-prototype/internal/facade"
	"github.com/volmax-studio/p10-s3-prototype/internal/publicread"
)

func main() {
	var c facade.Config
	var regAddr, pubAddr string
	flag.StringVar(&c.StorageDir, "storage", "", "Tessera POSIX storage directory (served read-only by the public endpoint)")
	flag.StringVar(&c.StateDir, "state", "", "facade state directory (journal, stored Receipts and checkpoints)")
	flag.StringVar(&c.Origin, "origin", "", "expected checkpoint origin (= note signer name)")
	flag.StringVar(&c.NoteSKeyFile, "note-skey-file", "", "note signing key file (outside the repository)")
	flag.StringVar(&c.NoteVKey, "note-vkey", "", "pinned note verifier key")
	flag.StringVar(&c.CosePEM, "cose-key", "", "PEM ES256 Receipt-signing key (outside the repository)")
	flag.StringVar(&c.TsIss, "ts-iss", "", "Receipt issuer (CWT iss) committed in the instance")
	flag.StringVar(&c.ExpectThumbprint, "expect-thumbprint", "", "hex SHA-256 thumbprint the Receipt key must have")
	flag.StringVar(&regAddr, "register-addr", "127.0.0.1:8080", "registration listener")
	flag.StringVar(&pubAddr, "public-addr", "127.0.0.1:8081", "public read listener")
	batch := flag.Uint("batch-size", 1, "Tessera batch max size")
	flag.DurationVar(&c.BatchAge, "batch-age", 10*time.Millisecond, "Tessera batch max age")
	flag.DurationVar(&c.CheckpointInterval, "checkpoint-interval", 200*time.Millisecond, "Tessera checkpoint interval")
	flag.DurationVar(&c.CheckpointRepublish, "checkpoint-republish", 0, "Tessera checkpoint republish interval (0: default)")
	flag.DurationVar(&c.PublishTimeout, "publish-timeout", 30*time.Second, "deadline of the whole finalization: published checkpoint wait, hash tiles and entry bundle reads")
	flag.DurationVar(&c.FetchTimeout, "fetch-timeout", 10*time.Second, "deadline of each single public HTTP read")
	flag.IntVar(&c.MaxLeafInput, "max-leaf-input", 1<<16-1, "limit on len(LeafEncodeV0(statement))")
	flag.StringVar(&c.PublicReadURL, "public-read-url", "", "TEST HOOK: read the public log through this base URL instead of the own public listener")
	flag.StringVar(&c.FaultPoint, "fault-point", "", "TEST ONLY: self-SIGKILL at pre-add|submitted|integrated|receipt-stored|pre-response")
	flag.IntVar(&c.FaultOnRequest, "fault-on-request", 0, "TEST ONLY: 1-based admitted registration request that triggers the fault")
	flag.Parse()
	c.BatchSize = *batch
	for n, v := range map[string]string{"storage": c.StorageDir, "state": c.StateDir, "origin": c.Origin, "note-skey-file": c.NoteSKeyFile, "note-vkey": c.NoteVKey, "cose-key": c.CosePEM, "ts-iss": c.TsIss, "expect-thumbprint": c.ExpectThumbprint} {
		if v == "" {
			fmt.Fprintln(os.Stderr, "missing --"+n)
			os.Exit(2)
		}
	}
	ctx := context.Background()
	// public side first: the facade reads checkpoints/tiles back through it, like any client
	if err := os.MkdirAll(c.StorageDir, 0o755); err != nil {
		fatal(err)
	}
	pl, err := net.Listen("tcp", pubAddr)
	if err != nil {
		fatal(err)
	}
	c.PublicURL = "http://" + pl.Addr().String() + "/"
	pubSrv := &http.Server{Handler: publicread.Handler(c.StorageDir)}
	go pubSrv.Serve(pl)
	svc, err := facade.Open(ctx, c)
	if err != nil {
		fatal(err)
	}
	rl, err := net.Listen("tcp", regAddr)
	if err != nil {
		fatal(err)
	}
	regSrv := &http.Server{Handler: svc.Handler()}
	go regSrv.Serve(rl)
	fmt.Fprintf(os.Stderr, "s3-facade ready: register=http://%s public=%s entries=%d\n", rl.Addr(), c.PublicURL, svc.Scanned)
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	sctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	regSrv.Shutdown(sctx)
	svc.Close(sctx)
	pubSrv.Shutdown(sctx)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "s3-facade:", err)
	os.Exit(1)
}
