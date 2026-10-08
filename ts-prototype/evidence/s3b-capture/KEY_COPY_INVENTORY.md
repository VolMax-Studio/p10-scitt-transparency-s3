# Read-only inventory of candidate key copies in the session container (paths and status only; no secret content; nothing deleted)

Taken after the second runner replay. Method: file-hash comparison (hashes not recorded) of the seven candidate secret files against every file under 2 KB in `/home/user`, `/tmp/claude-0` and `/root`, plus a search for `*.tar.age`. Limits: it does not cover files of other sizes, other filesystem trees, memory, swap, shell history or anything outside this container; encrypted packages delivered to the operator by file transfer are outside it.

| Class | Path | Status |
|---|---|---|
| Receipt private key (one-use) | `/home/user/s3-custody/candidate-receipt/ts.pem` | present, mode 0600; the only plaintext copy found |
| Checkpoint signing key (one-use) | `/home/user/s3-custody/candidate-checkpoint/note.skey` | present, mode 0600; the only plaintext copy found |
| Checkpoint verifier key (public) | `/home/user/s3-custody/candidate-checkpoint/note.vkey` | present (public) |
| Issuer keys (owner, admitter-one, admitter-two, intruder-x, operator) | `/home/user/s3-custody/candidate-issuers/*.pem` | present, mode 0600; only plaintext copies found; archive stays with the operator |
| Encrypted packages (transit) | `/home/user/s3-custody-transit/issuer-archive.tar.age`, `…/one-use-receipt-checkpoint.tar.age` | present; SHA-256 `7662c821…`, `c55c4b57…` (as in `transit-record.json`) |
| Encrypted packages (staging for transfer) | `$SP/handoff/issuer-archive.tar.age`, `$SP/handoff/one-use-receipt-checkpoint.tar.age` | present; same hashes |
| Test packages with dummy keys | `$SP/custody-test/*.tar.age` | present; encrypted to a throwaway identity; not candidate keys |
| Tracked in Git | any `*.pem`, `note.skey`, `*.age`, age identity | none |
| Throwaway keys of earlier exploratory runs | scratchpad key directories (`qual-keys-*`, `dev*-keys-*`, `run*-keys-*`, …) | present; **not** candidate keys; not part of the retirement scope |
| Facade | any `s3-facade` process; listeners on ports 19900/19901 and other test ports | **stopped**: none running, none listening |

Copies outside the container: the encrypted packages as delivered to the operator and every copy he made; his age identity; his decrypted copies, if any (his responsibility to list in the retirement record).
