//! NON-NORMATIVE FEASIBILITY SPIKE (not the S3 acceptance runner).
//!
//! Thin entry over the unchanged pinned S2b crate. It calls only public items of `p10_replay`:
//! `request::decode_request`, `finalize::replay_p0_p9`, `cose::parse_cose_sign1`, `statement::read_protected`.
//! It introduces no CBOR/COSE parser and no verdict logic. Composition of S2b results into HALT/REJECT is done elsewhere
//! (glue), from the frozen S2b prereg table.
//!
//! usage: s3-spike-entry verify --request <request.cbor> --out <dir> [--expect-target-payload <file>]
//!
//! exit codes: 0 Verified | 10 Invalid | 11 Unavailable | 2 transport/IO error | 20 target extraction or payload-equality failure
//! files written to <dir>: result.json (always), and on Verified: tB.bin, target.sub.txt, target.payload.bin, target.leaf_index.txt

use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

use p10_replay::cose::{parse_cose_sign1, PayloadRaw};
use p10_replay::finalize::{replay_p0_p9, ReplayResult};
use p10_replay::receipt::ReceiptOutcome;
use p10_replay::replay::Failure;
use p10_replay::request::{decode_request, ReplayRequest};
use p10_replay::statement::read_protected;

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn jstr(s: &str) -> String {
    let mut o = String::from("\"");
    for ch in s.chars() {
        match ch {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

fn failure_json(f: &Failure) -> String {
    format!(
        "{{\"phase\":{},\"severity\":{},\"class\":{},\"reason\":{},\"detail\":{}}}",
        jstr(&format!("{:?}", f.phase)),
        jstr(&format!("{:?}", f.severity)),
        jstr(&format!("{:?}", f.class)),
        jstr(&format!("{:?}", f.reason)),
        match &f.detail {
            Some(d) => jstr(d),
            None => "null".to_string(),
        }
    )
}

fn write(dir: &PathBuf, name: &str, data: &[u8]) -> Result<(), String> {
    fs::write(dir.join(name), data).map_err(|e| format!("write {name}: {e}"))
}

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
}

/// Target data taken from the exact verified target bytes (and, when detached, the exact request material).
struct Target {
    sub: String,
    payload: Vec<u8>,
    leaf_index: u64,
}

fn extract_target(req: &ReplayRequest, evidence: &p10_replay::evidence::ReplayEvidence) -> Result<Target, String> {
    let leaf_index = match &evidence.receipt.outcome {
        ReceiptOutcome::Authenticated(c) => c.leaf_index,
        other => return Err(format!("Verified result without an authenticated Receipt checkpoint: {other:?}")),
    };
    let target = req
        .material
        .target_registered_statement_bytes
        .as_deref()
        .ok_or_else(|| "Verified result without target statement bytes".to_string())?;
    let cose = parse_cose_sign1(target).map_err(|e| format!("parse_cose_sign1(target): {e:?}"))?;
    let view = read_protected(&cose.protected_content).map_err(|e| format!("read_protected(target): {e:?}"))?;
    let payload = match cose.payload {
        PayloadRaw::Attached(p) => p,
        PayloadRaw::Detached => req
            .material
            .detached_statement_payloads
            .get(&leaf_index)
            .cloned()
            .ok_or_else(|| format!("target payload is detached and no detached payload is supplied for index {leaf_index}"))?,
    };
    Ok(Target { sub: view.sub, payload, leaf_index })
}

fn run(args: &[String]) -> Result<u8, String> {
    if args.first().map(String::as_str) != Some("verify") {
        return Err("usage: s3-spike-entry verify --request <file> --out <dir> [--expect-target-payload <file>]".into());
    }
    let request_path = arg(args, "--request").ok_or("missing --request")?;
    let out = PathBuf::from(arg(args, "--out").ok_or("missing --out")?);
    fs::create_dir_all(&out).map_err(|e| format!("create out dir: {e}"))?;
    let raw = fs::read(&request_path).map_err(|e| format!("read request: {e}"))?;

    let req = match decode_request(&raw) {
        Ok(r) => r,
        Err(e) => {
            write(&out, "result.json", format!("{{\"stage\":\"decode_request\",\"status\":\"TransportError\",\"error\":{}}}\n", jstr(&format!("{e}"))).as_bytes())?;
            return Ok(2);
        }
    };

    match replay_p0_p9(&req) {
        ReplayResult::Invalid { reason, diagnostics } | ReplayResult::Unavailable { reason, diagnostics } => {
            let status = if matches!(reason.severity, p10_replay::replay::Severity::Invalid) { "Invalid" } else { "Unavailable" };
            let diags: Vec<String> = diagnostics.iter().map(failure_json).collect();
            let body = format!(
                "{{\"stage\":\"s2b\",\"status\":\"{status}\",\"reason\":{},\"diagnostics\":[{}]}}\n",
                failure_json(&reason),
                diags.join(",")
            );
            write(&out, "result.json", body.as_bytes())?;
            Ok(if status == "Invalid" { 10 } else { 11 })
        }
        ReplayResult::Verified { transcript_bytes, replay_evidence } => {
            write(&out, "tB.bin", &transcript_bytes)?;
            let subj: Vec<String> = replay_evidence
                .subject_observations
                .iter()
                .map(|s| format!("{{\"idx\":{},\"kind\":{},\"sig\":{}}}", s.idx, jstr(&format!("{:?}", s.kind)), jstr(&format!("{:?}", s.sig))))
                .collect();
            let unread: Vec<String> = replay_evidence.unreadable_rows.iter().map(|u| format!("{{\"idx\":{},\"reason\":{}}}", u.idx, jstr(&format!("{:?}", u.reason)))).collect();
            let target = extract_target(&req, &replay_evidence);
            let mut exit = 0u8;
            let target_json;
            match &target {
                Ok(t) => {
                    write(&out, "target.sub.txt", t.sub.as_bytes())?;
                    write(&out, "target.payload.bin", &t.payload)?;
                    write(&out, "target.leaf_index.txt", t.leaf_index.to_string().as_bytes())?;
                    let mut eq = "null".to_string();
                    if let Some(p) = arg(args, "--expect-target-payload") {
                        let want = fs::read(&p).map_err(|e| format!("read expected target payload: {e}"))?;
                        if want == t.payload {
                            eq = "true".into();
                        } else {
                            eq = "false".into();
                            exit = 20;
                        }
                    }
                    target_json = format!("{{\"leaf_index\":{},\"sub\":{},\"payload_len\":{},\"payload_equals_retained_file\":{eq}}}", t.leaf_index, jstr(&t.sub), t.payload.len());
                }
                Err(e) => {
                    target_json = format!("{{\"error\":{}}}", jstr(e));
                    exit = 20;
                }
            }
            let body = format!(
                "{{\"stage\":\"s2b\",\"status\":\"Verified\",\"checkpoint_size\":{},\"root\":\"{}\",\"log_identity_digest\":\"{}\",\"transcript_sha256\":\"{}\",\"tb_len\":{},\"subject_observations\":[{}],\"unreadable_rows\":[{}],\"target\":{}}}\n",
                replay_evidence.checkpoint_size,
                hex(&replay_evidence.root_digest),
                hex(&replay_evidence.log_identity.log_identity_digest),
                hex(&replay_evidence.transcript_sha256),
                transcript_bytes.len(),
                subj.join(","),
                unread.join(","),
                target_json
            );
            write(&out, "result.json", body.as_bytes())?;
            Ok(exit)
        }
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(code) => ExitCode::from(code),
        Err(e) => {
            eprintln!("s3-spike-entry: {e}");
            ExitCode::from(2)
        }
    }
}
