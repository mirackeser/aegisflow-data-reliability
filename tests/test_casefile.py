# SPDX-License-Identifier: Apache-2.0
import unittest

from aegisflow_dr import casefile as cf
from aegisflow_dr.pipeline import InputRejected

A, B = "a" * 64, "b" * 64


def items(n=len(cf.LINKS)):
    return [(kind, A if i % 2 else B, "2026-11-28T00:00:%02dZ" % i, {"n": i}) for i, kind in enumerate(cf.LINKS)][:n]


def decide(**overrides):
    values = dict(incident_id="INC-0001", evidence_sha256=A, run_id="run-1", decision="accepted", candidate="unit_change",
                  supported=["unit_change"], reviewer="  Ada   Lovelace ", note="Scale ratio 9.99.", decided_at="t")
    values.update(overrides)
    return cf.decision_record(**values)


class ChainTests(unittest.TestCase):
    def test_built_chain_is_intact_and_linked(self):
        chain = cf.build_chain(items())
        self.assertEqual([c["kind"] for c in chain], list(cf.LINKS))
        self.assertIsNone(chain[0]["prev"])
        self.assertTrue(all(chain[i]["prev"] == chain[i - 1]["link_sha256"] for i in range(1, len(chain))))
        self.assertTrue(cf.chain_intact(chain))
        self.assertTrue(cf.chain_intact(cf.build_chain(items(2))))  # a prefix is a valid chain
        self.assertTrue(cf.chain_intact([]))

    def test_any_change_breaks_the_chain(self):
        chain = cf.build_chain(items())
        edited = [dict(c) for c in chain]
        edited[1]["summary"] = {"n": 99}
        self.assertFalse(cf.chain_intact(edited))
        swapped = [dict(c) for c in chain]
        swapped[2]["digest"] = A if swapped[2]["digest"] == B else B
        self.assertFalse(cf.chain_intact(swapped))
        self.assertFalse(cf.chain_intact([chain[0], chain[2]]))  # a removed link
        self.assertFalse(cf.chain_intact(chain + [chain[-1]]))  # longer than the fixed order
        relinked = cf.build_chain(items())
        relinked[0] = cf.link("baseline", A, "x", {}, None)  # a new first link: the second no longer points at it
        self.assertFalse(cf.chain_intact(relinked))

    def test_invalid_links_and_order_are_refused(self):
        for bad in (lambda: cf.link("other", A, "t", {}, None), lambda: cf.link("baseline", "z" * 64, "t", {}, None),
                    lambda: cf.link("baseline", A, "t", {}, "short"), lambda: cf.build_chain(items()[1:]),
                    lambda: cf.link("baseline", A, "t", {"x": float("nan")}, None)):
            with self.assertRaises((InputRejected, ValueError)):
                bad()
        self.assertFalse(cf.is_digest(None))


class DecisionTests(unittest.TestCase):
    def test_accepted_decision_is_normalised_and_digested(self):
        record = decide()
        self.assertEqual((record["reviewer"], record["executed"], record["candidate"]), ("Ada Lovelace", False, "unit_change"))
        self.assertTrue(cf.decision_intact(record))
        self.assertFalse(cf.decision_intact({**record, "note": "changed"}))
        self.assertFalse(cf.decision_intact({**record, "executed": True}))

    def test_other_decisions_take_no_candidate(self):
        self.assertIsNone(decide(decision="rejected", candidate=None, supported=[])["candidate"])
        self.assertEqual(decide(decision="more_evidence", candidate=None, note="")["note"], "")
        with self.assertRaises(InputRejected):
            decide(decision="rejected", candidate="unit_change")

    def test_a_person_cannot_accept_what_the_probes_do_not_support(self):
        with self.assertRaisesRegex(InputRejected, "support"):
            decide(candidate="noise_increase")
        with self.assertRaises(InputRejected):
            decide(supported=[])

    def test_invalid_inputs(self):
        for overrides in ({"decision": "approve"}, {"evidence_sha256": "x"}, {"run_id": ""}, {"run_id": None},
                          {"reviewer": "   "}, {"reviewer": "x" * 61}, {"reviewer": 5}, {"note": "n" * 501},
                          {"note": "bell\x07"}):
            with self.subTest(overrides=overrides), self.assertRaises(InputRejected):
                decide(**overrides)


if __name__ == "__main__":
    unittest.main()
