"""Ablation: what each pipeline stage adds, scored against the golden lists.

Replays the committed LLM cache (.cache/llm). Makes no model calls: a cache miss raises CacheMiss.

Usage: python -m eval.ablation [--md eval/ablation.md]
"""
import argparse
import copy
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from eval.score import load_golden, score
from reqcheck import pipeline as pl
from reqcheck.llm import LLM
from reqcheck.roles import restore

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "llm"
PROVIDER = "anthropic"
MODEL = "claude-opus-5-5"
FINDING_ROLES = ("Auditor", "CrossChecker", "EdgeCaser", "WholeDoc")

DOCS = [
    ("Выданное ТЗ", "input/requirements.md", "report/report.json", "eval/golden.toml"),
    ("autotopup", "examples/docs/autotopup.md", "examples/autotopup/report.json", "eval/golden_autotopup.toml"),
    ("cashback", "examples/docs/cashback.md", "examples/cashback/report.json", "eval/golden_cashback.toml"),
]

VARIANTS = [
    ("rules", "Только правила (Linter)", ("rules",)),
    ("auditor", "+ Auditor", ("rules", "Auditor")),
    ("cross", "+ CrossChecker/EdgeCaser", ("rules", "Auditor", "CrossChecker", "EdgeCaser")),
    ("wholedoc", "+ WholeDoc (все ветки, до Критика)", ("rules", "Auditor", "CrossChecker", "EdgeCaser", "WholeDoc")),
]

BASELINE = {
    "source": "eval/baseline/README.md",
    "date": "27.11.2026",
    "model": "claude-opus-5-5",
    "rows": {
        "Выданное ТЗ": ("30 (29)", "36/40 (35/40)", "12/13 (13/13)"),
        "autotopup": ("26", "18/18", "8/8"),
        "cashback": ("33", "19/20", "8/9"),
    },
}


class CacheMiss(RuntimeError):
    pass


class ReplayLLM(LLM):
    """LLM that only reads the cache. Pinned to the provider and model the cache was recorded with."""

    def __init__(self, cache_dir=CACHE):
        super().__init__(use_cache=True, cache_dir=str(cache_dir))
        self.provider, self.model = PROVIDER, MODEL
        self.api_key, self.base_url = "x", "http://127.0.0.1:9"

    def _call(self, role, system, user):
        raise CacheMiss(f"{role}: prompt not in {self.cache_dir}; the replay built a different prompt")


class Replay(pl.Pipeline):
    """The real pipeline, run in one thread, keeping a copy of what each role returned."""

    def __init__(self, llm):
        super().__init__(llm, log=lambda m: None, workers=1)
        self.out: dict[str, list] = {}
        self.role_now = ""
        self.quotes = Counter()

    def _keep(self, role, fn, *args):
        self.role_now = role
        res = fn(*args)
        self.out[role] = copy.deepcopy(res)
        return res

    def segment(self, cands, rep):
        locate = self.g.locate

        def counted(quote, hint=None):
            q = locate(quote, hint)
            kind = "missed" if q is None else "verbatim" if q.text == restore(quote).strip() else "fixed"
            self.quotes[self.role_now, kind] += 1
            return q

        self.g.locate = counted
        self.role_now = "Segmenter"
        return super().segment(cands, rep)

    def audit(self, numbered, reqs, rep):
        return self._keep("Auditor", super().audit, numbered, reqs, rep)

    def stage2(self, numbered, reqs, known, rep):
        self.out["known"] = copy.deepcopy(known)
        return super().stage2(numbered, reqs, known, rep)

    def cross(self, numbered, reqs, known, rep):
        return self._keep("CrossChecker", super().cross, numbered, reqs, known, rep)

    def edge(self, numbered, reqs, known, rep):
        return self._keep("EdgeCaser", super().edge, numbered, reqs, known, rep)

    def whole(self, numbered, rep):
        return self._keep("WholeDoc", super().whole, numbered, rep)

    def critic(self, numbered, findings, rep):
        self.out["pre_critic"] = copy.deepcopy(findings)
        self.role_now = "Critic"
        return super().critic(numbered, findings, rep)

    def clarify(self, numbered, findings, rep):
        self.role_now = "Clarifier"
        return super().clarify(numbered, findings, rep)


def build(pipe: Replay, rep, parts) -> list:
    """Findings of a variant, made the way run() makes them before the Critic: attach_reqs, dedupe, F-ids."""
    out = dict(pipe.out)
    out["rules"] = out["known"][:len(out["known"]) - len(out["Auditor"])]
    findings = copy.deepcopy([f for p in parts for f in out.get(p, [])])
    scratch = pl.Pipeline(pipe.llm, log=lambda m: None, workers=1)
    scratch.attach_reqs(findings, rep.requirements)
    findings = scratch.dedupe(findings)
    for i, f in enumerate(findings, start=1):
        f.id = f"F-{i:02d}"
    return findings


def as_report(findings, doc_text: str) -> dict:
    findings = copy.deepcopy(findings)
    pl.tag_assumptions(findings, doc_text)
    return {"findings": [asdict(f) for f in findings], "questions": []}


def same_findings(a: list[dict], b: list[dict]) -> bool:
    key = lambda f: (f["problem"], f["severity"], f["criterion"], [(q["start"], q["end"]) for q in f["quotes"]])
    return [key(f) for f in a] == [key(f) for f in b]


def cells(r: dict) -> tuple[str, str, str]:
    return str(r["findings_total"]), f"{r['found']}/{r['golden_total']}", f"{r['must_found']}/{r['must_total']}"


def found(r: dict) -> set[str]:
    return {d["id"] for d in r["defects"] if d["found_by"]}


def step_diff(before: dict, after: dict) -> str:
    gained, lost = sorted(found(after) - found(before)), sorted(found(before) - found(after))
    parts = (["+" + ", +".join(gained)] if gained else []) + (["-" + ", -".join(lost)] if lost else [])
    return " ".join(parts) or "-"


def run_doc(name, doc, committed, golden_path) -> dict:
    llm = ReplayLLM()
    pipe = Replay(llm)
    rep = pipe.run(str(ROOT / doc))
    calls = rep.passport["llm_calls"]
    if calls or any(not t["cached"] for t in rep.trace):
        raise CacheMiss(f"{name}: {calls} real calls")
    golden = load_golden(ROOT / golden_path)
    text = pipe.doc.text
    rows = {}
    for key, _, parts in VARIANTS:
        rows[key] = score(as_report(build(pipe, rep, parts), text), golden)
    built = [asdict(f) for f in build(pipe, rep, VARIANTS[-1][2])]
    critic_in = [asdict(f) for f in pipe.out.get("pre_critic", [])]
    saved = json.loads((ROOT / committed).read_text(encoding="utf-8"))
    rows["full"] = score(saved, golden)
    replayed = json.loads(json.dumps(rep.to_dict(), ensure_ascii=False))
    drops = Counter((d["role"], d["reason"]) for d in rep.drops if d["role"] in FINDING_ROLES)
    return {
        "name": name, "rows": rows, "cached": len(rep.trace), "calls": calls,
        "pre_critic_ok": built == critic_in,
        "full_ok": same_findings(replayed["findings"], saved["findings"]),
        "quotes": {r: {k: pipe.quotes[r, k] for k in ("verbatim", "fixed", "missed")} for r in FINDING_ROLES},
        "dropped": sum(n for (_, reason), n in drops.items() if "цитат" in reason),
        "drops": drops,
    }


def render(results: list[dict]) -> str:
    out = ["# Абляция: что даёт каждый шаг", "",
           "**Самопроверка: на наших собственных разметках.** Эталоны `eval/golden*.toml` писали мы сами, "
           "поэтому это не независимая оценка.", "",
           f"Повтор закоммиченного кэша `.cache/llm` (`{PROVIDER}`, `{MODEL}`), без единого запроса к модели. "
           "Скрипт: `python -m eval.ablation`. Совпадения считает `eval/score.py` (автоматически, строка ±1 и "
           "ключевое слово), без ручной проверки.", "",
           "| Вариант | " + " | ".join(r["name"] for r in results) + " |",
           "| :--- | " + " | ".join(":---" for _ in results) + " |"]
    labels = [(k, label) for k, label, _ in VARIANTS] + [("full", "Полный (после Критика = закоммиченный report.json)")]
    for key, label in labels:
        out.append(f"| {label} | " + " | ".join(" / ".join(cells(r["rows"][key])) for r in results) + " |")
    b = BASELINE
    out.append(f"| Один промпт, без пайплайна ({b['model']}, {b['date']}) | "
               + " | ".join(" / ".join(b["rows"][r["name"]]) for r in results) + " |")
    out += ["", "В каждой ячейке: замечаний / найдено эталонных дефектов / найдено обязательных (must-find).", ""]
    out += ["## Какие эталоны добавляет или теряет каждый шаг", "",
            "| Шаг | " + " | ".join(r["name"] for r in results) + " |",
            "| :--- | " + " | ".join(":---" for _ in results) + " |"]
    for (prev, _), (key, label) in zip(labels, labels[1:]):
        out.append(f"| {label} | " + " | ".join(step_diff(r["rows"][prev], r["rows"][key]) for r in results) + " |")
    out.append("")
    out += ["## Проверка повтора", "",
            "| Документ | Ответов из кэша | Реальных запросов | Сборка до Критика = вход Критика | Полный = report.json |",
            "| :--- | :--- | :--- | :--- | :--- |"]
    for r in results:
        out.append(f"| {r['name']} | {r['cached']} | {r['calls']} | {'да' if r['pre_critic_ok'] else 'НЕТ'} | "
                   f"{'да' if r['full_ok'] else 'НЕТ'} |")
    out += ["", "## Защита цитат", "",
            "Каждая цитата модели ищется в документе. «Дословно»: найдена, текст оставлен. «Исправлена»: найдена "
            "приблизительно, текст заменён строкой документа. «Не найдена»: цитата выброшена; замечание без "
            "единой найденной цитаты выбрасывается целиком.", "",
            "| Документ | Роль | Дословно | Исправлена | Не найдена |", "| :--- | :--- | :--- | :--- | :--- |"]
    for r in results:
        for role in FINDING_ROLES:
            q = r["quotes"][role]
            out.append(f"| {r['name']} | {role} | {q['verbatim']} | {q['fixed']} | {q['missed']} |")
    out += [""] + [f"- {r['name']}: выброшено замечаний без цитаты: {r['dropped']}." for r in results]
    out += ["", "## Оговорки", "",
            "- Варианты до Критика собраны функциями пайплайна (`attach_reqs`, `dedupe`, `tag_assumptions`) из "
            "ответов ролей в кэше. Критик на них не запускался: это потребовало бы новых запросов.",
            "- EdgeCaser получает на вход замечания правил, Auditor и CrossChecker, поэтому без них его ответ "
            "был бы другим. Ряды - срезы одного прогона, не отдельные прогоны. Отключить Критика или защиту цитат "
            "без новых запросов нельзя, поэтому таких рядов нет.",
            "- Число замечаний до Критика включает дубли и ложные срабатывания (точность здесь не считалась); "
            "сравнимы по числу замечаний только ряды «Полный» и «один промпт».",
            "- Критик сливает похожие замечания. От слитого замечания в целевое переходят только текст проблемы и "
            "цитаты с новых строк, поэтому эталон, найденный только им, может перестать совпадать автоматически.",
            "- «Полный» считается по закоммиченному report.json, вопросы автору в полноту не входят (как в "
            "`eval/score.py`).",
            f"- Ряд «один промпт» скопирован из `{b['source']}` ({b['date']}); там отчёты пайплайна v1.3, здесь v1.4. "
            "Числа в нём тоже от `eval/score.py`; при строгой проверке первый прогон на выданном ТЗ дал 36/40 и 13/13 "
            "обязательных. В ТЗ в скобках - второй прогон того же промпта.",
            "- Полностью слепого столбца нет. Промпт базовой линии написан после чтения эталона выданного ТЗ "
            "(`eval/golden.toml`) и подсказывает, где обычно бывают дефекты; эталоны autotopup и cashback до его "
            "прогона не читались. Но пайплайн v1.4 (роль WholeDoc, промпты, Критик) меняли уже после того, как были "
            "известны результаты прогонов на всех трёх документах, в том числе на cashback. На cashback один промпт "
            "пропустил 1 обязательный дефект; это одна разница на одном документе, вывода о преимуществе из неё "
            "мы не делаем.",
            ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ablation table from the committed LLM cache, no model calls.")
    ap.add_argument("--md", default=str(ROOT / "eval" / "ablation.md"))
    args = ap.parse_args(argv)
    results = [run_doc(*d) for d in DOCS]
    md = render(results)
    Path(args.md).write_text(md, encoding="utf-8")
    print(md)
    return 0 if all(r["pre_critic_ok"] and r["full_ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
