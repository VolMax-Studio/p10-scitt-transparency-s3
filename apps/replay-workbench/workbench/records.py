"""Structural validation of runner output records.

This module does not interpret P10 rules and keeps no list of P10 reason tokens. It checks that a record is bounded UTF-8 JSON
(duplicate keys and non-finite numbers rejected), that the fields the application needs have the expected types, and that the
top-level outcome is one of the runner's documented outcome names. Original bytes are always preserved by the caller.
"""
import hashlib
import json

MAX_RECORD_BYTES = 8 * 1024 * 1024
RUNNER_OUTCOMES = ("BINDING_MATCH", "REJECT", "HALT", "S3-FAIL(packaging)", "S3-FAIL(infrastructure)")


class RecordError(ValueError):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _no_dups(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise RecordError(f"duplicate key {k!r}")
        seen[k] = v
    return seen


def _no_const(name):
    raise RecordError(f"non-finite number {name}")


def parse_strict(data, limit=MAX_RECORD_BYTES):
    """Parse bounded UTF-8 JSON; raises RecordError. The input bytes are not modified."""
    if not isinstance(data, (bytes, bytearray)):
        raise RecordError("record is not bytes")
    if len(data) > limit:
        raise RecordError(f"record larger than {limit} bytes")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as e:
        raise RecordError("record is not valid UTF-8") from e
    if text.startswith("﻿"):
        raise RecordError("record starts with a byte-order mark")
    try:
        return json.loads(text, object_pairs_hook=_no_dups, parse_constant=_no_const)
    except RecordError:
        raise
    except (ValueError, RecursionError) as e:
        raise RecordError(f"invalid JSON: {type(e).__name__}") from e


def read_record(path, limit=MAX_RECORD_BYTES):
    """Return (raw_bytes_or_None, parsed_or_None, problem_or_None). Never raises for ordinary file problems."""
    try:
        with open(path, "rb") as f:
            raw = f.read(limit + 1)
    except FileNotFoundError:
        return None, None, "missing"
    except OSError as e:
        return None, None, f"unreadable ({type(e).__name__})"
    try:
        return raw, parse_strict(raw, limit), None
    except RecordError as e:
        return raw, None, str(e)


def validate_verdict(obj):
    """Structural check of verdict.json; returns a list of problems (empty = structurally valid)."""
    p = []
    if not isinstance(obj, dict):
        return ["verdict is not a JSON object"]
    if obj.get("outcome") not in RUNNER_OUTCOMES:
        p.append("outcome missing or not a known runner outcome name")
    if not isinstance(obj.get("stage"), str):
        p.append("stage missing or not a string")
    r = obj.get("reason")
    if not isinstance(r, dict) or not isinstance(r.get("code"), str):
        p.append("reason missing or without a string code")
    ep = obj.get("executables_pinned")
    if ep is not None:
        if not isinstance(ep, dict) or any(not isinstance(v, bool) for v in ep.values()):
            p.append("executables_pinned is not an object of booleans")
    post = obj.get("post")
    if post is not None and not isinstance(post, dict):
        p.append("post is not an object")
    return p


def validate_run_info(obj):
    p = []
    if not isinstance(obj, dict):
        return ["run-info is not a JSON object"]
    if not isinstance(obj.get("network_isolated"), bool):
        p.append("network_isolated missing or not a boolean")
    for k in ("problems", "tcb_source_mismatch"):
        if not isinstance(obj.get(k), list):
            p.append(f"{k} missing or not a list")
    rs = obj.get("runner_source_sha256")
    if not isinstance(rs, dict) or any(not isinstance(v, str) for v in rs.values()):
        p.append("runner_source_sha256 missing or not an object of strings")
    for k in ("entry_binary_sha256", "g5_binary_sha256"):
        if not isinstance(obj.get(k), str):
            p.append(f"{k} missing or not a string")
    return p
