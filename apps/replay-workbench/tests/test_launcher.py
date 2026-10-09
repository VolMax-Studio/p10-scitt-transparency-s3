import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from . import fakes
from workbench import launcher as L

RUN_PY = os.path.join(fakes.APP, "run.py")
NASTY = ["/plain/path/run.py", "/dir with spaces/run.py", "/pct/100%/%s %d/run.py", "/q/\"double\"/a'single'/run.py", "/back\\slash/run.py",
         "/dollar/$HOME/`id`/run.py", "/sym/a;b&c|d>e<f~g#h*i?j(k)/run.py", "/uni/ünïcödé/日本/run.py", "/tab\tno"]


class Quoting(unittest.TestCase):
    def test_every_nasty_path_round_trips_through_the_reference_parser(self):
        for p in NASTY[:-1]:
            self.assertEqual(L.exec_parse(L.exec_quote(p) + " --pause-on-error"), [p, "--pause-on-error"], p)

    def test_percent_is_doubled_and_never_a_field_code(self):
        q = L.exec_quote("/a/%f/%U/100%")
        self.assertNotIn("%f", q.replace("%%", ""))
        self.assertEqual(L.exec_parse(q), ["/a/%f/%U/100%"])

    def test_unrepresentable_paths_are_refused(self):
        for bad in ("/a\nb/run.py", "/a\x00b/run.py", "relative/run.py", "", "/tab\tno"):
            with self.assertRaises(L.LauncherError, msg=repr(bad)):
                L.desktop_text("/usr/bin/python3", bad, "/i/icon.svg")
            with self.assertRaises(L.LauncherError, msg=repr(bad)):
                L.desktop_text(bad, "/s/run.py", "/i/icon.svg")

    def test_the_parsed_exec_really_runs_a_script_whose_path_has_spaces_and_percent_characters(self):
        with tempfile.TemporaryDirectory() as t:
            d = os.path.join(t, "my apps 100% %f %U $x `y` \"q\" 'a'")
            os.makedirs(d)
            script = os.path.join(d, "r un.py")
            with open(script, "w") as f:
                f.write("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
            text = L.desktop_text(sys.executable, script, "/i/icon.svg")
            exec_line = [l for l in text.splitlines() if l.startswith("Exec=")][0][5:]
            argv = L.exec_parse(exec_line)
            self.assertEqual(argv, [sys.executable, script, "--pause-on-error"])
            out = subprocess.run(argv, capture_output=True, text=True, timeout=30)       # no shell involved
            self.assertEqual(json.loads(out.stdout), ["--pause-on-error"])

    @unittest.skipUnless(shutil.which("desktop-file-validate"), "desktop-file-validate not installed")
    def test_generated_entry_validates(self):
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, "x.desktop")
            with open(f, "w") as fh:
                fh.write(L.desktop_text("/usr/bin/python3", "/dir with spaces/100%/run.py", "/i/p10-replay-workbench.svg"))
            r = subprocess.run(["desktop-file-validate", f], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home dir 100%")
        os.makedirs(self.home)
        self.env = {}
        self.desktop, self.icon = L.paths(self.env, self.home)

    def read(self, p):
        with open(p, "rb") as f:
            return f.read()

    def test_install_creates_a_user_owned_entry_and_icon_under_local_share(self):
        res = L.install("/usr/bin/python3", "/opt/my app/run.py", self.env, self.home)
        self.assertEqual([a for a, _ in res], ["created", "created"])
        self.assertTrue(self.desktop.startswith(os.path.join(self.home, ".local", "share", "applications")))
        self.assertTrue(self.icon.startswith(os.path.join(self.home, ".local", "share", "icons")))
        text = self.read(self.desktop).decode()
        self.assertIn("X-P10-Replay-Workbench-Launcher=1", text)
        self.assertEqual(L.exec_parse([l for l in text.splitlines() if l.startswith("Exec=")][0][5:]), ["/usr/bin/python3", "/opt/my app/run.py", "--pause-on-error"])
        self.assertIn(f"Icon={self.icon}", text)
        self.assertIn("Terminal=true", text)
        for p in (self.desktop, self.icon):
            st = os.stat(p)
            self.assertEqual((st.st_uid, stat.S_IMODE(st.st_mode)), (os.getuid(), 0o644))
        self.assertIn("<svg", self.read(self.icon).decode())
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.desktop)) if n.endswith(".tmp")], [])

    def test_xdg_data_home_is_honoured_when_absolute_and_ignored_otherwise(self):
        x = os.path.join(self.tmp.name, "xdg data")
        self.assertEqual(L.paths({"XDG_DATA_HOME": x}, self.home)[0], os.path.join(x, "applications", "p10-replay-workbench.desktop"))
        self.assertTrue(L.paths({"XDG_DATA_HOME": "relative"}, self.home)[0].startswith(os.path.join(self.home, ".local", "share")))

    def test_repeated_installation_is_idempotent_and_updates_a_moved_checkout(self):
        L.install("/usr/bin/python3", "/opt/a/run.py", self.env, self.home)
        before = (self.read(self.desktop), self.read(self.icon))
        res = L.install("/usr/bin/python3", "/opt/a/run.py", self.env, self.home)
        self.assertEqual([a for a, _ in res], ["unchanged", "unchanged"])
        self.assertEqual((self.read(self.desktop), self.read(self.icon)), before)
        res = L.install("/usr/bin/python3", "/opt/b/run.py", self.env, self.home)
        self.assertEqual([a for a, _ in res], ["unchanged", "updated"])
        self.assertIn(b"/opt/b/run.py", self.read(self.desktop))

    def test_an_unrelated_file_with_the_same_name_is_never_overwritten(self):
        os.makedirs(os.path.dirname(self.desktop))
        with open(self.desktop, "w") as f:
            f.write("[Desktop Entry]\nName=Somebody else\n")
        with self.assertRaises(L.LauncherError):
            L.install("/usr/bin/python3", "/opt/a/run.py", self.env, self.home)
        self.assertEqual(self.read(self.desktop), b"[Desktop Entry]\nName=Somebody else\n")
        self.assertFalse(os.path.exists(self.icon), "nothing is written when any target is foreign")

    def test_an_unrelated_icon_with_the_same_name_blocks_installation(self):
        os.makedirs(os.path.dirname(self.icon))
        with open(self.icon, "w") as f:
            f.write("<svg>mine</svg>")
        with self.assertRaises(L.LauncherError):
            L.install("/usr/bin/python3", "/opt/a/run.py", self.env, self.home)
        self.assertEqual(self.read(self.icon), b"<svg>mine</svg>")
        self.assertFalse(os.path.exists(self.desktop))

    def test_symlinks_are_not_followed_on_install_or_remove(self):
        os.makedirs(os.path.dirname(self.desktop))
        victim = os.path.join(self.tmp.name, "victim.desktop")
        with open(victim, "w") as f:
            f.write("X-P10-Replay-Workbench-Launcher=1\n")           # even a marked target must not be reached through a link
        os.symlink(victim, self.desktop)
        with self.assertRaises(L.LauncherError):
            L.install("/usr/bin/python3", "/opt/a/run.py", self.env, self.home)
        self.assertEqual(L.remove(self.env, self.home)[0][0], "kept")
        self.assertTrue(os.path.exists(victim))
        self.assertEqual(self.read(victim), b"X-P10-Replay-Workbench-Launcher=1\n")

    def test_removal_deletes_only_what_this_application_created(self):
        L.install("/usr/bin/python3", "/opt/a/run.py", self.env, self.home)
        other_desktop = os.path.join(os.path.dirname(self.desktop), "other.desktop")
        other_icon = os.path.join(os.path.dirname(self.icon), "other.svg")
        for p in (other_desktop, other_icon):
            with open(p, "w") as f:
                f.write("keep me")
        res = L.remove(self.env, self.home)
        self.assertEqual([a for a, _ in res], ["removed", "removed"])
        self.assertFalse(os.path.exists(self.desktop) or os.path.exists(self.icon))
        self.assertEqual((self.read(other_desktop), self.read(other_icon)), (b"keep me", b"keep me"))
        self.assertTrue(os.path.isdir(os.path.dirname(self.desktop)), "directories are left in place")
        self.assertEqual([a for a, _ in L.remove(self.env, self.home)], ["absent", "absent"])           # repeated removal is harmless

    def test_removal_keeps_a_foreign_file_with_the_same_name(self):
        os.makedirs(os.path.dirname(self.desktop))
        with open(self.desktop, "w") as f:
            f.write("[Desktop Entry]\nName=Somebody else\n")
        self.assertEqual(L.remove(self.env, self.home)[0], ("kept", self.desktop))
        self.assertTrue(os.path.exists(self.desktop))

    def test_module_has_no_privilege_or_system_changes(self):
        with open(L.__file__) as f:
            src = f.read()
        for word in ("subprocess", "os.system", "sudo", "pkexec", "sysctl", "apparmor", "setuid", "chmod("):
            self.assertNotIn(word, src.replace("no sudo", "").replace("No sudo", ""), word)
        text = L.desktop_text("/usr/bin/python3", "/opt/a/run.py", "/i.svg").lower()
        for word in ("sudo", "pkexec", "sysctl", "apparmor", "su -"):
            self.assertNotIn(word, text)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "h o m e")
        os.makedirs(self.home)
        self.bin = os.path.join(self.tmp.name, "spy bin")
        os.makedirs(self.bin)
        self.spy = os.path.join(self.tmp.name, "spy.log")
        for tool in ("sudo", "pkexec", "sysctl", "aa-status", "apparmor_parser", "systemctl", "update-desktop-database", "apt", "apt-get", "pip", "curl", "wget"):
            p = os.path.join(self.bin, tool)
            with open(p, "w") as f:
                f.write(f"#!/bin/sh\necho {tool} \"$@\" >> '{self.spy}'\nexit 0\n")
            os.chmod(p, 0o755)
        self.env = {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.home, "PYTHONDONTWRITEBYTECODE": "1"}

    def run_cli(self, *args):
        return subprocess.run([sys.executable, RUN_PY, *args], capture_output=True, text=True, env=self.env, timeout=60, stdin=subprocess.DEVNULL)

    def test_install_and_remove_through_run_py_start_nothing_and_call_no_privileged_tool(self):
        r = self.run_cli("--install-launcher")
        self.assertEqual(r.returncode, 0, r.stderr)
        desktop, icon = L.paths({}, self.home)
        self.assertTrue(os.path.isfile(desktop) and os.path.isfile(icon))
        with open(desktop) as f:
            lines = f.read().splitlines()
        argv = L.exec_parse([l for l in lines if l.startswith("Exec=")][0][5:])
        self.assertEqual(argv, [os.path.abspath(sys.executable), RUN_PY, "--pause-on-error"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "share", "p10-replay-workbench")), "no workspace, no job, nothing started")
        self.assertEqual(self.run_cli("--install-launcher").returncode, 0)                  # repeated
        r = self.run_cli("--remove-launcher")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(desktop) or os.path.exists(icon))
        self.assertEqual(self.run_cli("--remove-launcher").returncode, 0)
        self.assertFalse(os.path.exists(self.spy), "no sudo/sysctl/AppArmor/package tool may be invoked")

    def test_launcher_options_take_no_other_options_and_foreign_files_stop_installation(self):
        self.assertEqual(self.run_cli("--install-launcher", "--port", "5000").returncode, 2)
        self.assertEqual(self.run_cli("--install-launcher", "--remove-launcher").returncode, 2)
        desktop, _ = L.paths({}, self.home)
        os.makedirs(os.path.dirname(desktop))
        with open(desktop, "w") as f:
            f.write("foreign")
        r = self.run_cli("--install-launcher")
        self.assertEqual(r.returncode, 2)
        self.assertIn("left untouched", r.stderr)
        with open(desktop) as f:
            self.assertEqual(f.read(), "foreign")


if __name__ == "__main__":
    unittest.main()
