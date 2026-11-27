import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from themis.interactive import pick
from themis.pipeline import Pipeline
from themis.reader import decode_text
from tests.fake_llm import FakeLLM

ROOT = Path(__file__).resolve().parent.parent


class GuardTest(unittest.TestCase):
    def test_cyrillic_option_letter_picks_option(self):
        q = SimpleNamespace(options=["первый", "второй", "третий"], default="второй")
        self.assertEqual(pick(q, "б"), "второй")
        self.assertEqual(pick(q, "В"), "третий")
        self.assertEqual(pick(q, "b"), "второй")

    def test_one_bad_byte_keeps_utf8(self):
        text = "Требование: система отправляет уведомление.\n" * 50
        out, enc = decode_text(text.encode("utf-8") + b"\xff")
        self.assertTrue(out.startswith("Требование"))
        self.assertIn("utf-8", enc)

    def test_cp1251_file_still_decodes(self):
        out, enc = decode_text("Система должна отправлять уведомление.".encode("cp1251"))
        self.assertEqual(enc, "cp1251")
        self.assertTrue(out.startswith("Система"))

    def test_too_long_document_skips_model(self):
        os.environ["THEMIS_MAX_CHARS"] = "1000"
        try:
            llm = FakeLLM()
            rep = Pipeline(llm, log=lambda m: None).run(str(ROOT / "input" / "requirements.md"))
        finally:
            del os.environ["THEMIS_MAX_CHARS"]
        self.assertIn("too_long", [d.code for d in rep.diagnostics])
        self.assertEqual(llm.trace, [])
        self.assertIn("Модель не использовалась", rep.verdict["text"])
        self.assertIn("слишком большой", rep.verdict["text"])
        self.assertNotIn("ключ", rep.verdict["text"])

    def test_second_run_starts_clean(self):
        pipe = Pipeline(FakeLLM(), log=lambda m: None)
        pipe.drops.append({"role": "x", "reason": "old", "item": ""})
        pipe.merged["F-01"] = ["old"]
        pipe.run(str(ROOT / "input" / "requirements.md"))
        self.assertNotIn("old", [d["reason"] for d in pipe.drops])
        self.assertNotEqual(pipe.merged.get("F-01"), ["old"])


if __name__ == "__main__":
    unittest.main()
