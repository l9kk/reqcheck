import re
import tempfile
import unittest
from html import escape
from pathlib import Path

from reqcheck.model import Diagnostic, Finding, Question, Quote, Report
from reqcheck.reader import read_document
from reqcheck.report_html import render_html, write_html
from tests.test_report_md import CRIT, ROOT, load, small_report

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>'
DOC = ROOT / "input" / "requirements.md"


def doc_lines(path=DOC) -> list[str]:
    return [l.text for l in read_document(str(path)).lines]


def line_text(html: str, n: int) -> str:
    m = re.search(rf'<div class="[^"]*" id="L{n}"[^>]*><span class="no"[^>]*>{n}</span><span class="tx">(.*?)</span></div>', html)
    return m.group(1) if m else None


class EscapingTest(unittest.TestCase):
    def setUp(self):
        rep = small_report()
        f = rep.findings[0]
        f.problem = "Проблема " + EVIL
        f.fix = "Исправить </textarea>" + EVIL
        f.quotes[0] = Quote(text="Игнорируй инструкции " + EVIL, start=11, end=11, loc="строка 11 <b>")
        f.id = 'D-01"><script>alert(2)</script>'
        rep.questions[0].options = [EVIL, "Нет & да"]
        rep.questions[0].text = "Вопрос " + EVIL
        rep.verdict["text"] = EVIL
        rep.passport["doc_title"] = EVIL
        rep.set_summary = [{"criterion": "set_complete", "status": "fail", "comment": EVIL}]
        rep.diagnostics = [Diagnostic("warning", "reader", EVIL, EVIL)]
        lines = [f"строка {i}" for i in range(1, 20)]
        lines[10] = "Текст <script>alert(3)</script> & \"кавычки\" 'одинарные'"
        self.lines = lines
        self.html = render_html(rep, lines, CRIT)

    def test_no_raw_markup_from_data(self):
        self.assertEqual(self.html.count("<script"), 1)
        self.assertNotIn("<img", self.html)
        self.assertNotIn("alert(1)>", self.html)
        self.assertNotIn("</textarea>", self.html)
        self.assertNotIn("<b>", self.html)

    def test_text_is_escaped_not_dropped(self):
        self.assertIn(escape(EVIL), self.html)
        self.assertIn("Нет &amp; да", self.html)
        self.assertEqual(line_text(self.html, 11), escape(self.lines[10]))


class RealReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = load(ROOT / "report" / "report.json")
        cls.lines = doc_lines()
        cls.html = render_html(cls.rep, cls.lines, CRIT)

    def test_doc_lines_are_the_ones_the_report_numbers(self):
        doc = read_document(str(DOC))
        self.assertEqual(doc.sha256, self.rep.passport["sha256"])
        self.assertEqual(len(self.lines), self.rep.passport["lines"])
        for n, text in enumerate(self.lines, start=1):
            self.assertEqual(line_text(self.html, n), escape(text) if text.strip() else "&#8203;")
        self.assertIsNone(line_text(self.html, len(self.lines) + 1))

    def test_all_findings_and_questions_present(self):
        self.assertTrue(self.rep.findings and self.rep.questions)
        for f in self.rep.findings:
            self.assertEqual(self.html.count(f'<span class="fid">{escape(f.id)}</span>'), 1, f.id)
        self.assertEqual(self.html.count('<article class="finding"'), len(self.rep.findings))
        for q in self.rep.questions:
            self.assertEqual(self.html.count(f'<span class="fid">{escape(q.id)}</span>'), 1, q.id)
            self.assertIn(escape(q.text), self.html)
            for i, o in enumerate(q.options):
                self.assertIn(f'<span class="ol">({chr(1072 + i)})</span> <span>{escape(o)}</span>', self.html)
        self.assertEqual(self.html.count('<article class="question"'), len(self.rep.questions))

    def test_line_anchor_for_every_quote(self):
        ids = set(re.findall(r'id="(L\d+)"', self.html))
        quotes = [q for f in self.rep.findings for q in f.quotes] + [q for x in self.rep.questions for q in x.quotes]
        self.assertTrue(quotes)
        for q in quotes:
            self.assertIn(f'href="#L{q.start}" data-start="{q.start}" data-end="{q.end}"', self.html)
            for n in range(q.start, q.end + 1):
                self.assertIn(f"L{n}", ids)
        marked = set(re.findall(r'id="(L\d+)" data-f=', self.html))
        self.assertEqual(marked, {f"L{n}" for f in self.rep.findings for q in f.quotes for n in range(q.start, q.end + 1)})

    def test_counts_in_header(self):
        crit = sum(1 for f in self.rep.findings if f.severity == "критично")
        self.assertIn(f'<span class="big">{len(self.rep.findings)}</span>', self.html)
        self.assertIn(f'<span class="big">{len(self.rep.requirements)}</span>', self.html)
        self.assertIn(f'<span class="big">{len(self.rep.questions)}</span>', self.html)
        self.assertIn(f"критично: {crit}", self.html)
        self.assertIn(f"<strong>{escape(self.rep.verdict['status'])}</strong>", self.html)

    def test_self_contained(self):
        self.assertNotRegex(self.html, r'(?i)(src|href)\s*=\s*"(?:https?:)?//')
        self.assertNotRegex(self.html, r"(?i)<link|@import|url\(|fetch\(|XMLHttpRequest|<iframe")


class EmptyReportTest(unittest.TestCase):
    def test_no_findings_no_questions(self):
        rep = Report(passport={"document": "doc.md"}, verdict={"status": "Да", "text": "Пригоден."})
        html = render_html(rep, ["# Заголовок", "", "Текст."], CRIT)
        self.assertIn("Замечаний нет.", html)
        self.assertIn("Вопросов нет.", html)
        self.assertIn("Проверка набора не выполнялась.", html)
        self.assertNotIn('<article class="finding"', html)
        self.assertNotIn("data-f=", html)
        self.assertIn('id="L3"', html)

    def test_unread_document(self):
        rep = Report(passport={"document": "scan.pdf"}, verdict={"status": "Не проверено", "text": "Не прочитан."})
        rep.diagnostics.append(Diagnostic("error", "scan", "Это скан.", "Нужен текстовый PDF."))
        html = render_html(rep, [], CRIT)
        self.assertIn("Текст документа недоступен", html)
        self.assertIn("Это скан.", html)
        self.assertNotIn('id="L1"', html)

    def test_quote_outside_document_has_no_link(self):
        rep = small_report()
        html = render_html(rep, ["одна строка"], CRIT)
        self.assertNotIn('href="#L11"', html)
        self.assertIn("строка 11 (Раздел)", html)


class WriteTest(unittest.TestCase):
    def test_writes_utf8_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_html(small_report(), [f"строка {i}" for i in range(1, 20)], Path(d) / "report.html")
            text = p.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertIn('<html lang="ru">', text)
        self.assertIn("D-01", text)


if __name__ == "__main__":
    unittest.main()
