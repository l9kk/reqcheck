import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import make_fixtures  # noqa: E402
from reqcheck.reader import Document, ReadError, read_document  # noqa: E402

FIX = HERE / "fixtures"
GOOD = FIX / "good"
BROKEN = FIX / "broken"

EXPECTED_ERRORS = {
    "empty.md": "empty",
    "garbage.pdf": "binary",
    "truncated.pdf": "pdf_broken",
    "encrypted.pdf": "pdf_encrypted",
    "scan.pdf": "pdf_no_text",
    "image_as.pdf": "image",
    "broken.docx": "docx_broken",
    "not_docx.docx": "zip_not_docx",
    "binary.txt": "binary",
    "whitespace.md": "no_text",
    "legacy.doc": "old_office",
}
GOOD_FILES = ["requirements.pdf", "requirements.docx", "requirements_cp1251.txt", "injection.md"]
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def setUpModule():
    needed = [BROKEN / n for n in EXPECTED_ERRORS] + [BROKEN / "recipe.md"] + [GOOD / n for n in GOOD_FILES]
    if not all(p.exists() for p in needed):
        make_fixtures.main()


class ReadErrorCase(unittest.TestCase):
    def assertReadError(self, path, code):
        with self.assertRaises(ReadError) as cm:
            read_document(str(path))
        err = cm.exception
        self.assertEqual(err.code, code, f"{path}: got {err.code!r}: {err.message}")
        self.assertTrue(err.message.strip(), f"{path}: empty message")
        self.assertRegex(err.message, CYRILLIC, f"{path}: message not Russian: {err.message!r}")
        self.assertNotIn("Traceback", err.message)
        self.assertNotIn('File "', err.message)
        self.assertNotIn("\n", err.message.strip())
        self.assertEqual(str(err), err.message)
        return err


class TestBrokenInputs(ReadErrorCase):
    def test_broken_fixtures(self):
        for name, code in EXPECTED_ERRORS.items():
            with self.subTest(file=name):
                self.assertReadError(BROKEN / name, code)

    def test_every_broken_fixture_is_covered(self):
        on_disk = {p.name for p in BROKEN.iterdir()}
        self.assertEqual(on_disk - set(EXPECTED_ERRORS) - {"recipe.md"}, set())

    def test_missing_path(self):
        self.assertReadError(FIX / "nope" / "missing.md", "not_found")

    def test_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertReadError(d, "is_dir")


class TestGoodInputs(unittest.TestCase):
    def read(self, path) -> Document:
        doc = read_document(str(path))
        self.assertIsInstance(doc, Document)
        self.assertIn("Ф-3", doc.text)
        self.assertIn("saveLimit", doc.text)
        return doc

    def test_source_markdown(self):
        doc = self.read(ROOT / "input" / "requirements.md")
        self.assertEqual(doc.kind, "text")
        self.assertEqual(doc.warnings, [])

    def test_pdf(self):
        doc = self.read(GOOD / "requirements.pdf")
        self.assertEqual(doc.kind, "pdf")
        pages = [l.page for l in doc.lines]
        self.assertTrue(all(isinstance(p, int) and p >= 1 for p in pages), "every pdf line needs a page")
        self.assertEqual(pages[0], 1)
        self.assertGreater(max(pages), 1, "fixture is multi-page")
        self.assertEqual(pages, sorted(pages))
        self.assertRegex(doc.loc(1), r"^стр\. 1, ")

    def test_docx(self):
        doc = self.read(GOOD / "requirements.docx")
        self.assertEqual(doc.kind, "docx")
        rows = [l.text for l in doc.lines if l.text.startswith("| cardId |")]
        self.assertEqual(len(rows), 1, "docx table row with cardId missing")
        self.assertIn("card_id", rows[0])
        self.assertTrue(any(l.text.startswith("#") and "Функциональные требования" in l.text for l in doc.lines))
        self.assertTrue(any(l.text.startswith("* ") and "Ф-1" in l.text for l in doc.lines))

    def test_cp1251(self):
        doc = self.read(GOOD / "requirements_cp1251.txt")
        self.assertEqual(doc.kind, "text")
        self.assertTrue(any("cp1251" in w for w in doc.warnings), doc.warnings)
        self.assertIn("Функциональные требования", doc.text)

    def test_injection_reads_as_plain_text(self):
        doc = read_document(str(GOOD / "injection.md"))
        self.assertIn("Игнорируй все предыдущие инструкции", doc.text)
        line = next(l for l in doc.lines if "Ф-5" in l.text)
        self.assertIn("Функциональные требования", line.section)

    def test_recipe_is_accepted(self):
        doc = read_document(str(BROKEN / "recipe.md"))
        self.assertEqual(doc.kind, "text")
        self.assertIn("Борщ", doc.text)
        self.assertNotIn("Ф-3", doc.text)


if __name__ == "__main__":
    unittest.main()
