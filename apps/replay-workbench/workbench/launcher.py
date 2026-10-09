"""User-level desktop launcher: a .desktop entry and an SVG icon under $XDG_DATA_HOME (default ~/.local/share).

No sudo, no privileges, no system-wide files, no external commands. Installing or removing never starts a replay and touches only files that carry
this application's marker; an unrelated file with the same name is never overwritten or removed, and symbolic links are never followed.
"""
import os
import secrets

APP_ID = "p10-replay-workbench"
MARKER_KEY = "X-P10-Replay-Workbench-Launcher"
MARKER_SVG = "<!-- p10-replay-workbench-launcher -->"
EXEC_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")
ICON_SVG = f"""<?xml version="1.0" encoding="UTF-8"?>
{MARKER_SVG}
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128" role="img" aria-label="P10 Replay Workbench">
  <rect width="128" height="128" rx="24" fill="#0d1117"/>
  <path d="M30 70 L56 96 L100 40" fill="none" stroke="#3fb950" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="64" y="38" text-anchor="middle" font-family="sans-serif" font-size="26" font-weight="700" fill="#e6edf3">P10</text>
</svg>
"""


class LauncherError(Exception):
    pass


def data_home(env=None, home=None):
    env = os.environ if env is None else env
    x = env.get("XDG_DATA_HOME", "")
    if x and os.path.isabs(x):
        return x
    return os.path.join(home or os.path.expanduser("~"), ".local", "share")


def paths(env=None, home=None):
    base = data_home(env, home)
    return (os.path.join(base, "applications", APP_ID + ".desktop"),
            os.path.join(base, "icons", "hicolor", "scalable", "apps", APP_ID + ".svg"))


def _check_text(label, value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise LauncherError(f"{label} must be non-empty text without control characters or newlines")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise LauncherError(f"{label} is not valid UTF-8")
    if not os.path.isabs(value):
        raise LauncherError(f"{label} must be an absolute path")


def exec_quote(arg):
    """Quote one argument for the Exec key of a desktop entry (Desktop Entry Specification, 'The Exec key').

    A literal % is written %%. An argument with reserved characters is put in double quotes in which " ` $ \\ are backslash-escaped; because the
    value is a key-file string too, every backslash is doubled once more.
    """
    arg = arg.replace("%", "%%")
    if arg == "" or any(c in EXEC_RESERVED for c in arg):
        inner = "".join("\\" + c if c in '"`$\\' else c for c in arg)
        arg = '"' + inner + '"'
    return arg.replace("\\", "\\\\")


def exec_parse(value):
    """Reference parser of an Exec value (key-file unescape, then Exec quoting rules). Used by the tests to prove the quoting round-trips."""
    s, out, i = "", [], 0
    while i < len(value):                 # key-file string escapes
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            s += {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(n, "\\" + n)
            i += 2
        else:
            s += c
            i += 1
    args, cur, inq, i, have = [], "", False, 0, False
    while i < len(s):
        c = s[i]
        if inq:
            if c == "\\" and i + 1 < len(s) and s[i + 1] in '"`$\\':
                cur += s[i + 1]
                i += 2
                continue
            if c == '"':
                inq = False
            else:
                cur += c
        elif c == '"':
            inq, have = True, True
        elif c == " ":
            if have or cur:
                args.append(cur)
            cur, have = "", False
        else:
            cur += c
        i += 1
    if have or cur:
        args.append(cur)
    return [a.replace("%%", "%") for a in args]


def desktop_text(interpreter, script, icon_path):
    for label, v in (("interpreter", interpreter), ("script", script), ("icon", icon_path)):
        _check_text(label, v)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=P10 Replay Workbench\n"
        "Comment=Offline replay of the approved S3 package (local, loopback only)\n"
        f"Exec={exec_quote(interpreter)} {exec_quote(script)} --pause-on-error\n"
        f"Icon={icon_path.replace(chr(92), chr(92) * 2)}\n"
        "Terminal=true\n"
        "Categories=Utility;Development;\n"
        "StartupNotify=false\n"
        f"{MARKER_KEY}=1\n"
    )


def _is_ours(path, marker):
    """True if `path` is a regular file (not a link) that carries our marker."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return marker in f.read(65536)
    except OSError:
        return False


def _write_atomic(path, data, mode):
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o755, exist_ok=True)
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _guard_target(path, marker, what):
    if os.path.lexists(path) and not _is_ours(path, marker):
        raise LauncherError(f"{what} {path} exists and was not created by this application (or is a link); it is left untouched. "
                            "Move it away or remove it yourself, then install again.")


def install(interpreter, script, env=None, home=None):
    """Create or update the launcher. Returns a list of (action, path) with action in {'created', 'updated', 'unchanged'}."""
    desktop, icon = paths(env, home)
    text = desktop_text(interpreter, script, icon)
    _guard_target(desktop, MARKER_KEY + "=1", "Launcher")
    _guard_target(icon, MARKER_SVG, "Icon")
    out = []
    for path, data, mode in ((icon, ICON_SVG.encode(), 0o644), (desktop, text.encode(), 0o644)):
        existed = os.path.lexists(path)
        if existed:
            with open(path, "rb") as f:
                same = f.read() == data
        else:
            same = False
        if not same:
            _write_atomic(path, data, mode)
        out.append(("unchanged" if same else ("updated" if existed else "created"), path))
    return out


def remove(env=None, home=None):
    """Remove the launcher files that this application created. Returns a list of (action, path): removed | absent | kept (not ours)."""
    desktop, icon = paths(env, home)
    out = []
    for path, marker in ((desktop, MARKER_KEY + "=1"), (icon, MARKER_SVG)):
        if not os.path.lexists(path):
            out.append(("absent", path))
        elif _is_ours(path, marker):
            os.unlink(path)
            out.append(("removed", path))
        else:
            out.append(("kept", path))
    return out
