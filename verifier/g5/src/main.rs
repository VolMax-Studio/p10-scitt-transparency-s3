//! CANDIDATE G5 command line. usage: s3-g5 --capture <dir> [--index-sha256 <hex>]
//! stdout: one JSON line, {"g5":"PASS",...} or {"g5":"FAIL","reason":"E_...","detail":"..."}. exit: 0 PASS | 30 FAIL | 2 usage error.
//! On FAIL the S2b replay, the S2a runner and the post-S2a stage MUST NOT be called.
use std::path::PathBuf;
use std::process::ExitCode;

fn jstr(s: &str) -> String {
    let mut o = String::from("\"");
    for ch in s.chars() {
        match ch {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let get = |f: &str| args.iter().position(|a| a == f).and_then(|i| args.get(i + 1)).cloned();
    let Some(cap) = get("--capture") else {
        eprintln!("usage: s3-g5 --capture <dir> [--index-sha256 <hex>]");
        return ExitCode::from(2);
    };
    let anchor = get("--index-sha256");
    match s3_g5::check_capture(&PathBuf::from(cap), anchor.as_deref()) {
        Ok(p) => {
            let opt = |o: &Option<PathBuf>| o.as_ref().map(|p| jstr(&p.to_string_lossy())).unwrap_or_else(|| "null".into());
            println!(
                "{{\"g5\":\"PASS\",\"root\":{},\"anchor_checked\":{},\"prefix_leaves\":{},\"files_indexed\":{},\"request\":{},\"profile_artifact\":{},\"instance_commitment\":{},\"s1_instance\":{},\"retained_target_payload\":{}}}",
                jstr(&p.root.to_string_lossy()),
                p.anchor_checked,
                p.prefix_leaves,
                p.files_indexed,
                jstr(&p.request.to_string_lossy()),
                jstr(&p.profile_artifact.to_string_lossy()),
                jstr(&p.instance_commitment.to_string_lossy()),
                jstr(&p.s1_instance.to_string_lossy()),
                opt(&p.retained_target_payload)
            );
            ExitCode::SUCCESS
        }
        Err(f) => {
            println!("{{\"g5\":\"FAIL\",\"reason\":{},\"detail\":{}}}", jstr(f.reason), jstr(&f.detail));
            ExitCode::from(30)
        }
    }
}
