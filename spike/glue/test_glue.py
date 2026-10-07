"""NON-NORMATIVE FEASIBILITY SPIKE. Unit tests for the pure helpers of s3_spike_chain.py (no Lean, no network).
The S2a runner output shapes below are taken from the S2b helper source (orchestration/helper/S2aRunner.lean), not from a run.
usage: python3 -B -m unittest test_glue   (from this directory)"""
import json, os, unittest
import s3_spike_chain as G

FREEZE = """CodecArtifactV0:
c156965f810643b115b6bbe720c87e874522bfff298490713be5874677346dd9

CapabilityProofV0:
9482c3f775e78a72dd9b8290c67a59bf00716ac0adb86d5b7b0d8eb4045a4928

ProofArtifactV0:
30f498438473d39566d951b75dd5ce7326d9c368da3cda4868635a3e422a8696

Evidence run:
"""


class T(unittest.TestCase):
    def test_compose(self):
        self.assertEqual(G.compose_s2b({"status": "Verified"}), "continue")
        self.assertEqual(G.compose_s2b({"status": "Invalid", "reason": {"class": "Binding"}}), "REJECT")
        for cls in ("Replay", "Request"):
            self.assertEqual(G.compose_s2b({"status": "Invalid", "reason": {"class": cls}}), "HALT")
        self.assertEqual(G.compose_s2b({"status": "Unavailable", "reason": {"class": "Material"}}), "HALT")
        self.assertIsNone(G.compose_s2b({"status": "TransportError"}))

    def test_norm_s2a(self):
        self.assertEqual(G.norm_s2a({"outcome": "reject", "repr": "P10S2.CoverageOutcome.reject (P10S2.RejectReason.c3_profileAfterFirstAdmission)"}), ("reject", "c3_profileAfterFirstAdmission"))
        self.assertEqual(G.norm_s2a({"outcome": "halt", "repr": "halt (P10S2.HaltReason.tb5_checkpointMaterialUnavailable)"}), ("halt", "tb5_checkpointMaterialUnavailable"))
        self.assertEqual(G.norm_s2a({"outcome": "accept", "repr": "accept ..."}), ("accept", None))
        self.assertEqual(G.norm_expected_s2a(".reject .c3_profileAfterFirstAdmission"), ("reject", "c3_profileAfterFirstAdmission"))
        self.assertEqual(G.norm_expected_s2a(".accept (.obs false none)"), ("accept", None))

    def test_frozen_digests(self):
        d = G.frozen_a12_a14(FREEZE)
        self.assertEqual(d["codec_digest"][:8], "c156965f")
        self.assertEqual(d["capability_proof_digest"][:8], "9482c3f7")
        self.assertEqual(d["proof_digest"][:8], "30f49843")
        with self.assertRaises(ValueError):
            G.frozen_a12_a14("nothing")

    def test_match_s2b(self):
        res = {"status": "Invalid", "reason": {"class": "Binding", "reason": "LeafInputDomainViolation"}}
        self.assertTrue(G.match_s2b({"status": "Invalid", "class": "binding", "reason": "LeafInputDomainViolation"}, res)[0])
        self.assertFalse(G.match_s2b({"status": "Invalid", "class": "replay", "reason": "RootMismatch"}, res)[0])
        self.assertFalse(G.match_s2b({"status": "Verified"}, res)[0])
        miss = {"status": "Unavailable", "reason": {"class": "Material", "reason": "MissingIndex { first_missing: 2 }"}}
        self.assertTrue(G.match_s2b({"status": "Unavailable", "class": "material", "reason": "MissingIndex"}, miss)[0])


if __name__ == "__main__":
    unittest.main()
