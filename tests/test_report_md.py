import json
import re
import unittest
from pathlib import Path

from themis.model import ChecklistRow, Diagnostic, Finding, Question, Quote, Report, Requirement
from themis.pipeline import all_criteria, load_criteria
from themis.report_md import brief, problem_parts, render
from themis.segment import clean

ROOT = Path(__file__).resolve().parent.parent
REPORTS = [ROOT / "report" / "report.json", ROOT / "examples" / "autotopup" / "report.json",
           ROOT / "examples" / "cashback" / "report.json"]
CRIT = all_criteria(load_criteria())


def load(path) -> Report:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rep = Report(passport=d["passport"])
    rep.requirements = [Requirement(**{**r, "quote": Quote(**r["quote"])}) for r in d["requirements"]]
    rep.findings = [Finding(**{**f, "quotes": [Quote(**q) for q in f["quotes"]]}) for f in d["findings"]]
    rep.questions = [Question(**{**q, "quotes": [Quote(**x) for x in q["quotes"]]}) for q in d["questions"]]
    rep.checklist = [ChecklistRow(**c) for c in d["checklist"]]
    rep.diagnostics = [Diagnostic(**x) for x in d["diagnostics"]]
    for k in ("verdict", "set_summary", "trace", "req_checks", "drops"):
        setattr(rep, k, d[k])
    return rep


def q(text, line):
    return Quote(text=text, start=line, end=line, loc=f"строка {line} (Раздел)")


def small_report() -> Report:
    reqs = [Requirement(id=f"R-0{i}", doc_id=f"Ф-{i}", type="functional", short=f"Требование {i}", section="Раздел",
                        quote=q(f"Текст требования {i}.", 10 + i)) for i in (1, 2, 3)]
    f1 = Finding(id="D-01", scope="req", req_ids=["R-01", "R-02", "R-03"], criterion="correct", severity="критично",
                 quotes=[q("Текст требования 1.", 11), q("Текст требования 2.", 12)],
                 problem="Ф-1 противоречит Ф-2 по лимиту уведомлений. Также: Ф-1 противоречит Ф-2 по лимиту. "
                         "Также: Ф-3 не говорит, какое правило главнее.",
                 impact="Тест даст два ожидаемых результата. Разработчик выберет сам.", fix="Выбрать одно правило.",
                 test_hint="Сменить порог после push.")
    f2 = Finding(id="D-02", scope="set", req_ids=[], criterion="set_complete", severity="мелочь",
                 quotes=[q("Текст требования 3.", 13)], problem="Нет требований к мониторингу и логированию.")
    qs = Question(id="Q-01", text="Отправлять ли второй push после смены порога?", quotes=[q("Текст требования 1.", 11)],
                  blocks="Нельзя написать тест.", options=["Да", "Нет"], default="Да, сбросить признак.",
                  addressee="бизнес", finding_ids=["D-01"])
    trace = [{"role": "Auditor", "cached": True, "seconds": 0.0, "in_tokens": 1200, "out_tokens": 3400, "orig_seconds": 12.5},
             {"role": "Critic", "cached": True, "seconds": 0.0, "in_tokens": 800, "out_tokens": 600, "orig_seconds": 7.5}]
    drops = [{"role": "Guard", "reason": "дубликат", "item": "секретный текст дубликата"},
             {"role": "Critic", "reason": "объединено с D-01", "item": "текст слияния"},
             {"role": "Critic", "reason": "объединено с D-01", "item": "ещё текст слияния"}]
    return Report(passport={"document": "doc.md", "date": "2026-11-27 10:00", "model": "m", "provider": "p",
                            "agent_version": "0.1.0 (v1.3)", "llm_calls": 0, "llm_cached": 2, "seconds": 0.1,
                            "llm_seconds_uncached": 20.0},
                  requirements=reqs, findings=[f1, f2], questions=[qs], trace=trace, drops=drops,
                  req_checks={"R-01": ["correct"]},
                  verdict={"status": "Нет", "text": "Нельзя.", "fix_first": ["D-01"]})


class BriefTest(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(brief("Коротко и ясно.", 50), "Коротко и ясно.")

    def test_cut_on_word_boundary(self):
        s = "Если push уже отправлен по старому порогу, Ф-4 требует нового push после повышения порога"
        out = brief(s, 60)
        self.assertTrue(out.endswith("…"))
        self.assertTrue(s.startswith(out[:-1]))
        self.assertIn(s[len(out) - 1], " ,")

    def test_prefers_sentence_end(self):
        s = "Первое предложение достаточно длинное. Второе предложение уже не помещается в лимит."
        self.assertEqual(brief(s, 60), "Первое предложение достаточно длинное.")


class MergedTextTest(unittest.TestCase):
    def test_parts_split_and_near_duplicate_dropped(self):
        parts = problem_parts("Ф-1 противоречит Ф-2 по лимиту уведомлений. Также: Ф-1 противоречит Ф-2 по лимиту. "
                              "Также: Ф-3 не говорит, какое правило главнее.")
        self.assertEqual(parts, ["Ф-1 противоречит Ф-2 по лимиту уведомлений.", "Ф-3 не говорит, какое правило главнее."])

    def test_plain_problem_is_one_part(self):
        self.assertEqual(problem_parts("Нет требований к мониторингу."), ["Нет требований к мониторингу."])


class RenderSmallTest(unittest.TestCase):
    def setUp(self):
        self.md = render(small_report(), CRIT)

    def test_first_screen_comes_first(self):
        top = self.md.split("## 1. Паспорт прогона")[0]
        self.assertIn("## Главное за 2 минуты", top)
        self.assertIn("**Начинать разработку и тестирование: Нет.**", top)
        self.assertIn("Сначала ответить на Q-01 и исправить D-01.", top)
        self.assertIn("**D-01** (Корректное, вопрос Q-01): Ф-1 противоречит Ф-2", top)
        self.assertIn("> «Текст требования 2.» (строка 12)", top)
        self.assertIn("- Последствия: Тест даст два ожидаемых результата.", top)
        self.assertIn("- Варианты: (а) Да; (б) Нет", top)
        self.assertIn("- Рекомендация агента: Да, сбросить признак.", top)
        self.assertIn("Цитат: **4**", top)

    def test_finding_printed_in_full_once(self):
        self.assertEqual(self.md.count("**D-01** · критично"), 1)
        self.assertEqual(self.md.count("- Как исправить (окончательно после ответа на Q-01): Выбрать одно правило."), 1)
        self.assertIn("- См. **D-01** (критично, описано под R-01): Ф-1 противоречит Ф-2", self.md)
        self.assertEqual(self.md.count("- См. **D-01**"), 2)

    def test_merged_parts_are_sub_bullets(self):
        self.assertNotIn("Также: Ф-1 противоречит", self.md)
        self.assertIn("- Проблема: Ф-1 противоречит Ф-2 по лимиту уведомлений.\n  - Также: Ф-3 не говорит", self.md)

    def test_passport_wording(self):
        self.assertIn("| Запросов к модели | 2, все ответы взяты из кэша прошлого прогона", self.md)
        self.assertIn("| Время работы модели | 20.0 с (в исходном прогоне, до кэша) |", self.md)
        self.assertIn("| Токены модели, вход / выход | 2 000 / 4 000 (в исходном прогоне, до кэша) |", self.md)
        self.assertNotIn("из кэша: 2", self.md)

    def test_drops_are_counted_not_listed(self):
        self.assertIn("- Guard: дубликат: 1", self.md)
        self.assertIn("- Critic: объединено с другим замечанием, текст добавлен к нему: 2", self.md)
        self.assertNotIn("секретный текст дубликата", self.md)
        self.assertIn("поле `drops`", self.md)

    def test_live_run_passport(self):
        rep = small_report()
        rep.passport.update(llm_calls=2, llm_cached=0)
        rep.passport.pop("llm_seconds_uncached")
        for t in rep.trace:
            t.update(cached=False, seconds=t.pop("orig_seconds"))
        md = render(rep, CRIT)
        self.assertIn("| Запросов к модели | 2 |", md)
        self.assertIn("| Время работы модели | 20.0 с |", md)


class RenderOfficialTest(unittest.TestCase):
    def test_nothing_lost_and_no_duplicates(self):
        for path in REPORTS:
            with self.subTest(report=path.parent.name):
                rep = load(path)
                md = render(rep, CRIT)
                flat = re.sub(r"\s+", " ", md)
                for f in rep.findings:
                    self.assertEqual(md.count(f"**{f.id}** · "), 1, f.id)
                    for part in problem_parts(f.problem):
                        self.assertIn(re.sub(r"\s+", " ", part), flat, f.id)
                    for text in (f.impact, f.fix, f.test_hint):
                        self.assertIn(re.sub(r"\s+", " ", text), flat, f.id)
                    for x in f.quotes:
                        self.assertIn(f"({x.loc})", md, f.id)
                for q in rep.questions:
                    for text in [q.text, q.blocks, q.default] + q.options:
                        self.assertIn(text, md, q.id)
                for r in rep.requirements:
                    self.assertRegex(md, rf"\| {r.id} \| [^|]+ \| ")
                self.assertNotIn(" Также: ", md.split("## 9.")[0].replace("- Также: ", ""))

    def test_official_first_screen_is_short(self):
        md = render(load(REPORTS[0]), CRIT)
        top = md.split("## 1. Паспорт прогона")[0]
        self.assertLessEqual(len(top.splitlines()), 62)
        for f in load(REPORTS[0]).findings:
            if f.severity == "критично":
                self.assertIn(f"**{f.id}** (", top)

    def test_triage_never_cuts_mid_word(self):
        cuts = 0
        for path in REPORTS:
            for f in load(path).findings:
                full = clean(problem_parts(f.problem)[0])
                out = brief(full, 160)
                if out.endswith("…"):
                    cuts += 1
                    self.assertTrue(full.startswith(out[:-1]), f.id)
                    self.assertIn(full[len(out) - 1], " ,;:—-–", f.id)
        self.assertGreater(cuts, 0)


if __name__ == "__main__":
    unittest.main()
