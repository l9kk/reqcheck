import os
import tempfile
import unittest
from pathlib import Path

from reqcheck.interactive import load_answers, pick, run as irun
from reqcheck.llm import LLM
from reqcheck.loop import recheck, render_delta
from reqcheck.model import Finding, Question, Report
from reqcheck.pipeline import Pipeline
from reqcheck.reader import read_document

DOC = Path(__file__).resolve().parent.parent / "input" / "requirements.md"


def build(mock):
    old = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "mock"
    try:
        pipe = Pipeline(LLM(mock=mock), log=lambda m: None)
    finally:
        os.environ.pop("LLM_PROVIDER") if old is None else os.environ.update(LLM_PROVIDER=old)
    from reqcheck.ground import Grounder
    from reqcheck.model import Requirement
    pipe.doc = read_document(str(DOC))
    pipe.g = Grounder(pipe.doc)
    reqs = [Requirement(f"R-0{i}", f"Ф-{i}", "functional", "s", "sec", pipe.g.quote_lines(36 + i, 36 + i)) for i in (1, 2, 3)]
    f1 = Finding("D-01", "req", ["R-02"], "verifiable", "критично", [reqs[1].quote], "Месяц не определён.")
    f2 = Finding("D-02", "req", ["R-02"], "unambiguous", "важно", [reqs[1].quote], "Что значит проведённые покупки.")
    f3 = Finding("D-03", "req", ["R-03"], "complete", "важно", [reqs[2].quote], "Нет сообщения push.")
    q = Question("Q-01", "Какой часовой пояс?", [reqs[1].quote], "", ["Алматы", "UTC"], "Алматы", "аналитик", ["D-01", "D-02"])
    rep = Report(passport={"document": "requirements.md"}, requirements=reqs, findings=[f1, f2, f3], questions=[q])
    return pipe, rep, q


def canned(role, system, user):
    if role == "Auditor":
        return {"results": [
            {"req_id": "R-02", "fail": ["unambiguous"], "findings": [
                {"criterion": "unambiguous", "severity": "важно", "quote": "Возврат уменьшает расходы месяца",
                 "problem": "Не сказано, что делать с частичным возвратом."},
                {"criterion": "verifiable", "severity": "важно", "quote": "цитаты нет нигде в тексте документа",
                 "problem": "Выдуманное замечание без цитаты."}]},
            {"req_id": "R-03", "fail": [], "findings": []},
            {"req_id": "R-01", "fail": [], "findings": []}]}
    if role == "CrossChecker":
        return {"steps": []}
    if role == "Delta":
        return {"old": [{"id": "D-01", "status": "closed", "reason": "часовой пояс назван"},
                        {"id": "D-02", "status": "remains", "reason": "термин не определён"}],
                "new": [{"id": "N-01", "same_as": "", "reason": "новый дефект"}]}
    return {}


ITEMS = [{"q": None, "answer": "Алматы", "requirement": "Месяц определяется по дате покупки в Алматы (UTC+5).",
          "acceptance": ["Дано покупка 31.01 23:30 Когда ... Тогда расход января"]}]


class AnswersFileTest(unittest.TestCase):
    def test_pick_letter_number_text_default(self):
        _, _, q = build(canned)
        self.assertEqual(pick(q, "b"), "UTC")
        self.assertEqual(pick(q, "1"), "Алматы")
        self.assertEqual(pick(q, ""), "Алматы")
        self.assertEqual(pick(q, "default"), "Алматы")
        self.assertEqual(pick(q, "c"), "c")
        self.assertEqual(pick(q, "Свой текст"), "Свой текст")

    def test_load_file(self):
        _, rep, _ = build(canned)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.toml"
            p.write_text('Q-01 = "b"\n', encoding="utf-8")
            out = load_answers(p, rep)
            self.assertEqual(out[0]["answer"], "UTC")
            p.write_text('Q-09 = "a"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_answers(p, rep)
            p.write_text("Q-01 = \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_answers(p, rep)


class DeltaTest(unittest.TestCase):
    def items(self, q):
        return [dict(ITEMS[0], q=q)]

    def test_closed_remains_new_with_quote_guard(self):
        pipe, rep, q = build(canned)
        d = recheck(pipe, rep, self.items(q), say=lambda m: None)
        self.assertEqual([f.id for f, _ in d["closed"]], ["D-01"])
        self.assertEqual([f.id for f, _ in d["remains"]], ["D-02"])
        self.assertEqual([f.id for f, _ in d["new"]], ["N-01"])
        self.assertEqual(d["guard_drops"], 1)
        text = render_delta(d)
        self.assertIn("закрыто 1, осталось 1, новых 1", text)
        self.assertIn("D-01", text)
        self.assertIn("N-01", text)

    def test_unjudged_closes_nothing(self):
        def mock(role, system, user):
            return {} if role == "Delta" else canned(role, system, user)
        pipe, rep, q = build(mock)
        d = recheck(pipe, rep, self.items(q), say=lambda m: None)
        self.assertFalse(d["closed"])
        self.assertEqual(len(d["remains"]), 2)
        self.assertIn("закрытыми ничего не считаем", render_delta(d))

    def test_auditor_silence_aborts(self):
        pipe, rep, q = build(lambda role, s, u: {})
        self.assertIsNone(recheck(pipe, rep, self.items(q), say=lambda m: None))

    def test_run_writes_delta_from_file_answers(self):
        pipe, rep, q = build(lambda role, s, u: {"items": [{"q_id": "Q-01", "requirement": ITEMS[0]["requirement"],
                                                            "acceptance": ITEMS[0]["acceptance"]}]}
                             if role == "Rewriter" else canned(role, s, u))
        with tempfile.TemporaryDirectory() as d:
            path = irun(rep, pipe.llm, Path(d) / "r.md", answers=[{"q": q, "answer": "Алматы"}], pipe=pipe, say=lambda m: None)
            text = path.read_text(encoding="utf-8")
        self.assertIn("## Дельта после ответов", text)
        self.assertIn("Месяц определяется по дате покупки в Алматы (UTC+5)", text)


if __name__ == "__main__":
    unittest.main()
