"""Real-browser navigation check (skipped when node, Playwright or Chromium are not available)."""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest

from . import fakes
from .test_jobs import JobBase, PKG
from .test_server import TOKEN
from workbench import server

PW = os.environ.get("PLAYWRIGHT_MODULE", "/opt/node-tools/node_modules/playwright")
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "browser_check.js")


@unittest.skipUnless(shutil.which("node") and os.path.isdir(PW) and os.path.exists(CHROMIUM), "node, Playwright and Chromium are required")
class BrowserNavigation(JobBase):
    def test_home_module_settings_navigation_with_a_running_synthetic_job(self):
        script_path = os.path.join(self.t, "wrapper.sh")
        m = self.manager(fakes.wrapper_script(0, verdict=fakes.VERDICT_BYTES, info=fakes.dumps(fakes.good_info()), body="echo finished earlier"))
        self.srv, self.app = server.create(self.ws, m.module, m, TOKEN, 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.app.settings.save({"lean_bin": "/opt/lean 4/bin", "allowed_signers": "", "deadline_minutes": 60})
        earlier = m.start("run", PKG, "/opt/lean 4/bin", None, None)               # an earlier job that finished (synthetic, stub)
        self.done(m, earlier)
        with open(script_path, "w") as f:                                          # from now on the stub wrapper never finishes by itself
            f.write(fakes.wrapper_script(0, body="sleep 600"))
        url = f"http://127.0.0.1:{self.app.port}/#token={TOKEN}"
        shots = os.environ.get("SHOT_DIR")
        args = ["node", SCRIPT, url] + ([shots] if shots else [])
        r = subprocess.run(args, capture_output=True, text=True, timeout=240, env=dict(os.environ, PLAYWRIGHT_MODULE=PW, PLAYWRIGHT_CHROMIUM=CHROMIUM))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("BROWSER CHECK PASSED", r.stdout)


if __name__ == "__main__":
    unittest.main()
