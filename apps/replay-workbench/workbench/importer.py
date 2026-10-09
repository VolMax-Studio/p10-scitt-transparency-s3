"""Streamed upload, approved-archive digest check and bounded safe extraction.

Only an archive whose SHA-256 equals the digest in the shipped profile is ever extracted, and nothing from it is executed here.
"""
import hashlib
import os
import re
import secrets
import shutil
import stat
import tarfile
import time

CHUNK = 1 << 20
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ImportRejected(Exception):
    """The archive violates the import contract. `code` is an application reason, never a P10 outcome."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


class Workspace:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        old = os.umask(0o077)
        try:
            for d in ("", "archives", "packages", "runs", "tmp"):
                os.makedirs(os.path.join(self.root, d), mode=0o700, exist_ok=True)
        finally:
            os.umask(old)
        os.chmod(self.root, 0o700)

    def p(self, *parts):
        return os.path.join(self.root, *parts)


def stream_to_file(read, dest, limit, deadline_s=600.0):
    """Copy `read(n)` into `dest`, hashing on the fly. Returns (sha256, size). Raises ImportRejected beyond limit/deadline."""
    h, n, t0 = hashlib.sha256(), 0, time.monotonic()
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                if time.monotonic() - t0 > deadline_s:
                    raise ImportRejected("UPLOAD_TIMEOUT", "upload took too long")
                b = read(min(CHUNK, limit - n + 1))
                if not b:
                    break
                n += len(b)
                if n > limit:
                    raise ImportRejected("UPLOAD_TOO_LARGE", f"more than {limit} bytes")
                h.update(b)
                f.write(b)
    except BaseException:
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise
    return h.hexdigest(), n


def _norm(name, root):
    if not isinstance(name, str) or name == "":
        raise ImportRejected("BAD_MEMBER_NAME", "empty name")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        raise ImportRejected("BAD_MEMBER_NAME", "non-UTF-8 name")
    if "\\" in name or _CONTROL.search(name):
        raise ImportRejected("BAD_MEMBER_NAME", f"backslash or control character in {name!r}")
    if name.startswith("/"):
        raise ImportRejected("ABSOLUTE_PATH", name)
    parts = name.rstrip("/").split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ImportRejected("PATH_TRAVERSAL", name)
    if parts[0] != root:
        raise ImportRejected("WRONG_ROOT", name)
    return "/".join(parts)


def plan_members(tf, root, max_members, max_bytes):
    """First pass: validate every member without writing. Returns a list of (normalized, member)."""
    plan, seen, total = [], set(), 0
    for m in tf:
        if len(plan) >= max_members:
            raise ImportRejected("TOO_MANY_MEMBERS", f"more than {max_members}")
        n = _norm(m.name, root)
        if n in seen:
            raise ImportRejected("DUPLICATE_DESTINATION", n)
        seen.add(n)
        if m.issym() or m.islnk():
            raise ImportRejected("LINK_MEMBER", n)
        if not (m.isreg() or m.isdir()):
            raise ImportRejected("SPECIAL_MEMBER", n)
        if m.isreg():
            if m.size < 0:
                raise ImportRejected("BAD_SIZE", n)
            total += m.size
            if total > max_bytes:
                raise ImportRejected("TOO_LARGE", f"declared bytes exceed {max_bytes}")
        plan.append((n, m))
    if not plan:
        raise ImportRejected("EMPTY_ARCHIVE", "")
    # every file's ancestors must be directories that are members, and the root itself must be a directory
    kinds = {n: m.isdir() for n, m in plan}
    if kinds.get(root) is not True:
        raise ImportRejected("MISSING_ROOT", "root directory entry absent")
    for n, m in plan:
        par = n.rpartition("/")[0]
        while par:
            if kinds.get(par) is not True:
                raise ImportRejected("MISSING_PARENT", f"{n} has no directory member {par}")
            par = par.rpartition("/")[0]
    return plan


def extract(archive_path, dest_dir, root, max_members, max_bytes):
    """Extract into the NEW directory `dest_dir` (must not exist). On any error remove only that directory."""
    old = os.umask(0o077)
    try:
        os.mkdir(dest_dir, 0o700)
    finally:
        os.umask(old)
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            plan = plan_members(tf, root, max_members, max_bytes)
        written = 0
        with tarfile.open(archive_path, "r:gz") as tf:
            names = {n: m for n, m in plan}
            for m in tf:                      # second pass walks the same stream; only planned names are written
                n = _norm(m.name, root)
                if names.get(n) is None or names[n].offset != m.offset:
                    raise ImportRejected("ARCHIVE_CHANGED", n)
                target = os.path.join(dest_dir, *n.split("/"))
                parent = os.path.dirname(target)
                real = os.path.realpath(parent)
                if os.path.commonpath([real, os.path.realpath(dest_dir)]) != os.path.realpath(dest_dir):
                    raise ImportRejected("ESCAPE", n)
                if m.isdir():
                    os.makedirs(target, mode=0o700, exist_ok=True)
                    continue
                if os.path.islink(parent) or not os.path.isdir(parent):
                    raise ImportRejected("BAD_ANCESTOR", n)
                mode = 0o700 if (m.mode & 0o111) else 0o600   # ordinary owner exec bit retained; no group/other/setuid/setgid/sticky
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
                got = 0
                with os.fdopen(fd, "wb") as out:
                    src = tf.extractfile(m)
                    while True:
                        b = src.read(CHUNK)
                        if not b:
                            break
                        got += len(b)
                        written += len(b)
                        if got > m.size or written > max_bytes:
                            raise ImportRejected("TOO_LARGE", f"written bytes exceed declared size for {n}")
                        out.write(b)
                if got != m.size:
                    raise ImportRejected("SHORT_MEMBER", n)
                os.utime(target, (m.mtime, m.mtime))
        return {"members": len(plan), "bytes": written}
    except tarfile.TarError as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ImportRejected("BAD_ARCHIVE", type(e).__name__)
    except BaseException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise


def import_package(ws, read, profile):
    """Stream, verify the approved digest, then extract (or reuse) the managed package.

    Returns a dict with app_status SUPPORTED or UNSUPPORTED_PACKAGE. Raises ImportRejected for contract violations.
    """
    lim = profile["limits"]
    tmp = ws.p("tmp", "upload-" + secrets.token_hex(8))
    digest, size = stream_to_file(read, tmp, lim["upload_bytes"])
    try:
        want = profile["archive"]["sha256"]
        if digest != want:
            return {"app_status": "UNSUPPORTED_PACKAGE", "sha256": digest, "bytes": size,
                    "detail": "Archive digest is not the approved rev2 package; nothing was extracted or executed."}
        pkg = ws.p("packages", digest)
        arch_dir = ws.p("archives", digest)
        if not os.path.isdir(arch_dir):
            os.makedirs(arch_dir, mode=0o700, exist_ok=True)
            os.replace(tmp, os.path.join(arch_dir, profile["archive"]["name"]))
        reused = os.path.isdir(os.path.join(pkg, profile["archive"]["root"]))
        info = {"members": None, "bytes": None}
        if not reused:
            part = ws.p("packages", digest + ".partial-" + secrets.token_hex(4))
            info = extract(os.path.join(arch_dir, profile["archive"]["name"]), part, profile["archive"]["root"],
                           lim["members"], lim["extracted_bytes"])
            if os.path.exists(pkg):
                shutil.rmtree(part, ignore_errors=True)
            else:
                os.rename(part, pkg)
        return {"app_status": "SUPPORTED", "package_id": digest, "sha256": digest, "bytes": size, "reused": reused, **info}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
