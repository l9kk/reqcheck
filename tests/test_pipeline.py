import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from reqcheck.cli import main
from reqcheck.ground import Grounder
from reqcheck.lint import lint
from reqcheck.llm import parse_json, unwrap
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


class LLMShapeTest(unittest.TestCase):
    def test_list_wrapped_answer_is_unwrapped(self):
        data = unwrap(parse_json('[{"findings": [{"a": 1}], "set_summary": []}, {"findings": [{"a": 2}]}]'))
        self.assertEqual(data["findings"], [{"a": 1}, {"a": 2}])
        self.assertEqual(unwrap({"x": 1}), {"x": 1})


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


class GenericLintTest(unittest.TestCase):
    TEXT = """# ТЗ: перевод между счетами

Версия: 1.2

ТР-1. Сервис пишет в журнал запрос целиком, включая PIN и CVV.
ТР-2. При ошибке сервис повторяет перевод через некоторое время.
ТР-3. Лимит перевода: уточняется.

| Метод | URL | Назначение |
| :--- | :--- | :--- |
| GET | /v1/transfer?amount= | Перевод между счетами |
| GET | /v1/accounts | Список счетов |

| Роль | ФИО | Дата |
| :--- | :--- | :--- |
| Владелец | | |
| ИБ | | |
"""

    def test_banking_rules_on_unseen_text(self):
        cr = tomllib.load(open(ROOT / "criteria.toml", "rb"))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text(self.TEXT, encoding="utf-8")
            doc = read_document(str(p))
            probs = {f.quotes[0].start: f.problem for f in lint(doc, cr)}
        self.assertIn("CVV", probs[5])
        self.assertIn("PIN", probs[5])
        self.assertIn("некоторое время", probs[6])
        self.assertIn("уточняется", probs[7])
        self.assertIn("GET", probs[11])
        self.assertNotIn(12, probs)
        self.assertTrue(any("только в первой колонке" in x for x in probs.values()))
        self.assertTrue(any(x == "У документа нет даты." for x in probs.values()))


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


class InteractiveTest(unittest.TestCase):
    def test_answers_written_without_model(self):
        from reqcheck.interactive import run as irun
        from reqcheck.llm import LLM
        from reqcheck.pipeline import Pipeline
        old = dict(os.environ)
        os.environ.update({"LLM_PROVIDER": "mock"})
        try:
            rep = Pipeline(LLM(), log=lambda m: None).run(str(DOC))
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertTrue(rep.questions)
        replies = iter(["", "s", "Порог по умолчанию 50 000 тенге", "q"])
        said = []
        with tempfile.TemporaryDirectory() as d:
            path = irun(rep, None, Path(d) / "r.md", read=lambda _: next(replies), say=said.append)
            text = path.read_text(encoding="utf-8")
        self.assertIn(rep.questions[0].id, text)
        self.assertIn("Порог по умолчанию 50 000 тенге", text)
        self.assertNotIn(rep.questions[1].text, text)


if __name__ == "__main__":
    unittest.main()
