// s3-keygen: generate a Tessera checkpoint (note) signing key pair. The secret key file must be kept OUTSIDE the repository; only the verifier key is public.
package main

import (
	"crypto/rand"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/mod/sumdb/note"
)

func main() {
	name := flag.String("name", "", "checkpoint origin / key name")
	out := flag.String("out", "", "directory for note.skey (0600) and note.vkey")
	flag.Parse()
	if *name == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "usage: s3-keygen --name ORIGIN --out DIR")
		os.Exit(2)
	}
	skey, vkey, err := note.GenerateKey(rand.Reader, *name)
	if err != nil {
		panic(err)
	}
	if err := os.MkdirAll(*out, 0o700); err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(*out, "note.skey"), []byte(skey+"\n"), 0o600); err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(*out, "note.vkey"), []byte(vkey+"\n"), 0o644); err != nil {
		panic(err)
	}
	fmt.Println(vkey)
}
