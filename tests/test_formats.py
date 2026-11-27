import tempfile
import unittest
import zipfile
from pathlib import Path

from reqcheck.pipeline import Pipeline
from reqcheck.reader import ReadError, read_document
from tests.fake_llm import FakeLLM

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
ROWS = [("ID", "Требование", "Приоритет"),
        ("ФТ-1", "Система должна отправлять push-уведомление о списании в течение 5 секунд.", "Высокий"),
        ("ФТ-2", "Система должна быстро показывать историю операций.", "Средний"),
        ("ФТ-3", "Пользователь должен иметь возможность отключить уведомления.", "Низкий"),
        ("НФТ-1", "Сервис должен быть доступен 99,9% времени в месяц.", "Высокий")]


def make_xlsx(path: Path, rows=ROWS) -> None:
    strings = sorted({c for r in rows for c in r})
    idx = {s: i for i, s in enumerate(strings)}
    sst = "".join(f"<si><t>{s}</t></si>" for s in strings)
    body = "".join("<row>" + "".join(f'<c t="s"><v>{idx[c]}</v></c>' for c in r) + "</row>" for r in rows)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook {NS} {RNS}><sheets><sheet name="Требования" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f"<sst {NS}>{sst}</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {NS}><sheetData>{body}</sheetData></worksheet>")


HTML = """<!doctype html><html><head><style>p{color:red}</style><script>alert(1)</script></head><body>
<h1>ТЗ: Уведомления</h1><h2>Требования</h2>
<ul><li>ФТ-1. Система должна отправлять push-уведомление о списании.</li>
<li>ФТ-2. Система должна быстро показывать историю.</li></ul>
<table><tr><th>ID</th><th>Требование</th></tr><tr><td>НФТ-1</td><td>Доступность 99,9%.</td></tr></table>
</body></html>"""


class FormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_xlsx_rows_become_table_lines(self):
        f = self.dir / "req.xlsx"
        make_xlsx(f)
        doc = read_document(str(f))
        self.assertEqual(doc.kind, "xlsx")
        texts = [l.text for l in doc.lines]
        self.assertEqual(texts[0], "## Требования")
        self.assertEqual(texts[1], "| ID | Требование | Приоритет |")
        self.assertIn("| ФТ-2 | Система должна быстро показывать историю операций. | Средний |", texts)

    def test_broken_xlsx_is_a_clear_error(self):
        f = self.dir / "bad.xlsx"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("xl/workbook.xml", "<workbook")
        with self.assertRaises(ReadError) as cm:
            read_document(str(f))
        self.assertEqual(cm.exception.code, "xlsx_broken")

    def test_html_keeps_structure_and_drops_scripts(self):
        f = self.dir / "req.html"
        f.write_text(HTML, encoding="utf-8")
        doc = read_document(str(f))
        texts = [l.text for l in doc.lines]
        self.assertEqual(doc.kind, "html")
        self.assertEqual(texts[:2], ["# ТЗ: Уведомления", "## Требования"])
        self.assertIn("* ФТ-1. Система должна отправлять push-уведомление о списании.", texts)
        self.assertIn("| НФТ-1 | Доступность 99,9%. |", texts)
        self.assertFalse(any("alert" in t or "color" in t for t in texts))

    def test_html_runs_through_pipeline_with_grounded_quotes(self):
        f = self.dir / "req.html"
        f.write_text(HTML, encoding="utf-8")
        rep = Pipeline(FakeLLM(), log=lambda m: None).run(str(f))
        self.assertFalse([d for d in rep.diagnostics if d.level == "error"])
        self.assertTrue(rep.requirements)
        self.assertTrue(rep.findings)
        self.assertTrue(all(q.start >= 1 for x in rep.findings for q in x.quotes))

if __name__ == "__main__":
    unittest.main()
