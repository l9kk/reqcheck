import re
import unittest
from html import escape, unescape

from reqcheck.report_html import md_line, render_html
from tests.test_report_html import DOC, EVIL, doc_lines
from tests.test_report_md import CRIT, ROOT, load, small_report


TAG_ON = r'<[a-z]+(?:\s+[a-z-]+(?:=(?:"[^"]*"|[^\s>"]*))?)*\s+on[a-z]+='


def chips(html: str) -> list[tuple[str, str]]:
    return re.findall(r'<a class="flink chip" href="#[^"]+" data-sev="([^"]+)">.*?<b>([^<]+)</b>', html)


def data_md(html: str, n: int) -> str:
    m = re.search(rf'id="L{n}"[^>]* data-md="([^"]*)"', html)
    return unescape(m.group(1)) if m else None


class FixFirstChipsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = load(ROOT / "report" / "report.json")
        cls.html = render_html(cls.rep, doc_lines(), CRIT)

    def test_chips_carry_severity(self):
        sev = {f.id: f.severity for f in self.rep.findings}
        got = chips(self.html)
        self.assertEqual(sorted(i for _, i in got), sorted(self.rep.verdict["fix_first"]))
        for s, i in got:
            self.assertEqual(s, sev[i], i)

    def test_critical_first_and_others_labelled(self):
        got = chips(self.html)
        ranks = [0 if s == "критично" else 1 for s, _ in got]
        self.assertEqual(ranks, sorted(ranks))
        for s, i in got:
            if s != "критично":
                self.assertRegex(self.html, rf'<b>{re.escape(i)}</b> · <span class="clab">{s}</span>')
        crit = sum(1 for s, _ in got if s == "критично")
        self.assertIn(f"Критично · {crit}", self.html)

    def test_chip_titles_are_short(self):
        for t in re.findall(r'<a class="flink chip".*?<span class="ct">([^<]*)</span>', self.html):
            self.assertTrue(1 <= len(unescape(t).rstrip("…").split()) <= 6, t)

    def test_verdict_prefix_not_repeated(self):
        self.assertEqual(self.html.count("Начинать разработку и тестирование нельзя"), 0)
        self.assertIn('<span class="pg" aria-hidden="true">✕</span><strong>Нет</strong>', self.html)

    def test_three_stat_cards(self):
        stats = re.search(r'<dl class="stats">(.*?)</dl>', self.html).group(1)
        self.assertEqual(stats.count("<dt>"), 3)
        self.assertNotIn("Строк в документе", self.html)


class DefaultFilterTest(unittest.TestCase):
    def test_default_is_critical(self):
        html = render_html(small_report(), [f"строка {i}" for i in range(1, 20)], CRIT)
        self.assertIn('data-default="критично"', html)
        self.assertIn('data-sev="критично" aria-pressed="true"', html)
        self.assertIn('data-sev="" aria-pressed="false">Все <span class="cnt">2</span>', html)
        self.assertIn("#sev=", html)

    def test_all_when_no_critical(self):
        rep = small_report()
        for f in rep.findings:
            f.severity = "мелочь"
        html = render_html(rep, [f"строка {i}" for i in range(1, 20)], CRIT)
        self.assertIn('data-default=""', html)
        self.assertIn('data-sev="" aria-pressed="true"', html)


class MarkdownTest(unittest.TestCase):
    def test_noise_stripped(self):
        self.assertEqual(md_line("## Часть A"), ("h2", "Часть A"))
        self.assertEqual(md_line("| :--- | :--- |")[0], "sep")
        self.assertEqual(md_line("---")[0], "hr")
        kind, out = md_line("| **Наименование задачи** | Месячный порог |")
        self.assertEqual(kind, "tr")
        self.assertEqual(out, '<span class="c"><strong>Наименование задачи</strong></span><span class="c">Месячный порог</span>')
        for noise in ("|", "**", "---", ":---", "#"):
            self.assertNotIn(noise, out)

    def test_real_document_rendering(self):
        lines = doc_lines()
        html = render_html(load(ROOT / "report" / "report.json"), lines, CRIT)
        for n, text in enumerate(lines, start=1):
            md = data_md(html, n)
            if md is None:
                continue
            plain = re.sub(r"<[^>]+>", "", md)
            for noise in ("|", "**", ":---"):
                self.assertNotIn(noise, plain, n)
            self.assertFalse(plain.startswith("#"), n)

    def test_line_keeps_raw_text_and_number(self):
        html = render_html(small_report(), ["# Заголовок", "| a | **b** |"], CRIT)
        self.assertIn('<div class="ln md-h1" id="L1" data-md="Заголовок"><span class="no" style="min-width:1ch">1</span>'
                      '<span class="tx"># Заголовок</span></div>', html)
        self.assertIn('<span class="tx">| a | **b** |</span>', html)


class PolishEscapingTest(unittest.TestCase):
    def setUp(self):
        rep = small_report()
        f = rep.findings[0]
        f.problem = EVIL + ". Вторая фраза " + EVIL
        f.id = 'D-01"><script>alert(2)</script>'
        rep.verdict["fix_first"] = [f.id]
        lines = [f"строка {i}" for i in range(1, 20)]
        lines[10] = "| **<script>alert(3)</script>** | <img src=x onerror=alert(1)> |"
        lines[11] = "## " + EVIL
        self.html = render_html(rep, lines, CRIT)

    def test_no_raw_markup(self):
        self.assertEqual(self.html.count("<script"), 1)
        self.assertNotIn("<img", self.html)
        self.assertNotRegex(self.html, TAG_ON)

    def test_data_md_is_escaped_html(self):
        for n in (11, 12):
            md = data_md(self.html, n)
            self.assertNotIn("<script", md)
            self.assertNotIn("<img", md)
            self.assertIn("&lt;script&gt;", md)
        bad_id = escape('D-01"><script>alert(2)</script>')
        self.assertIn(f"<b>{bad_id}</b>", self.html)

    def test_short_title_escaped(self):
        self.assertIn('<span class="ftitle">&lt;script&gt;', self.html)


if __name__ == "__main__":
    unittest.main()
