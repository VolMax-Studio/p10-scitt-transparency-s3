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

from workbench import importer, jobs, modules, server  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default=os.path.join(os.path.expanduser("~"), ".local", "share", "p10-replay-workbench"),
                    help="private workspace (default: %(default)s)")
    ap.add_argument("--port", type=int, default=0, help="loopback port (default: any free port)")
    ap.add_argument("--deadline-minutes", type=int, default=None, help="default job deadline in minutes (profile default: 60)")
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    a = ap.parse_args(argv)
    module = modules.default_module()
    ws = importer.Workspace(a.workspace)
    try:
        mgr = jobs.JobManager(ws, module, default_deadline_minutes=a.deadline_minutes)
    except jobs.WorkspaceInUse as e:
        print("Cannot start:", e, file=sys.stderr)
        print("Stop the other instance first, or use --workspace with a different directory.", file=sys.stderr)
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
