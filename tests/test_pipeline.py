import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from reqcheck.cli import main
from reqcheck.ground import Grounder
from reqcheck.lint import lint
from reqcheck.reader import read_document

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "input" / "requirements.md"
FIX = ROOT / "tests" / "fixtures"


def run(path, out_dir, env=None):
    old = dict(os.environ)
    os.environ.update({"LLM_PROVIDER": "mock", "REQCHECK_PDF": "0", **(env or {})})
    try:
        code = main([str(path), "-o", str(Path(out_dir) / "r.md"), "--quiet"])
    finally:
        os.environ.clear()
        os.environ.update(old)
    data = json.loads((Path(out_dir) / "r.json").read_text(encoding="utf-8"))
    md = (Path(out_dir) / "r.md").read_text(encoding="utf-8")
    return code, data, md


class GroundTest(unittest.TestCase):
    def setUp(self):
        self.doc = read_document(str(DOC))
        self.g = Grounder(self.doc)

    def test_exact_quote(self):
        q = self.g.locate("На карту приходится максимум один такой push за календарный месяц")
        self.assertIsNotNone(q)
        self.assertIn("Ф-3", self.doc.lines[q.start - 1].text)

    def test_quote_with_typography_changes(self):
        q = self.g.locate('поле "Порог, ₸", сумма за месяц и кнопка "Сохранить"')
        self.assertIsNotNone(q)

    def test_fuzzy_quote(self):
        q = self.g.locate("Месяц определяется по дате совершения покупки в городе Алматы")
        self.assertIsNotNone(q)
        self.assertIn("Ф-2", self.doc.lines[q.start - 1].text)

    def test_invented_quote_rejected(self):
        self.assertIsNone(self.g.locate("Система должна поддерживать биометрическую аутентификацию по лицу"))


class LintTest(unittest.TestCase):
    def test_finds_rule_defects_with_grounded_quotes(self):
        doc = read_document(str(DOC))
        cr = tomllib.load(open(ROOT / "criteria.toml", "rb"))
        fs = lint(doc, cr)
        problems = " ".join(f.problem for f in fs)
        self.assertIn("GET", problems)
        self.assertIn("201", problems)
        self.assertIn("тиыны", problems)
        for f in fs:
            for q in f.quotes:
                self.assertTrue(1 <= q.start <= q.end <= len(doc.lines))


class PipelineMockTest(unittest.TestCase):
    def test_full_report_sections(self):
        with tempfile.TemporaryDirectory() as d:
            code, data, md = run(DOC, d)
        self.assertIn(code, (0, 1))
        for h in ("## 1. Паспорт прогона", "## 2. Сводка", "## 3. Уточняющие вопросы", "## 4. Как агент нарезал",
                  "## 5. Проверка каждого требования", "## 6. Проверка набора", "## 8. Итог", "## 9. Как работал агент"):
            self.assertIn(h, md)
        self.assertGreater(len(data["requirements"]), 10)

    def test_every_quote_is_in_source(self):
        doc = read_document(str(DOC))
        with tempfile.TemporaryDirectory() as d:
            _, data, _ = run(DOC, d)
        for f in data["findings"]:
            for q in f["quotes"]:
                src = " ".join(doc.lines[i - 1].text for i in range(q["start"], q["end"] + 1))
                self.assertTrue(q["text"].replace("**", "")[:30].strip() in src.replace("**", ""), q)

    def test_broken_inputs_never_crash(self):
        for f in sorted((FIX / "broken").iterdir()):
            with self.subTest(file=f.name), tempfile.TemporaryDirectory() as d:
                code, data, md = run(f, d)
                self.assertEqual(code, 2)
                self.assertIn("Диагностика", md)
                self.assertTrue(data["diagnostics"])

    def test_no_key_degrades_gracefully(self):
        with tempfile.TemporaryDirectory() as d:
            code, data, md = run(DOC, d, {"LLM_PROVIDER": "openai_compat", "LLM_API_KEY": "", "GEMINI_API_KEY": ""})
        self.assertIn(code, (0, 1))
        self.assertTrue(any(x["code"] == "no_key" for x in data["diagnostics"]))
        self.assertTrue(data["findings"])


if __name__ == "__main__":
    unittest.main()
