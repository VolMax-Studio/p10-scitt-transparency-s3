#!/usr/bin/env python3
"""TEST HARNESS (not acceptance code): the runner's private capture snapshot. Unsafe names and symlinks must survive the copy unchanged (so G5 can reject them), regular
files are copied byte for byte, FIFOs are recreated (never opened), unreproducible special files are refused, and the copy does not follow links. No Lean.
usage: test_snapshot.py"""
import os, socket, sys, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "verifier", "runner"))
import s3c_verify as V


class Snap(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(); self.src = os.path.join(self.t, "cap"); os.makedirs(os.path.join(self.src, "prefix"))
        open(os.path.join(self.src, "capture.json"), "wb").write(b'{"x":1}\n'); open(os.path.join(self.src, "prefix", "000000.cose"), "wb").write(bytes(range(256)))

    def names(self, d):
        out = []
        for root, dirs, files in os.walk(os.fsencode(d)):
            for n in dirs + files: out.append(os.path.relpath(os.path.join(root, n), os.fsencode(d)))
        return sorted(out)

    def test_regular_files_are_byte_identical_and_read_only(self):
        dst = os.path.join(self.t, "snap"); V.snapshot_capture(self.src, dst)
        self.assertEqual(open(os.path.join(dst, "prefix", "000000.cose"), "rb").read(), bytes(range(256)))
        self.assertEqual(self.names(self.src), self.names(dst))
        self.assertEqual(os.stat(os.path.join(dst, "capture.json")).st_mode & 0o777, 0o400)

    def test_unsafe_names_and_symlinks_are_preserved_not_followed(self):
        os.symlink("/etc/hostname", os.path.join(self.src, "prefix", "link.cose"))
        os.symlink("/etc", os.path.join(self.src, "dirlink"))
        for raw in (b"prefix\\000001.cose", b"new\nline.cose", b"\xff.cose"):
            open(os.path.join(os.fsencode(self.src), raw), "wb").write(b"x")
        dst = os.path.join(self.t, "snap"); V.snapshot_capture(self.src, dst)
        self.assertEqual(self.names(self.src), self.names(dst))
        self.assertTrue(os.path.islink(os.path.join(dst, "prefix", "link.cose"))); self.assertEqual(os.readlink(os.path.join(dst, "dirlink")), "/etc")
        self.assertFalse(os.path.exists(os.path.join(dst, "dirlink", "passwd")) and not os.path.islink(os.path.join(dst, "dirlink")))     # /etc was not copied in

    def test_fifo_is_recreated_without_blocking(self):
        os.mkfifo(os.path.join(self.src, "prefix", "pipe.cose"))
        dst = os.path.join(self.t, "snap"); V.snapshot_capture(self.src, dst)
        self.assertTrue(os.path.exists(os.path.join(dst, "prefix", "pipe.cose")) and not os.path.isfile(os.path.join(dst, "prefix", "pipe.cose")))

    def test_socket_is_refused_as_packaging(self):
        s = socket.socket(socket.AF_UNIX); s.bind(os.path.join(self.src, "prefix", "sock.cose"))
        with self.assertRaises(V.SnapshotError) as cm: V.snapshot_capture(self.src, os.path.join(self.t, "snap"))
        self.assertEqual(cm.exception.code, "SNAPSHOT_SPECIAL_FILE"); s.close()

    def test_changes_to_the_original_after_the_copy_do_not_reach_the_snapshot(self):
        dst = os.path.join(self.t, "snap"); V.snapshot_capture(self.src, dst)
        open(os.path.join(self.src, "capture.json"), "wb").write(b"CHANGED")
        self.assertEqual(open(os.path.join(dst, "capture.json"), "rb").read(), b'{"x":1}\n')


class Overlap(unittest.TestCase):
    """r14: a direct call must not recurse into its own destination."""
    def setUp(self):
        self.t = tempfile.mkdtemp(); self.src = os.path.join(self.t, "cap"); os.makedirs(os.path.join(self.src, "prefix"))
        open(os.path.join(self.src, "capture.json"), "wb").write(b"{}\n")

    def refuse(self, dst):
        with self.assertRaises(V.SnapshotError) as cm: V.snapshot_capture(self.src, dst)
        self.assertEqual(cm.exception.code, "SNAPSHOT_DESTINATION_OVERLAPS_SOURCE")
        self.assertEqual(sorted(os.listdir(self.src)), ["capture.json", "prefix"])         # nothing was created inside the source

    def test_destination_equal_inside_alias_or_ancestor_is_refused(self):
        self.refuse(self.src)
        self.refuse(os.path.join(self.src, "snap"))
        self.refuse(os.path.join(self.src, "prefix", "a", "b"))
        os.symlink(self.src, os.path.join(self.t, "alias")); self.refuse(os.path.join(self.t, "alias", "snap")); self.refuse(os.path.join(self.t, "alias"))
        self.refuse(self.t)                                                                  # destination containing the source

    def test_separate_destination_with_a_shared_name_prefix_is_accepted(self):
        V.snapshot_capture(self.src, os.path.join(self.t, "cap-snap"))
        self.assertEqual(open(os.path.join(self.t, "cap-snap", "capture.json"), "rb").read(), b"{}\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
