import tempfile
import unittest
from pathlib import Path

from reqcheck.interactive import load_answers, pick, run as irun
from reqcheck.loop import recheck, render_delta
from reqcheck.model import Finding, Question, Report
from reqcheck.pipeline import Pipeline
from reqcheck.ground import Grounder
from reqcheck.model import Requirement
from reqcheck.reader import read_document
from tests.fake_llm import FakeLLM

DOC = Path(__file__).resolve().parent.parent / "input" / "requirements.md"


class Canned(FakeLLM):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def json(self, role, system, user):
        self.trace.append({"role": role, "cached": False, "seconds": 0.0, "in_tokens": 0, "out_tokens": 0})
        return self.fn(role, system, user)


def build(mock):
    pipe = Pipeline(Canned(mock), log=lambda m: None)
    pipe.doc = read_document(str(DOC))
    pipe.g = Grounder(pipe.doc)
    reqs = [Requirement(f"R-0{i}", f"Ф-{i}", "functional", "s", "sec", pipe.g.quote_lines(36 + i, 36 + i)) for i in (1, 2, 3)]
    f1 = Finding("D-01", "req", ["R-02"], "verifiable", "критично", [reqs[1].quote], "Месяц не определён.")
    f2 = Finding("D-02", "req", ["R-02"], "unambiguous", "важно", [reqs[1].quote], "Что значит проведённые покупки.")
    f3 = Finding("D-03", "req", ["R-03"], "complete", "важно", [reqs[2].quote], "Нет сообщения push.")
    f4 = Finding("D-04", "req", ["R-02"], "complete", "мелочь", [reqs[1].quote], "Нет примера.")
    q = Question("Q-01", "Какой часовой пояс?", [reqs[1].quote], "", ["Алматы", "UTC"], "Алматы", "аналитик", ["D-01", "D-02"])
    rep = Report(passport={"document": "requirements.md"}, requirements=reqs, findings=[f1, f2, f3, f4], questions=[q])
    return pipe, rep, q


def canned(role, system, user):
    if role == "Auditor":
        return {"results": [
            {"req_id": "R-02", "fail": ["unambiguous"], "findings": [
                {"criterion": "unambiguous", "severity": "важно", "quote": "Возврат уменьшает расходы месяца",
                 "problem": "Не сказано, что делать с частичным возвратом."},
                {"criterion": "verifiable", "severity": "важно", "quote": "цитаты нет нигде в тексте документа",
                 "problem": "Выдуманное замечание без цитаты."},
                {"criterion": "necessary", "severity": "мелочь", "quote": "Месяц определяется по дате покупки",
                 "problem": "Правило дублирует другое переписанное требование."}]},
            {"req_id": "R-03", "fail": ["complete"], "findings": [
                {"criterion": "complete", "severity": "важно", "quote": "Когда расходы переходят от суммы ниже порога",
                 "problem": "Нет сообщения push для соседнего требования."}]},
            {"req_id": "R-01", "fail": [], "findings": []}]}
    if role == "CrossChecker":
        return {"steps": []}
    if role == "Delta":
        return {"old": [{"id": "D-01", "status": "closed", "reason": "часовой пояс назван"},
                        {"id": "D-02", "status": "remains", "reason": "термин не определён"},
                        {"id": "D-03", "status": "closed", "reason": "соседний"}],
                "new": [{"id": "N-01", "same_as": "", "reason": "новый дефект"},
                        {"id": "N-03", "same_as": "D-03", "reason": "то же"}]}
    return {}


TEXT = "Месяц определяется по дате покупки в Алматы (UTC+5)."
ACC = ["Дано покупка 31.01 23:30 Когда ... Тогда расход января"]
ITEMS = [{"q": None, "answer": "Алматы", "requirement": TEXT, "acceptance": ACC,
          "rewrites": [{"req_id": "R-02", "requirement": TEXT, "acceptance": ACC}]}]


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
        self.assertEqual(d["untouched"], 1)
        self.assertEqual(d["noise"], 1)
        self.assertEqual(d["repeat_nb"], 1)
        self.assertIn("повторно найдено 1 старых", render_delta(d))
        text = render_delta(d)
        self.assertIn("закрыто 1 из 2 связанных замечаний, осталось 1; новых последствий ответов: 1", text)
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

    def test_rewriter_covers_all_linked_requirements(self):
        from reqcheck.interactive import rewrite
        seen = {}

        def mock(role, system, user):
            seen["user"] = user
            return {"items": [{"q_id": "Q-01", "rewrites": [
                {"req_id": "R-02", "requirement": "Новый текст.", "acceptance": []},
                {"req_id": "R-03", "requirement": "Второй текст.", "acceptance": ["Дано ... Тогда ..."]},
                {"req_id": "R-99", "requirement": "Чужой.", "acceptance": []}]}]}
        pipe, rep, q = build(mock)
        q.finding_ids = ["D-01", "D-03"]
        out = rewrite([{"q": q, "answer": "Алматы"}], rep, pipe.llm, say=lambda m: None)
        self.assertEqual([w["req_id"] for w in out[0]["rewrites"]], ["R-02", "R-03"])
        self.assertIn("R-03:", seen["user"])

    def test_run_writes_delta_from_file_answers(self):
        pipe, rep, q = build(lambda role, s, u: {"items": [{"q_id": "Q-01", "rewrites": ITEMS[0]["rewrites"]}]}
                             if role == "Rewriter" else canned(role, s, u))
        with tempfile.TemporaryDirectory() as d:
            path = irun(rep, pipe.llm, Path(d) / "r.md", answers=[{"q": q, "answer": "Алматы"}], pipe=pipe, say=lambda m: None)
            text = path.read_text(encoding="utf-8")
        self.assertIn("## Дельта после ответов", text)
        self.assertIn("Месяц определяется по дате покупки в Алматы (UTC+5)", text)


if __name__ == "__main__":
    unittest.main()
