# Custody handoff (candidate key set)

Two age-encrypted packages (recipient: the operator's locally generated age public key, recorded in `transit-record.json`): `issuer-archive.tar.age` (five issuer keys) and `one-use-receipt-checkpoint.tar.age` (Receipt key, checkpoint signing key, public verifier key). They were produced by streaming `tar | age`; no plaintext archive exists. The packages are not committed.

Local verification (on the operator's machine; needs `python3`, `age`, `openssl`; the identity file is the one belonging to the recipient):

```
python3 deployment/candidate/custody/verify_custody.py --identity AGE_IDENTITY_FILE \
    --issuers issuer-archive.tar.age --one-use one-use-receipt-checkpoint.tar.age
```

It checks the package SHA-256 values against `transit-record.json`, decrypts into a private temporary directory (removed at the end), checks the file inventory, recomputes the public key fingerprints (RFC 9679-style thumbprints) and compares them with `definition-manifest.json`, and checks that the checkpoint signing key matches the verifier key. It prints only hashes, public fingerprints and PASS/FAIL, and exits 0 only if everything passes.

Nothing is deleted anywhere until the operator confirms that this command printed `ALL PASS` on his machine. Retirement of the one-use keys is a later, manual step (`spec/operator-record-receipt-key-retirement.md`).

Fail-closed: both package hashes are checked against `transit-record.json` before `age` or `tar` is invoked; if either differs the script exits nonzero and nothing is decrypted or extracted. Test: `python3 deployment/candidate/custody/test_verify_custody.py` (fake `age`/`tar` record any call on hash mismatch; positive run and wrong-identity run with dummy keys).
