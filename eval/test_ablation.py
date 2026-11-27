import json
import tempfile
import unittest

from eval import ablation as ab


class AblationTest(unittest.TestCase):
    def test_cache_miss_raises_without_a_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            llm = ab.ReplayLLM(cache_dir=tmp)
            with self.assertRaises(ab.CacheMiss):
                llm.json("Auditor", "system", "user")
            self.assertEqual(llm.trace, [])

    def test_replay_autotopup(self):
        name, doc, committed, golden = ab.DOCS[1]
        r = ab.run_doc(name, doc, committed, golden)
        self.assertEqual(r["calls"], 0)
        self.assertGreater(r["cached"], 0)
        self.assertTrue(r["pre_critic_ok"])
        self.assertTrue(r["full_ok"])
        totals = [r["rows"][k]["findings_total"] for k, _, _ in ab.VARIANTS]
        self.assertEqual(totals, sorted(totals))
        saved = json.loads((ab.ROOT / committed).read_text(encoding="utf-8"))
        self.assertEqual(r["rows"]["full"]["findings_total"], len(saved["findings"]))

    def test_step_diff(self):
        before = {"defects": [{"id": "G1", "found_by": ["F-01"]}, {"id": "G2", "found_by": []}]}
        after = {"defects": [{"id": "G1", "found_by": []}, {"id": "G2", "found_by": ["F-02"]}]}
        self.assertEqual(ab.step_diff(before, after), "+G2 -G1")
        self.assertEqual(ab.step_diff(before, before), "-")


if __name__ == "__main__":
    unittest.main()
