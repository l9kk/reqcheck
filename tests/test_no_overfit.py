import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["input/requirements.md", "examples/docs/autotopup.md", "examples/docs/cashback.md"]
N = 5


def shingles(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + N]) for i in range(len(words) - N + 1)}


class NoOverfitTest(unittest.TestCase):
    """Prompts, rules and code must not carry text copied from the sample documents."""

    def sources(self):
        return sorted((ROOT / "reqcheck").glob("*.py")) + [ROOT / "criteria.toml"]

    def test_no_five_word_phrase_from_sample_docs(self):
        code = {p: shingles(p.read_text(encoding="utf-8")) for p in self.sources()}
        for doc in DOCS:
            doc_sh = shingles((ROOT / doc).read_text(encoding="utf-8"))
            for path, sh in code.items():
                self.assertFalse(doc_sh & sh, f"{doc} -> {path.name}: {sorted(doc_sh & sh)[:5]}")

    def test_no_api_names_from_sample_docs(self):
        text = " ".join(p.read_text(encoding="utf-8") for p in self.sources()).lower()
        for name in ("savelimit", "spentmonth", "/alerts/", "cardid"):
            self.assertNotIn(name, text)

    def test_check_catches_a_copied_phrase(self):
        doc = (ROOT / DOCS[0]).read_text(encoding="utf-8")
        line = next(x for x in doc.splitlines() if len(re.findall(r"\w+", x)) >= 8)
        self.assertTrue(shingles(doc) & shingles(f'PROMPT = "{line}"'))


if __name__ == "__main__":
    unittest.main()
