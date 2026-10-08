# Operator record: one-use Receipt-key retirement (template; nothing has been done)

Status: **TEMPLATE FOR THE OPERATOR. No key has been deleted by any tool or by Claude, and no step below is automated.** The procedure is a proposal for deployment-profile decision D8. It is performed, if at all, by the operator (Ivan) after the capture is frozen and verified, and the filled record is an operator-generated, self-attested document.

## What this does and does not give

- **Purpose.** The log identity (`LogIdentityV0`) commits one Receipt-signing key for one bounded capture. If no copy of its private key survives, nobody, including the operator, can later sign a further Receipt under this identity with that key.
- **Assumption.** All copies were found and removed. This cannot be proven by the record: unknown copies (backups, snapshots, copy-on-write or journaling file systems, swap, terminal history, a second host, someone else's clipboard) are not excluded.
- **Not given.** It is not a cryptographic proof of non-equivocation. It does not undo anything signed before retirement (a Receipt signed earlier and never published would still verify). It does not give operator independence: the same operator ran the log, the facade, the issuer table and every key, before and after. It does not change what the capture proves.
- **Cost.** After retirement the log cannot register or re-issue anything under this identity. Nothing in the S3 acceptance path needs the private key: S3-C uses the retained original Receipts and public keys only.

## Preconditions (all must hold before any key is touched)

1. The capture is frozen, its anchor is recorded and the offline acceptance (`BINDING_MATCH` through the pinned runner) succeeded twice with identical `verdict.json`.
2. Every original Receipt, response, submission and public checkpoint is retained in the capture and hashed in the manifest (I8). No registration is planned under this identity.
3. The decision to retire (instead of archiving) is recorded as taken by the operator, not by Claude.

## Procedure (operator)

1. Stop the facade (SIGTERM) and confirm no process still holds the key files open. Record the final log size, the final public checkpoint file and its SHA-256, and the facade state directory hash listing.
2. Inventory every known copy of the **Receipt private key** (PEM, outside the repository), and the same for the **checkpoint (note) signing key**, which has the same property for checkpoints. List path, device, backup or snapshot membership, and whether the storage can securely erase (ordinary files on SSD or copy-on-write file systems cannot be assumed erased by overwriting).
3. Remove each copy by a method that fits its storage. Preferred where available: keep the keys only on an encrypted volume or tmpfs created for the capture and destroy that volume key or unmount the tmpfs; otherwise delete the files and remove backups and snapshots that contain them. Note the method per copy. Do **not** claim secure overwriting on storage where it is not reliable.
4. Verify absence by listing each location again and, for backups, by the backup tool's listing. Record anything that could not be verified.
5. Issuer keys (owner, admitters, operator) are **not** retired by this procedure: they stay archived offline under the operator's custody (they are needed to regenerate negative material); their archive location is recorded, not their content.
6. Fill the record below and store it with the capture provenance. Signing or timestamping the record is the operator's separate choice.

## Record (to be filled by the operator)

| Field | Value |
|---|---|
| Date and time (UTC) of retirement | |
| Operator | |
| Persons present (if any) | |
| Log identity (`LogIdentityV0`, hex) | |
| Receipt key thumbprint (SHA-256, hex) | |
| Checkpoint key verifier (note vkey) | |
| Final log size and root (hex) | |
| Final public checkpoint SHA-256 | |
| Facade stopped at (UTC), process confirmed gone | |
| Copies of the Receipt private key found (path, device, backup) | |
| Method of removal per copy | |
| Copies of the checkpoint private key found and removed | |
| Locations or media that could not be checked or erased | |
| Issuer keys archived at (location, not content) | |
| Statement of known limits (copy this document's "Not given" section) | |
| Operator's declaration (free text) | |

The record is data for reviewers, not a source of key authority: nothing in the acceptance chain reads it.
