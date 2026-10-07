//! CANDIDATE S3 acceptance-layer code (G5). Not ratified, not frozen, not adopted.
//!
//! Role (spec/capture-format.md, S3_PREREG s6.1): artifact correspondence between a capture directory and its `request.cbor`.
//! It decodes `request.cbor` ONLY through the pinned frozen `p10_replay::request::decode_request`, reads `capture.json` through the
//! frozen duplicate-aware JSON type `p10_replay::statement::Json`, compares raw bytes, and accounts for every record and every file.
//! It implements NO P10 rule: no configuration, identity, fingerprint, lifecycle, coverage, signature or Receipt check, and it never
//! parses or re-encodes a signed object.
//!
//! The first failed check (fixed order) is reported with a stable reason code. A failure means: the S2b replay, the S2a runner and the
//! post-S2a stage MUST NOT be called.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Component, Path, PathBuf};

use p10_replay::request::decode_request;
use p10_replay::statement::Json;
use sha2::{Digest, Sha256};

pub const FORMAT_ID: &str = "P10-S3-CaptureIndex-v0-candidate";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fail {
    pub reason: &'static str,
    pub detail: String,
}

fn fail<T>(reason: &'static str, detail: impl Into<String>) -> Result<T, Fail> {
    Err(Fail { reason, detail: detail.into() })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pass {
    pub root: PathBuf,
    pub request: PathBuf,
    pub profile_artifact: PathBuf,
    pub instance_commitment: PathBuf,
    pub s1_instance: PathBuf,
    pub retained_target_payload: Option<PathBuf>,
    pub prefix_leaves: usize,
    pub files_indexed: usize,
    pub anchor_checked: bool,
}

pub fn sha256_hex(b: &[u8]) -> String {
    Sha256::digest(b).iter().map(|x| format!("{x:02x}")).collect()
}

// ---------------------------------------------------------------------------------------------- index model

struct FileRef {
    label: String,
    path: String,
    sha256: String,
}

struct PrefixEntry {
    index: u64,
    file: usize, // index into files
    origin_issuer: bool,
}

struct Index {
    files: Vec<FileRef>,
    request: usize,
    prefix: Vec<PrefixEntry>,
    submissions: Vec<(u64, usize)>,
    receipts: Vec<(u64, usize, bool)>,
    detached: Vec<(u64, usize)>,
    target_index: u64,
    profile: usize,
    inst: usize,
    ib: usize,
    retained: Option<usize>,
}

fn members<'a>(j: &'a Json, keys: &[&str], at: &str) -> Result<Vec<&'a Json>, Fail> {
    let Json::Object(o) = j else { return fail("E_INDEX_MALFORMED", format!("{at}: not an object")) };
    if o.len() != keys.len() {
        return fail("E_INDEX_MALFORMED", format!("{at}: members must be exactly {keys:?}"));
    }
    let mut out = Vec::new();
    for k in keys {
        match o.iter().find(|(n, _)| n == k) {
            Some((_, v)) => out.push(v),
            None => return fail("E_INDEX_MALFORMED", format!("{at}: missing member {k}")),
        }
    }
    Ok(out)
}

fn text<'a>(j: &'a Json, at: &str) -> Result<&'a str, Fail> {
    match j {
        Json::String(s) => Ok(s),
        _ => fail("E_INDEX_MALFORMED", format!("{at}: not a string")),
    }
}

fn arr<'a>(j: &'a Json, at: &str) -> Result<&'a [Json], Fail> {
    match j {
        Json::Array(a) => Ok(a),
        _ => fail("E_INDEX_MALFORMED", format!("{at}: not an array")),
    }
}

fn index_of(j: &Json, at: &str) -> Result<u64, Fail> {
    let s = text(j, at)?;
    let ok = s == "0" || (!s.is_empty() && !s.starts_with('0') && s.len() <= 19 && s.bytes().all(|b| b.is_ascii_digit()));
    if !ok {
        return fail("E_INDEX_MALFORMED", format!("{at}: index must be a canonical decimal string, got {s:?}"));
    }
    s.parse::<u64>().or_else(|_| fail("E_INDEX_MALFORMED", format!("{at}: index out of range")))
}

fn sha_of(j: &Json, at: &str) -> Result<String, Fail> {
    let s = text(j, at)?;
    if s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        Ok(s.to_string())
    } else {
        fail("E_INDEX_MALFORMED", format!("{at}: sha256 must be 64 lowercase hex characters"))
    }
}

fn add_file(files: &mut Vec<FileRef>, label: String, path: &Json, sha: &Json) -> Result<usize, Fail> {
    let p = text(path, &format!("{label}.path"))?.to_string();
    let s = sha_of(sha, &format!("{label}.sha256"))?;
    files.push(FileRef { label, path: p, sha256: s });
    Ok(files.len() - 1)
}

fn file_ref(files: &mut Vec<FileRef>, j: &Json, label: &str) -> Result<usize, Fail> {
    let m = members(j, &["path", "sha256"], label)?;
    add_file(files, label.to_string(), m[0], m[1])
}

fn parse_index(bytes: &[u8]) -> Result<Index, Fail> {
    let json: Json = serde_json::from_slice(bytes).or_else(|e| fail("E_INDEX_MALFORMED", format!("capture.json: {e}")))?;
    let top = members(
        &json,
        &["format", "request", "prefix", "submissions", "receipts", "detached_payloads", "target", "material", "public_keys", "provenance"],
        "capture.json",
    )?;
    if text(top[0], "format")? != FORMAT_ID {
        return fail("E_INDEX_MALFORMED", format!("format must be {FORMAT_ID}"));
    }
    let mut files = Vec::new();
    let request = file_ref(&mut files, top[1], "request")?;
    let mut prefix = Vec::new();
    for (k, it) in arr(top[2], "prefix")?.iter().enumerate() {
        let m = members(it, &["index", "path", "sha256", "origin", "role"], &format!("prefix[{k}]"))?;
        let index = index_of(m[0], &format!("prefix[{k}].index"))?;
        let origin = text(m[3], "origin")?;
        if origin != "issuer" && origin != "ts" {
            return fail("E_INDEX_MALFORMED", format!("prefix[{k}].origin must be issuer or ts"));
        }
        text(m[4], "role")?;
        let file = add_file(&mut files, format!("prefix[{index}]"), m[1], m[2])?;
        prefix.push(PrefixEntry { index, file, origin_issuer: origin == "issuer" });
    }
    let mut submissions = Vec::new();
    for (k, it) in arr(top[3], "submissions")?.iter().enumerate() {
        let m = members(it, &["index", "path", "sha256"], &format!("submissions[{k}]"))?;
        let index = index_of(m[0], "submissions.index")?;
        submissions.push((index, add_file(&mut files, format!("submission[{index}]"), m[1], m[2])?));
    }
    let mut receipts = Vec::new();
    for (k, it) in arr(top[4], "receipts")?.iter().enumerate() {
        let m = members(it, &["index", "path", "sha256", "selected"], &format!("receipts[{k}]"))?;
        let index = index_of(m[0], "receipts.index")?;
        let sel = match m[3] {
            Json::Bool(b) => *b,
            _ => return fail("E_INDEX_MALFORMED", "receipts.selected must be a boolean"),
        };
        receipts.push((index, add_file(&mut files, format!("receipt[{index}]"), m[1], m[2])?, sel));
    }
    let mut detached = Vec::new();
    for (k, it) in arr(top[5], "detached_payloads")?.iter().enumerate() {
        let m = members(it, &["index", "path", "sha256"], &format!("detached_payloads[{k}]"))?;
        let index = index_of(m[0], "detached.index")?;
        detached.push((index, add_file(&mut files, format!("detached[{index}]"), m[1], m[2])?));
    }
    let t = members(top[6], &["index"], "target")?;
    let target_index = index_of(t[0], "target.index")?;
    let mat = members(top[7], &["profile_artifact", "instance_commitment", "s1_instance", "retained_target_payload"], "material")?;
    let profile = file_ref(&mut files, mat[0], "material.profile_artifact")?;
    let inst = file_ref(&mut files, mat[1], "material.instance_commitment")?;
    let ib = file_ref(&mut files, mat[2], "material.s1_instance")?;
    let ret = arr(mat[3], "material.retained_target_payload")?;
    let retained = match ret.len() {
        0 => None,
        1 => Some(file_ref(&mut files, &ret[0], "material.retained_target_payload")?),
        _ => return fail("E_INDEX_MALFORMED", "material.retained_target_payload: at most one entry"),
    };
    for (k, it) in arr(top[8], "public_keys")?.iter().enumerate() {
        let m = members(it, &["name", "path", "sha256"], &format!("public_keys[{k}]"))?;
        let name = text(m[0], "public_keys.name")?.to_string();
        add_file(&mut files, format!("public_key[{name}]"), m[1], m[2])?;
    }
    for (k, it) in arr(top[9], "provenance")?.iter().enumerate() {
        let m = members(it, &["path", "sha256"], &format!("provenance[{k}]"))?;
        add_file(&mut files, format!("provenance[{k}]"), m[0], m[1])?;
    }
    Ok(Index { files, request, prefix, submissions, receipts, detached, target_index, profile, inst, ib, retained })
}

// ---------------------------------------------------------------------------------------------- path policy and inventory

/// A capture path is relative, uses `/` separators, has only normal components, and is not `capture.json`.
pub fn path_ok(p: &str) -> bool {
    if p.is_empty() || p.starts_with('/') || p.contains('\\') || p.contains('\0') || p == "capture.json" {
        return false;
    }
    if p.split('/').any(|c| c.is_empty() || c == "." || c == "..") {
        return false;
    }
    Path::new(p).components().all(|c| matches!(c, Component::Normal(_)))
}

fn walk(root: &Path, rel: &Path, out: &mut BTreeSet<String>) -> Result<(), Fail> {
    let dir = root.join(rel);
    let rd = fs::read_dir(&dir).or_else(|e| fail("E_CAPTURE_UNREADABLE", format!("{}: {e}", dir.display())))?;
    for ent in rd {
        let ent = ent.or_else(|e| fail("E_CAPTURE_UNREADABLE", e.to_string()))?;
        let r = rel.join(ent.file_name());
        let md = fs::symlink_metadata(root.join(&r)).or_else(|e| fail("E_CAPTURE_UNREADABLE", e.to_string()))?;
        let name = r.to_string_lossy().replace('\\', "/");
        if md.file_type().is_symlink() {
            return fail("E_PATH_UNSAFE", format!("{name}: symbolic link"));
        } else if md.is_dir() {
            walk(root, &r, out)?;
        } else if md.is_file() {
            out.insert(name);
        } else {
            return fail("E_PATH_UNSAFE", format!("{name}: not a regular file or directory"));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------- the checker

pub fn check_capture(root: &Path, anchor: Option<&str>) -> Result<Pass, Fail> {
    // C0 index bytes and optional external anchor (the hash of capture.json recorded outside the capture, e.g. in MANIFEST.sha256)
    let index_bytes = fs::read(root.join("capture.json")).or_else(|e| fail("E_CAPTURE_UNREADABLE", format!("capture.json: {e}")))?;
    let anchor_checked = if let Some(a) = anchor {
        if sha256_hex(&index_bytes) != a {
            return fail("E_INDEX_ANCHOR_MISMATCH", format!("sha256(capture.json) = {} but the anchor is {a}", sha256_hex(&index_bytes)));
        }
        true
    } else {
        false
    };
    // C1 index syntax and shape
    let ix = parse_index(&index_bytes)?;
    // C2 path policy and uniqueness
    let mut seen = BTreeSet::new();
    for f in &ix.files {
        if !path_ok(&f.path) {
            return fail("E_PATH_UNSAFE", format!("{}: unsafe path {:?}", f.label, f.path));
        }
        if !seen.insert(f.path.clone()) {
            return fail("E_PATH_DUPLICATE", format!("{}: path {:?} is indexed more than once", f.label, f.path));
        }
    }
    // C3 inventory: every indexed file exists, every file on disk is indexed (capture.json excepted); no symlinks
    let mut on_disk = BTreeSet::new();
    walk(root, Path::new(""), &mut on_disk)?;
    on_disk.remove("capture.json");
    for f in &ix.files {
        if !on_disk.contains(&f.path) {
            return fail("E_FILE_MISSING", format!("{}: {}", f.label, f.path));
        }
    }
    if let Some(extra) = on_disk.difference(&seen).next() {
        return fail("E_FILE_NOT_INDEXED", extra.clone());
    }
    // C4 hashes of every indexed file
    let mut data: Vec<Vec<u8>> = Vec::with_capacity(ix.files.len());
    for f in &ix.files {
        let b = fs::read(root.join(&f.path)).or_else(|e| fail("E_CAPTURE_UNREADABLE", format!("{}: {e}", f.path)))?;
        if sha256_hex(&b) != f.sha256 {
            return fail("E_FILE_HASH_MISMATCH", format!("{} ({}): sha256 {} != indexed {}", f.label, f.path, sha256_hex(&b), f.sha256));
        }
        data.push(b);
    }
    // C5 index structure
    let mut pidx: BTreeMap<u64, &PrefixEntry> = BTreeMap::new();
    for e in &ix.prefix {
        if pidx.insert(e.index, e).is_some() {
            return fail("E_PREFIX_DUPLICATE_INDEX", format!("prefix index {} appears more than once", e.index));
        }
    }
    if pidx.is_empty() {
        return fail("E_PREFIX_NOT_CONTIGUOUS", "empty prefix");
    }
    for (k, i) in pidx.keys().enumerate() {
        if *i != k as u64 {
            return fail("E_PREFIX_NOT_CONTIGUOUS", format!("expected index {k}, found {i}"));
        }
    }
    let mut sub: BTreeMap<u64, usize> = BTreeMap::new();
    for (i, f) in &ix.submissions {
        if !pidx.contains_key(i) {
            return fail("E_SUBMISSION_INDEX_UNKNOWN", format!("submission for index {i} which is not in the prefix"));
        }
        if sub.insert(*i, *f).is_some() {
            return fail("E_SUBMISSION_DUPLICATE", format!("two submissions for index {i}"));
        }
    }
    for e in &ix.prefix {
        if e.origin_issuer && !sub.contains_key(&e.index) {
            return fail("E_SUBMISSION_MISSING", format!("issuer-originated prefix index {} has no submission file", e.index));
        }
    }
    if !pidx.contains_key(&ix.target_index) {
        return fail("E_TARGET_INDEX_UNKNOWN", format!("target index {} is not in the prefix", ix.target_index));
    }
    let mut seen_r = BTreeSet::new();
    let mut selected: Vec<(u64, usize)> = Vec::new();
    for (i, f, s) in &ix.receipts {
        if !seen_r.insert(*i) {
            return fail("E_RECEIPT_DUPLICATE", format!("two receipts for index {i}"));
        }
        if *s {
            selected.push((*i, *f));
        }
    }
    if selected.len() != 1 || selected[0].0 != ix.target_index {
        return fail("E_RECEIPT_SELECTION", format!("exactly one receipt, for the target index {}, must be selected (found {})", ix.target_index, selected.len()));
    }
    let mut det: BTreeMap<u64, usize> = BTreeMap::new();
    for (i, f) in &ix.detached {
        if det.insert(*i, *f).is_some() {
            return fail("E_DETACHED_DUPLICATE", format!("two detached payloads for index {i}"));
        }
    }
    // C6 frozen request decoder
    let req_bytes = &data[ix.request];
    let req = decode_request(req_bytes).or_else(|e| fail("E_REQUEST_DECODE", format!("{e}")))?;
    // C7 correspondence: every supplied record is accounted for, none deduplicated
    let mut counts: BTreeMap<u64, usize> = BTreeMap::new();
    for l in &req.material.leaves {
        *counts.entry(l.index).or_insert(0) += 1;
    }
    if let Some((i, n)) = counts.iter().find(|(_, n)| **n > 1) {
        return fail("E_REQUEST_LEAF_DUPLICATE", format!("request.cbor carries {n} records for index {i}"));
    }
    if let Some(i) = counts.keys().find(|i| !pidx.contains_key(i)) {
        return fail("E_REQUEST_LEAF_UNMATCHED", format!("request.cbor record for index {i} has no capture file"));
    }
    if let Some(i) = pidx.keys().find(|i| !counts.contains_key(i)) {
        return fail("E_PREFIX_FILE_UNMATCHED", format!("capture file for index {i} has no record in request.cbor"));
    }
    for l in &req.material.leaves {
        let f = pidx[&l.index].file;
        if l.statement_bytes != data[f] {
            return fail("E_LEAF_BYTES_MISMATCH", format!("index {}: request.cbor bytes differ from {}", l.index, ix.files[f].path));
        }
    }
    match &req.material.selected_receipt_bytes {
        None => return fail("E_RECEIPT_ABSENT", "request.cbor carries no selected Receipt"),
        Some(b) => {
            if *b != data[selected[0].1] {
                return fail("E_RECEIPT_BYTES_MISMATCH", format!("request.cbor Receipt differs from {}", ix.files[selected[0].1].path));
            }
        }
    }
    match &req.material.target_registered_statement_bytes {
        None => return fail("E_TARGET_ABSENT", "request.cbor carries no target statement"),
        Some(b) => {
            let f = pidx[&ix.target_index].file;
            if *b != data[f] {
                return fail("E_TARGET_BYTES_MISMATCH", format!("request.cbor target differs from {}", ix.files[f].path));
            }
        }
    }
    for (i, b) in &req.material.detached_statement_payloads {
        match det.get(i) {
            None => return fail("E_DETACHED_UNMATCHED", format!("request.cbor detached payload for index {i} has no capture file")),
            Some(f) if *b != data[*f] => return fail("E_DETACHED_BYTES_MISMATCH", format!("index {i}: bytes differ from {}", ix.files[*f].path)),
            Some(_) => {}
        }
    }
    if let Some(i) = det.keys().find(|i| !req.material.detached_statement_payloads.contains_key(i)) {
        return fail("E_DETACHED_FILE_UNMATCHED", format!("capture detached payload for index {i} has no record in request.cbor"));
    }
    // C8 submitted registered-form bytes equal the exported leaf bytes (I4)
    for (i, f) in &sub {
        if data[*f] != data[pidx[i].file] {
            return fail("E_SUBMISSION_MISMATCH", format!("index {i}: submitted bytes differ from the exported leaf {}", ix.files[pidx[i].file].path));
        }
    }
    Ok(Pass {
        root: root.to_path_buf(),
        request: root.join(&ix.files[ix.request].path),
        profile_artifact: root.join(&ix.files[ix.profile].path),
        instance_commitment: root.join(&ix.files[ix.inst].path),
        s1_instance: root.join(&ix.files[ix.ib].path),
        retained_target_payload: ix.retained.map(|f| root.join(&ix.files[f].path)),
        prefix_leaves: ix.prefix.len(),
        files_indexed: ix.files.len(),
        anchor_checked,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_policy() {
        for ok in ["prefix/000000.cose", "a", "a/b/c.bin"] {
            assert!(path_ok(ok), "{ok}");
        }
        for bad in ["", "/etc/passwd", "../x", "a/../b", "a//b", "./a", "a/.", "a\\b", "capture.json", "a/\0"] {
            assert!(!path_ok(bad), "{bad:?}");
        }
    }

    #[test]
    fn index_numbers() {
        assert_eq!(index_of(&Json::String("0".into()), "t").unwrap(), 0);
        assert_eq!(index_of(&Json::String("12".into()), "t").unwrap(), 12);
        for bad in ["", "01", "-1", "1.0", "x", "99999999999999999999"] {
            assert!(index_of(&Json::String(bad.into()), "t").is_err(), "{bad}");
        }
    }

    #[test]
    fn duplicate_members_and_numbers_are_rejected_by_the_frozen_json_type() {
        assert!(serde_json::from_slice::<Json>(br#"{"a":"1","a":"2"}"#).is_err());
        assert!(serde_json::from_slice::<Json>(br#"{"a":1}"#).is_err());
        assert!(serde_json::from_slice::<Json>(br#"{"a":null}"#).is_err());
    }
}
