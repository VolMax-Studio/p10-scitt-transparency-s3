import json
import unittest

from . import fakes
from workbench import records as R


class RecordTests(unittest.TestCase):
    def test_strict_parse_rejects(self):
        for bad in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xef\xbb\xbf{}', b'\xff\xfe', b'{', b'', b'x' * 10):
            with self.assertRaises(R.RecordError, msg=bad):
                R.parse_strict(bad)
        with self.assertRaises(R.RecordError):
            R.parse_strict(b" " * 20, limit=10)
        self.assertEqual(R.parse_strict(b'{"a":[1,2.5,null,true]}'), {"a": [1, 2.5, None, True]})

    def test_verdict_structure(self):
        self.assertEqual(R.validate_verdict(fakes.good_verdict()), [])
        for k, v in (("outcome", "ACCEPT"), ("outcome", None), ("stage", 3), ("reason", "BindingMatch"), ("reason", {"code": 7}),
                     ("executables_pinned", {"entry": 1, "g5": True}), ("executables_pinned", [True]), ("post", [])):
            self.assertTrue(R.validate_verdict(fakes.good_verdict(**{k: v})), (k, v))
        self.assertTrue(R.validate_verdict([]))

    def test_run_info_structure(self):
        self.assertEqual(R.validate_run_info(fakes.good_info()), [])
        for k, v in (("network_isolated", 1), ("network_isolated", "true"), ("problems", None), ("tcb_source_mismatch", {}),
                     ("runner_source_sha256", {"a": 1}), ("entry_binary_sha256", None)):
            self.assertTrue(R.validate_run_info(fakes.good_info(**{k: v})), (k, v))

    def test_no_p10_rule_tables(self):
        with open(R.__file__) as f:
            src = f.read()
        for token in ("A1", "NETWORK_ISOLATION", "BindingMatch"):
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
