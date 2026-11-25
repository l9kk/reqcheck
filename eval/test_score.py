import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from eval import score as sc

GOLDEN = sc.load_golden(sc.DEFAULT_GOLDEN)
MUST = [d["id"] for d in GOLDEN if d["must_find"]]


def quote(text, start, end=None):
    return {"text": text, "start": start, "end": end or start, "loc": ""}


def finding(fid, problem, quotes, impact="", fix=""):
    return {"id": fid, "scope": "doc", "req_ids": [], "criterion": "consistent", "severity": "критично",
            "quotes": quotes, "problem": problem, "impact": impact, "fix": fix, "test_hint": "", "role": ""}


def fake_report():
    return {
        "passport": {},
        "findings": [
            finding("F1", "Критерий приёмки противоречит Ф-2: месяц считается по дате совершения покупки, "
                          "значит покупка 31 января попадает в январь, а не в февраль.",
                    [quote("Месяц определяется по дате совершения покупки в Алматы.", 38),
                     quote("Покупка 31 января в 23:58 на 4 000 ₸", 64)]),
            finding("F2", "Неудачная вёрстка таблицы.", [quote("Покупка 31 января", 64)]),
            finding("F3", "Нет ссылки на макет.", [quote("Мобильный банк", 15)]),
        ],
        "questions": [
            {"id": "Q1", "text": "Какой код вернуть: 403 или 404 для чужой карты?",
             "quotes": [quote("Для чужой карты возвращается 404", 189)],
             "blocks": "", "options": [], "default": "", "addressee": "", "finding_ids": []},
        ],
    }


class GoldenFileTest(unittest.TestCase):
    def test_golden_shape(self):
        self.assertEqual(len(GOLDEN), 40)
        self.assertEqual([d["id"] for d in GOLDEN], [f"G{i:02d}" for i in range(1, 41)])
        self.assertEqual(sorted(MUST), ["G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08",
                                        "G11", "G12", "G25", "G31", "G35"])
        for d in GOLDEN:
            self.assertIn(d["severity"], sc.SEVERITIES, d["id"])
            self.assertTrue(d["lines"] and all(isinstance(n, int) for n in d["lines"]), d["id"])
            self.assertTrue(d["keywords"] and all(g for g in d["keywords"]), d["id"])


class MatchTest(unittest.TestCase):
    def test_line_slack(self):
        g01 = next(d for d in GOLDEN if d["id"] == "G01")
        self.assertTrue(sc.lines_overlap([quote("", 65)], g01))
        self.assertTrue(sc.lines_overlap([quote("", 30, 37)], g01))
        self.assertFalse(sc.lines_overlap([quote("", 66)], g01))
        self.assertFalse(sc.lines_overlap([], g01))

    def test_keyword_groups_all_required(self):
        d = {"keywords": [["феврал", "январ"], ["ф-2", "дат"]]}
        self.assertTrue(sc.keywords_match("Январь и ДАТА", d))
        self.assertFalse(sc.keywords_match("январь", d))


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.r = sc.score(fake_report(), GOLDEN)

    def test_recall(self):
        g01 = next(d for d in self.r["defects"] if d["id"] == "G01")
        self.assertEqual(g01["found_by"], ["F1"])
        self.assertEqual(self.r["found"], 1)
        self.assertAlmostEqual(self.r["recall"], 1 / 40)
        crit_total = sum(1 for d in GOLDEN if d["severity"] == "критично")
        self.assertEqual(self.r["by_severity"]["критично"], {"found": 1, "total": crit_total,
                                                              "recall": 1 / crit_total})
        self.assertEqual(self.r["by_severity"]["важно"]["found"], 0)

    def test_precision_and_unmatched(self):
        self.assertEqual(self.r["findings_total"], 3)
        self.assertEqual(self.r["findings_matched"], 1)
        self.assertAlmostEqual(self.r["precision"], 1 / 3)
        self.assertEqual([u["id"] for u in self.r["unmatched"]], ["F2", "F3"])

    def test_must_find(self):
        self.assertEqual(self.r["must_total"], 13)
        self.assertEqual(self.r["must_found"], 1)
        self.assertEqual(self.r["must_missed"], [i for i in MUST if i != "G01"])
        self.assertNotIn("G01", self.r["must_missed"])

    def test_questions(self):
        g05 = next(d for d in self.r["defects"] if d["id"] == "G05")
        self.assertEqual(g05["asked_by"], ["Q1"])
        self.assertEqual(self.r["asked_only"], ["G05"])
        self.assertEqual(self.r["found_or_asked"], 2)

    def test_empty_report(self):
        r = sc.score({"findings": [], "questions": []}, GOLDEN)
        self.assertEqual(r["recall"], 0)
        self.assertIsNone(r["precision"])
        self.assertEqual(len(r["must_missed"]), 13)


class CliTest(unittest.TestCase):
    def test_cli_writes_md_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = Path(tmp, "report.json")
            rep.write_text(json.dumps(fake_report(), ensure_ascii=False), encoding="utf-8")
            md = Path(tmp, "out.md")
            p = subprocess.run([sys.executable, str(Path(sc.__file__)), str(rep), "--md", str(md)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("Must-find missed", p.stdout)
            self.assertIn("| G01 |", md.read_text(encoding="utf-8"))
            p2 = subprocess.run([sys.executable, str(Path(sc.__file__)), str(Path(tmp, "missing.json"))],
                                capture_output=True, text=True)
            self.assertEqual(p2.returncode, 0)


if __name__ == "__main__":
    unittest.main()
