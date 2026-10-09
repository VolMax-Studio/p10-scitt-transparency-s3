#!/usr/bin/env python3
"""P10 Replay Workbench launcher: loopback-only server for the approved S3 rev2 replay.  Usage: python3 apps/replay-workbench/run.py"""
import argparse
import os
import secrets
import signal
import sys
import threading
import webbrowser

if sys.version_info < (3, 12):
    sys.exit("P10 Replay Workbench needs Python 3.12 or newer (found %s)." % sys.version.split()[0])
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from workbench import importer, jobs, launcher, modules, server  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default=os.path.join(os.path.expanduser("~"), ".local", "share", "p10-replay-workbench"),
                    help="private workspace (default: %(default)s)")
    ap.add_argument("--port", type=int, default=0, help="loopback port (default: 0 = any free port, chosen anew at every start)")
    ap.add_argument("--deadline-minutes", type=int, default=None, help="default job deadline in minutes (profile default: 60)")
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    ap.add_argument("--pause-on-error", action="store_true", help="wait for Enter before exiting after a startup error (used by the desktop launcher)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--install-launcher", action="store_true",
                   help="create a user-level desktop entry and icon under ~/.local/share (no sudo); starts nothing")
    g.add_argument("--remove-launcher", action="store_true", help="remove the desktop entry and icon created by --install-launcher; starts nothing")
    return ap


def _pause(enabled):
    if enabled and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("Press Enter to close this window. ")
        except EOFError:
            pass


def launcher_command(a):
    try:
        if a.install_launcher:
            res = launcher.install(os.path.abspath(sys.executable), os.path.abspath(__file__))
            for action, path in res:
                print(f"{action}: {path}")
            print("The launcher appears as 'P10 Replay Workbench' in your applications menu (log out and in if it does not show up).")
            print("It runs this checkout's run.py; if you move the checkout, run --install-launcher again. Remove it with --remove-launcher.")
        else:
            for action, path in launcher.remove():
                print(f"{action}: {path}")
        return 0
    except (launcher.LauncherError, OSError) as e:
        print("Launcher:", e, file=sys.stderr)
        return 2


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.install_launcher or a.remove_launcher:
        extra = [x for x in (sys.argv[1:] if argv is None else argv) if x not in ("--install-launcher", "--remove-launcher")]
        if extra:
            ap.error("--install-launcher / --remove-launcher take no other options")
        return launcher_command(a)
    module = modules.default_module()
    ws = importer.Workspace(a.workspace)
    try:
        mgr = jobs.JobManager(ws, module, default_deadline_minutes=a.deadline_minutes)
    except jobs.WorkspaceInUse as e:
        print("Cannot start:", e, file=sys.stderr)
        print("Stop the other instance first, or use --workspace with a different directory.", file=sys.stderr)
        _pause(a.pause_on_error)
        return 2
    token = secrets.token_urlsafe(32)
    srv, app = server.create(ws, module, mgr, token, a.port)
    url = f"http://127.0.0.1:{app.port}/#token={token}"
    print("P10 Replay Workbench (loopback only; single user)")
    print("  workspace:", ws.root)
    print("  open this URL in a browser on this machine:")
    print("  " + url)
    print("  Ctrl+C stops the server and any active job.")
    sys.stdout.flush()

    def stop(signum, frame):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)       # closing the launcher's terminal window stops the server and any active job cleanly
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    finally:
        mgr.close()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
