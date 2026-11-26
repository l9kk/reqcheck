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

    def test_quote_with_inline_list_numbering(self):
        q = self.g.locate("1. Проверить пользовательскую сессию. 2. Проверить принадлежность карты клиенту. "
                          "3. Проверить сумму и переключатель.")
        self.assertEqual((q.start, q.end), (117, 119))

    def test_quote_across_code_fences(self):
        q = self.g.locate('200. Successful — Created {"result":"OK","amount":"50000","enabled":"1"} или '
                          '{"result":"ERROR","message":"Проверьте сумму"}')
        self.assertEqual((q.start, q.end), (165, 171))

    def test_quote_longer_than_six_lines(self):
        q = self.g.locate("200. Ответ в случае успешного выполнения метода. 400. Ответ в случае, если параметры "
                          'запроса заполнены неверно. 200. Successful — Created {"result":"OK","amount":"50000",'
                          '"enabled":"1"} или {"result":"ERROR","message":"Проверьте сумму"} 401. Ответ в случае, '
                          "если запрос выполнен без необходимой авторизации.")
        self.assertEqual((q.start, q.end), (162, 174))

    def test_short_quote_only_as_whole_line(self):
        self.assertEqual(self.g.locate("404").start, 190)
        self.assertIsNone(self.g.locate("405"))
        self.assertIsNone(self.g.locate("200"))

    def test_reordered_list_quote_rejected(self):
        self.assertIsNone(self.g.locate("1. Проверить сумму и переключатель. 2. Проверить пользовательскую сессию. "
                                        "3. Заменить настройку и удалить карту клиента."))


class LLMShapeTest(unittest.TestCase):
    def test_list_wrapped_answer_is_unwrapped(self):
        data = unwrap(parse_json('[{"findings": [{"a": 1}], "set_summary": []}, {"findings": [{"a": 2}]}]'))
        self.assertEqual(data["findings"], [{"a": 1}, {"a": 2}])
        self.assertEqual(unwrap({"x": 1}), {"x": 1})

    def test_daily_quota_detected_from_response_body(self):
        from types import SimpleNamespace
        from openai import RateLimitError
        from reqcheck.llm import LLM, LLMError

        body = ('[{"error": {"code": 429, "message": "Quota exceeded. Generate content requests per day limit '
                'exceeded on Free Tier.\\nPlease retry in 20h21m1.49s.", "details": [{"quotaId": '
                '"GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}]')
        err = RateLimitError.__new__(RateLimitError)
        Exception.__init__(err, "Error code: 429")
        err.response = SimpleNamespace(text=body)
        err.body = None

        class Fake:
            calls = 0

            def create(self, **kw):
                Fake.calls += 1
                raise err

        c = LLM(use_cache=False)
        c.model = "m"
        c._client = type("C", (), {"chat": type("Ch", (), {"completions": Fake()})()})()
        with self.assertRaises(LLMError) as ctx:
            c._call("Critic", "s", "u")
        self.assertEqual(ctx.exception.code, "quota_day")
        self.assertIn("20h21m", ctx.exception.hint)
        self.assertEqual(Fake.calls, 1)

    def test_depleted_credits_fail_fast(self):
        from types import SimpleNamespace
        from openai import APIStatusError
        from reqcheck.llm import LLM, LLMError

        err = APIStatusError.__new__(APIStatusError)
        Exception.__init__(err, "Error code: 402")
        err.status_code = 402
        err.response = SimpleNamespace(text='[{"error": {"code": 402, "message": "prepayment credits are depleted"}}]')
        err.body = None
        calls = []

        class Fake:
            def create(self, **kw):
                calls.append(1)
                raise err

        c = LLM(use_cache=False)
        c.model = "m"
        c._client = type("C", (), {"chat": type("Ch", (), {"completions": Fake()})()})()
        with self.assertRaises(LLMError) as ctx:
            c._call("Critic", "s", "u")
        self.assertEqual(ctx.exception.code, "billing")
        self.assertEqual(len(calls), 1)


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

    def test_security_rules_use_correct_criterion(self):
        cr = tomllib.load(open(ROOT / "criteria.toml", "rb"))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text(self.TEXT, encoding="utf-8")
            fs = {f.quotes[0].start: f for f in lint(read_document(str(p)), cr)}
        for line in (5, 11):
            self.assertEqual(fs[line].criterion, "correct")
            self.assertEqual(fs[line].severity, "критично")

    def test_placeholder_or_empty_test_section_is_critical(self):
        cr = tomllib.load(open(ROOT / "criteria.toml", "rb"))
        text = ("# ТЗ: тестовый перевод\nВерсия 1.0 от 26.11.2026\n## Цели\nЛимит: уточняется.\n\n## Тестирование\n\n"
                "заполняются тестировщиками\n\n## Приёмка\n\n## Ограничения\nСумма до 100 ₸.\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.md"
            p.write_text(text, encoding="utf-8")
            fs = {f.quotes[0].start: f for f in lint(read_document(str(p)), cr)}
        self.assertEqual(fs[4].severity, "важно")
        self.assertEqual(fs[8].severity, "критично")
        self.assertEqual(fs[10].severity, "критично")
        self.assertIn("пустой", fs[10].problem)
        self.assertNotIn(1, fs)
        self.assertNotIn(6, fs)

    def test_placeholder_in_task_testing_section_is_critical(self):
        cr = tomllib.load(open(ROOT / "criteria.toml", "rb"))
        fs = [f for f in lint(read_document(str(DOC)), cr) if f.quotes[0].start == 57]
        self.assertEqual([f.severity for f in fs], ["критично"])


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
        if not any(f["severity"] == "критично" for f in data["findings"]):
            self.assertEqual(data["verdict"]["status"], "Не проверено")

    def test_broken_input_verdict_is_not_checked(self):
        with tempfile.TemporaryDirectory() as d:
            _, data, md = run(FIX / "broken" / "scan.pdf", d)
        self.assertEqual(data["verdict"]["status"], "Не проверено")
        self.assertIn("**ошибка**", md)

    def test_summary_has_triage_table_and_no_internal_ids(self):
        with tempfile.TemporaryDirectory() as d:
            _, data, md = run(DOC, d)
        summary = md.split("## 3.")[0]
        for f in data["findings"]:
            self.assertIn(f"| {f['id']} |", summary)
        self.assertNotRegex(md, r"\bF-\d\d\b")


class RankTest(unittest.TestCase):
    def test_questions_on_critical_findings_come_first(self):
        from reqcheck.model import Finding, Question
        from reqcheck.pipeline import Pipeline
        fs = [Finding("D-01", "req", [], "complete", "критично", [], "a"),
              Finding("D-02", "req", [], "complete", "мелочь", [], "b")]
        qs = [Question("Q-01", "minor?", [], "", [], "", "", ["D-02"]),
              Question("Q-02", "none?", [], "", [], "", "", []),
              Question("Q-03", "crit?", [], "", [], "", "", ["D-01"])]
        ranked = Pipeline.rank_questions(qs, fs)
        self.assertEqual([q.text for q in ranked], ["crit?", "minor?", "none?"])
        self.assertEqual([q.id for q in ranked], ["Q-01", "Q-02", "Q-03"])


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
