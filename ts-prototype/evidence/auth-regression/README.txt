Regression of the facade with issuer authentication (candidate; exploratory prototype checks, not frozen-chain verdicts).

Source pinned at commit 10638c239b27d7c87b238a6f387c95882162c4dc (tree clean under ts-prototype/). Binaries built from it with
  CGO_ENABLED=0 go build -trimpath -buildvcs=false ./cmd/...   (go1.24.7)
  s3-capture 1ecde5e4bc10ad8587782f9ab74b070aed0665c800c261972bab5e69cc1fab4d
  s3-facade  7c71d8615bc3d46152943e47bf0c7555bc310e93ba9f67b69fd7bfb9e3a0ec40
  s3-keygen  fd829bd6e250b1c9294dd952d59bc1e7db2adaed9e028e41b2ee116c684e7532

Contents
  go-test.out          go test -count=1 ./...  (issuerauth: valid/tampered/identity-to-key/unknown/alg/label/kid/detached cases and table-load refusals)
  facade-tests.out     scripts/facade_tests.py T1..T8, chaos seed 1 with 30 statements (real s3-facade and s3-capture processes; statements signed by throwaway test issuers
                       whose private keys exist only in the test process; Receipt and checkpoint keys and the fixture are throwaway development ones used by the earlier regression runs)
  timeout-tests.out    scripts/timeout_tests.py --mode post (publish-timeout 3 s, fetch-timeout 1 s)
  facade-tests/, timeout-tests/   per-test results (facade-tests.json), journals, s3check outputs and facade stderr; Tessera log directories, tile dumps and exports were pruned.
T8 is new: refusals of each kind append nothing, journal no intent, store and issue no Receipt, leave the checkpoint size unchanged; a duplicate is not answered without authentication;
the capture client transports a detached payload (exported leaf == submitted bytes, payload not in the log); the facade does not start without a valid issuer table.
Earlier evidence directories (before the change) are unchanged. No claim of RFC 9943 or SCRAPI compliance is made by these tests.
