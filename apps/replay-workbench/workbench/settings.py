"""Persistent host settings: Lean bin directory, optional public allowed-signers path, job deadline.

Stored in the workspace as settings.json (owner-only, atomic writes, strict JSON, unknown keys rejected). The file holds only these three
values: no token, key or file contents. Restoring settings only fills input fields; it never restores a readiness result, starts a job or
earns a badge. Paths may legitimately lie outside the workspace; they get the same validation as inputs of a job start.
"""
import json
import os
import secrets
import stat

from . import records as R
from .jobs import abs_path_ok

FORMAT = "p10-replay-workbench-settings-v0"
FIELDS = ("lean_bin", "allowed_signers", "deadline_minutes")
MAX_BYTES = 64 * 1024
MAX_DEADLINE_MINUTES = 24 * 60


class SettingsError(ValueError):
    pass


class SettingsStore:
    def __init__(self, path, default_deadline_minutes, min_deadline_minutes=1):
        self.path = path
        self.default_deadline = default_deadline_minutes
        self.min_deadline = min_deadline_minutes

    # ---- validation ---------------------------------------------------------------------------------------------------------
    def defaults(self):
        return {"lean_bin": "", "allowed_signers": "", "deadline_minutes": self.default_deadline}

    def validate(self, obj):
        """Return a normalized settings dict or raise SettingsError. Every problem is reported; nothing is coerced."""
        if not isinstance(obj, dict):
            raise SettingsError("settings must be a JSON object")
        extra = sorted(set(obj) - set(FIELDS) - {"format"})
        if extra:
            raise SettingsError("unknown fields: " + ", ".join(extra))
        if "format" in obj and obj["format"] != FORMAT:
            raise SettingsError("unsupported settings format")
        out = self.defaults()
        for k in ("lean_bin", "allowed_signers"):
            if k in obj:
                v = obj[k]
                if not isinstance(v, str):
                    raise SettingsError(f"{k} must be a string")
                if v != "" and not abs_path_ok(v):
                    raise SettingsError(f"{k} must be empty or a normalized absolute path")
                out[k] = v
        if "deadline_minutes" in obj:
            d = obj["deadline_minutes"]
            if isinstance(d, bool) or not isinstance(d, (int, float)) or d != d or not (self.min_deadline <= d <= MAX_DEADLINE_MINUTES):
                raise SettingsError(f"deadline_minutes must be a number between {self.min_deadline} and {MAX_DEADLINE_MINUTES}")
            out["deadline_minutes"] = d
        return out

    # ---- load / save --------------------------------------------------------------------------------------------------------
    def load(self):
        """Return (settings, warning). Missing file: defaults, no warning. Unreadable or invalid file: safe defaults and a clear warning."""
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)    # NONBLOCK: a FIFO must not hang the UI
        except FileNotFoundError:
            return self.defaults(), None
        except OSError as e:
            return self.defaults(), f"Saved host settings could not be opened ({type(e).__name__}); defaults are used."
        try:
            with os.fdopen(fd, "rb") as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                    return self.defaults(), "Saved host settings are not a regular file; defaults are used."
                raw = f.read(MAX_BYTES + 1)
        except OSError as e:
            return self.defaults(), f"Saved host settings could not be read ({type(e).__name__}); defaults are used."
        try:
            return self.validate(R.parse_strict(raw, MAX_BYTES)), None
        except (R.RecordError, SettingsError) as e:
            return self.defaults(), f"Saved host settings are invalid ({e}); defaults are used. Saving new settings replaces the file."

    def save(self, obj):
        """Validate and write atomically with owner-only permissions. Returns the saved settings."""
        s = self.validate(obj)
        body = json.dumps({"format": FORMAT, **s}, indent=1, sort_keys=True).encode() + b"\n"
        tmp = f"{self.path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)        # replaces a symlink or a malformed file itself; never writes through a link
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return s
