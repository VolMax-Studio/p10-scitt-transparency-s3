# S2b public API used by the spike entry (compile-checked)

NON-NORMATIVE FEASIBILITY SPIKE. Pinned crate: `p10_replay` at S2b commit `8eaa91cad1ffa963158b365c6d0d7316f4965e89`, linked as a path dependency from an external crate (`spike/s3-entry`), built with Rust 1.82.0 and the locked versions.

**Executed:** `cargo build --locked --offline` of `spike/s3-entry` succeeded (inside `run_host.sh` step 2; output in `evidence/2026-10-07-container/container-run-via-run_host/host.log`). A crate outside S2b can therefore name every item below. No S2b file was modified, and no S2b parser code was copied.

| Module / item | Kind | Used for |
|---|---|---|
| `p10_replay::request::decode_request(&[u8]) -> Result<ReplayRequest, TransportError>` | pub fn | frozen request decode (`TransportError` printed through its `Display`) |
| `p10_replay::request::ReplayRequest` fields `.frozen`, `.material`; `TsMaterial.target_registered_statement_bytes: Option<Vec<u8>>`, `TsMaterial.detached_statement_payloads: BTreeMap<u64, Vec<u8>>` | pub struct, pub fields | exact target bytes, exact detached payloads |
| `p10_replay::finalize::replay_p0_p9(&ReplayRequest) -> ReplayResult`; `ReplayResult::{Verified{transcript_bytes, replay_evidence}, Invalid{reason, diagnostics}, Unavailable{reason, diagnostics}}` | pub fn, pub enum | the S2b replay |
| `p10_replay::replay::Failure` fields `phase, severity, class, reason, detail`; `replay::Severity` | pub struct, pub enum (Debug) | S2b result reporting |
| `p10_replay::evidence::ReplayEvidence` fields `checkpoint_size, root_digest, receipt, log_identity.log_identity_digest, subject_observations, unreadable_rows, transcript_sha256` | pub struct, pub fields | evidence summary, Receipt checkpoint |
| `p10_replay::receipt::ReceiptOutcome::Authenticated(AuthenticatedCheckpoint{tree_size, leaf_index, root})` | pub enum / struct | authenticated Receipt `leaf_index` of the target |
| `p10_replay::cose::parse_cose_sign1(&[u8]) -> Result<CoseSign1Raw, CoseRawError>`; `CoseSign1Raw.protected_content`, `.payload`; `cose::PayloadRaw::{Attached(Vec<u8>), Detached}` | pub fn, pub struct, pub enum | frozen COSE_Sign1 split of the authenticated target |
| `p10_replay::statement::read_protected(&[u8]) -> Result<ProtectedView, ProtectedUnreadable>`; `ProtectedView.sub` | pub fn, pub struct | protected CWT `sub` of the authenticated target |

Everything else printed (`Phase`, `ResultClass`, `Reason`, `Kind`, `SigObservation`, `RowReason`) is used only through `Debug`.

**Inaccessible required API:** none found. If a later change needs an item that is not `pub`, the rule is to stop and report, not to modify S2b or copy its parsing code.
