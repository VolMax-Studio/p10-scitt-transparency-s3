import io
import os
import stat
import tempfile
import unittest

from . import fakes
from workbench import importer


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = importer.Workspace(os.path.join(self.tmp.name, "ws"))
        self.addCleanup(self.tmp.cleanup)

    def archive(self, members, name="a.tar.gz"):
        return fakes.make_tar(os.path.join(self.tmp.name, name), members)

    def profile_for(self, path, **limits):
        with open(path, "rb") as f:
            return fakes.test_profile(archive_sha=fakes.sha(f.read()), **limits)

    def do_import(self, path, profile):
        f = open(path, "rb")
        self.addCleanup(f.close)
        return importer.import_package(self.ws, f.read, profile)

    def packages(self):
        return sorted(os.listdir(self.ws.p("packages")))

    # case 1
    def test_unknown_archive_hash_is_not_extracted(self):
        path = self.archive(fakes.good_members())
        prof = fakes.test_profile(archive_sha="f" * 64)
        r = self.do_import(path, prof)
        self.assertEqual(r["app_status"], "UNSUPPORTED_PACKAGE")
        self.assertEqual(self.packages(), [])
        self.assertEqual(os.listdir(self.ws.p("archives")), [])
        self.assertEqual(os.listdir(self.ws.p("tmp")), [])

    def test_approved_archive_is_extracted_safely(self):
        path = self.archive(fakes.good_members())
        prof = self.profile_for(path)
        r = self.do_import(path, prof)
        self.assertEqual(r["app_status"], "SUPPORTED")
        root = os.path.join(self.ws.p("packages", r["package_id"]), "p10-s3-offline")
        self.assertTrue(os.access(os.path.join(root, "verify_offline.sh"), os.X_OK))
        m = os.stat(os.path.join(root, "data", "a.txt")).st_mode
        self.assertEqual(m & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o077), 0)   # setuid bit in the archive is dropped
        self.assertEqual(os.stat(self.ws.p()).st_mode & 0o777, 0o700)
        r2 = self.do_import(path, prof)
        self.assertTrue(r2["reused"])
        self.assertEqual(os.listdir(self.ws.p("tmp")), [])

    # case 2
    def hostile(self, items, code, **limits):
        path = self.archive(items)
        prof = self.profile_for(path, **limits)
        with self.assertRaises(importer.ImportRejected) as c:
            self.do_import(path, prof)
        self.assertEqual(c.exception.code, code)
        self.assertEqual(self.packages(), [], "nothing may remain after a rejected import")
        self.assertEqual(os.listdir(self.ws.p("tmp")), [])

    def test_traversal(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/../evil", "file", b"x", 0o644)], "PATH_TRAVERSAL")

    def test_absolute(self):
        self.hostile(fakes.good_members() + [("/etc/evil", "file", b"x", 0o644)], "ABSOLUTE_PATH")

    def test_wrong_root(self):
        self.hostile(fakes.good_members() + [("other/evil", "file", b"x", 0o644)], "WRONG_ROOT")

    def test_duplicate_destination(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/data/a.txt", "file", b"y", 0o644)], "DUPLICATE_DESTINATION")

    def test_duplicate_after_normalisation(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/data/a.txt/", "file", b"y", 0o644)], "DUPLICATE_DESTINATION")

    def test_symlink(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/link", "sym", "/etc/passwd", 0o777)], "LINK_MEMBER")

    def test_hardlink(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/hl", "hard", "p10-s3-offline/data/a.txt", 0o644)], "LINK_MEMBER")

    def test_special_member(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/fifo", "fifo", None, 0o644)], "SPECIAL_MEMBER")

    def test_backslash_and_control_names(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/a\\b", "file", b"x", 0o644)], "BAD_MEMBER_NAME")
        self.hostile(fakes.good_members() + [("p10-s3-offline/a\x01b", "file", b"x", 0o644)], "BAD_MEMBER_NAME")

    def test_member_count_limit(self):
        self.hostile(fakes.good_members(), "TOO_MANY_MEMBERS", members=3)

    def test_total_size_limit(self):
        self.hostile(fakes.good_members() + [("p10-s3-offline/big", "file", b"x" * 5000, 0o644)], "TOO_LARGE", extracted_bytes=1000)

    def test_missing_parent_directory(self):
        self.hostile([("p10-s3-offline", "dir", None, 0o755), ("p10-s3-offline/x/y.txt", "file", b"x", 0o644)], "MISSING_PARENT")

    def test_upload_limit(self):
        path = self.archive(fakes.good_members())
        prof = self.profile_for(path, upload_bytes=100)
        with self.assertRaises(importer.ImportRejected) as c:
            self.do_import(path, prof)
        self.assertEqual(c.exception.code, "UPLOAD_TOO_LARGE")
        self.assertEqual(os.listdir(self.ws.p("tmp")), [])

    def test_not_a_tar(self):
        path = os.path.join(self.tmp.name, "junk.tar.gz")
        with open(path, "wb") as f:
            f.write(b"not a tarball")
        prof = self.profile_for(path)
        with self.assertRaises(importer.ImportRejected) as c:
            self.do_import(path, prof)
        self.assertEqual(c.exception.code, "BAD_ARCHIVE")
        self.assertEqual(self.packages(), [])


if __name__ == "__main__":
    unittest.main()
