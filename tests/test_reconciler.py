import copy
import unittest
from dataclasses import asdict
from pathlib import Path

from reqcheck.ground import Grounder
from reqcheck.llm import LLMError
from reqcheck.model import Finding, Question, Report
from reqcheck.pipeline import ROLE_ORDER, Pipeline
from reqcheck.reader import read_document
from reqcheck.report_md import render
from tests.fake_llm import FakeLLM

DOC = Path(__file__).resolve().parent.parent / "input" / "requirements.md"


class Answer(FakeLLM):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer
        self.users: list[str] = []

    def reconciler(self, user):
        self.users.append(user)
        if isinstance(self.answer, Exception):
            raise self.answer
        return copy.deepcopy(self.answer)


def setup(answer):
    pipe = Pipeline(Answer(answer), log=lambda m: None)
    pipe.doc = read_document(str(DOC))
    pipe.g = Grounder(pipe.doc)
    quote = pipe.g.quote_lines(38, 38)
    f1 = Finding("D-01", "req", ["R-02"], "unambiguous", "критично", [quote], "Не задано, по какой дате считать месяц.",
                 fix="Считать месяц по дате проведения операции.")
    f2 = Finding("D-02", "req", ["R-02"], "verifiable", "важно", [quote], "Нет числа.", fix="Указать число и единицу.")
    f3 = Finding("D-03", "req", ["R-03"], "complete", "мелочь", [quote], "Нет примера.", fix="Добавить пример ответа.")
    q1 = Question("Q-01", "По какой дате операция относится к месяцу?", [quote], "", ["По дате совершения", "По дате проведения"],
                  "Вариант (а).", "аналитик", ["D-01", "D-02"])
    q2 = Question("Q-02", "Какой метод сохраняет порог?", [quote], "", ["PUT", "POST"], "Вариант (а).", "архитектор", ["D-02"])
    rep = Report(passport={"document": DOC.name}, findings=[f1, f2, f3], questions=[q1, q2])
    return pipe, rep


def run(answer):
    pipe, rep = setup(answer)
    before = copy.deepcopy(rep)
    pipe.reconcile(rep.findings, rep.questions, rep)
    return pipe, rep, before


class ReconcilerTest(unittest.TestCase):
    NEW = "Считать месяц по дате совершения операции по времени UTC+5."

    def test_rewrites_fix_of_linked_finding_only(self):
        pipe, rep, before = run({"fixes": [{"id": "D-01", "q_id": "Q-01", "fix": self.NEW}], "conflicts": []})
        self.assertEqual(rep.findings[0].fix, self.NEW)
        self.assertEqual([asdict(f) for f in rep.findings[1:]], [asdict(f) for f in before.findings[1:]])
        self.assertIn("D-01 [закрывает Q-01]", pipe.llm.users[0])
        self.assertIn("D-02 [закрывает Q-01, Q-02]", pipe.llm.users[0])
        self.assertNotIn("D-03 [", pipe.llm.users[0])
        self.assertEqual(rep.diagnostics, [])

    def test_other_fields_never_change(self):
        bad = {"id": "D-01", "fix": self.NEW, "severity": "мелочь", "criterion": "x", "problem": "другое",
               "quotes": ["чужая цитата"], "req_ids": ["R-99"], "new_id": "D-77"}
        _, rep, before = run({"fixes": [bad], "conflicts": []})
        got, old = asdict(rep.findings[0]), asdict(before.findings[0])
        self.assertEqual(got.pop("fix"), self.NEW)
        old.pop("fix")
        self.assertEqual(got, old)
        self.assertEqual([asdict(q) for q in rep.questions], [asdict(q) for q in before.questions])

    def test_unlinked_and_short_fixes_are_ignored(self):
        pipe, rep, before = run({"fixes": [{"id": "D-03", "fix": "Совсем другой и достаточно длинный текст исправления."},
                                           {"id": "D-01", "fix": "  "}, {"id": "D-02", "fix": "Да."},
                                           {"id": "D-09", "fix": "Несуществующее замечание с длинным текстом."},
                                           {"id": ["D-01"], "fix": self.NEW}, {"id": "D-01", "fix": 5}]})
        self.assertEqual([asdict(f) for f in rep.findings], [asdict(f) for f in before.findings])
        reasons = [d["reason"] for d in pipe.drops if d["role"] == "Reconciler"]
        self.assertEqual(reasons.count("пустое или слишком короткое исправление"), 2)
        self.assertEqual(reasons.count("замечание не закрыто вопросом"), 2)
        self.assertEqual(reasons.count("неверный формат элемента"), 2)

    def test_new_value_gets_assumption_tag(self):
        _, rep, _ = run({"fixes": [{"id": "D-01", "fix": "Считать месяц по дате совершения, срок хранения 777 дней."}]})
        self.assertTrue(rep.findings[0].fix.endswith("[предложение, согласовать]"))

    def test_failure_keeps_originals(self):
        for answer in (LLMError("network", "LLM недоступна (network).", ""), RuntimeError("boom"),
                       {"fixes": "не список"}, {"fixes": ["мусор"]}, {"другое": []}, ["список"]):
            with self.subTest(answer=answer):
                _, rep, before = run(answer)
                self.assertEqual([asdict(f) for f in rep.findings], [asdict(f) for f in before.findings])
                self.assertEqual([asdict(q) for q in rep.questions], [asdict(q) for q in before.questions])
                self.assertIn("reconcile", [d.code for d in rep.diagnostics])

    def test_conflict_note_goes_on_later_question(self):
        _, rep, _ = run({"fixes": [], "conflicts": [{"a": "Q-02", "b": "Q-01", "reason": "Разные правила для одного поля."},
                                                    {"a": "Q-01", "b": "Q-01", "reason": "сам с собой"},
                                                    {"a": "Q-01", "b": "Q-09", "reason": "нет такого"},
                                                    {"a": "Q-01", "b": "Q-02", "reason": ""}]})
        self.assertEqual(rep.questions[0].note, "")
        self.assertEqual(rep.questions[1].note, "рекомендация расходится с Q-01: Разные правила для одного поля.")
        self.assertIn("- Внимание: рекомендация расходится с Q-01", render(rep, {}))

    def test_no_call_without_linked_findings(self):
        pipe, rep = setup({"fixes": []})
        for q in rep.questions:
            q.finding_ids = []
        pipe.reconcile(rep.findings, rep.questions, rep)
        self.assertEqual(pipe.llm.trace, [])

    def test_runs_last_in_full_pipeline(self):
        llm = FakeLLM()
        rep = Pipeline(llm, log=lambda m: None).run(str(DOC))
        roles = [t["role"] for t in llm.trace]
        self.assertEqual(roles[-1], "Reconciler")
        self.assertEqual(roles.count("Reconciler"), 1)
        self.assertEqual(ROLE_ORDER[-1], "Reconciler")
        self.assertEqual([t["role"] for t in rep.trace][-1], "Reconciler")


if __name__ == "__main__":
    unittest.main()
