import json
import unittest
from dataclasses import asdict
from pathlib import Path

from themis.llm import ReplayLLM
from themis.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
DOCS = [("input/requirements.md", "report/report.json"),
        ("examples/docs/autotopup.md", "examples/autotopup/report.json"),
        ("examples/docs/cashback.md", "examples/cashback/report.json")]


def key(f: dict) -> tuple:
    return (f["id"], f["severity"], f["criterion"], f["problem"], tuple(q["text"] for q in f["quotes"]))


class CommittedCacheReplayTest(unittest.TestCase):
    """The committed .cache/llm must rebuild the committed reports with zero model calls, on every OS."""

    def test_reports_replay_from_committed_cache(self):
        for doc, ref in DOCS:
            with self.subTest(doc=doc):
                llm = ReplayLLM(cache_dir=str(ROOT / ".cache" / "llm"))
                rep = asdict(Pipeline(llm, log=lambda m: None).run(str(ROOT / doc)))
                want = json.loads((ROOT / ref).read_text(encoding="utf-8"))
                self.assertFalse([d for d in rep["diagnostics"] if d["code"] == "cache_miss"])
                self.assertTrue(all(t["cached"] for t in llm.trace))
                self.assertEqual([key(f) for f in rep["findings"]], [key(f) for f in want["findings"]])
                self.assertEqual([(q["id"], q["text"]) for q in rep["questions"]],
                                 [(q["id"], q["text"]) for q in want["questions"]])
                self.assertEqual(rep["verdict"]["status"], want["verdict"]["status"])


if __name__ == "__main__":
    unittest.main()
