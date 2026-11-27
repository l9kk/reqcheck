import re

CAND_RE = re.compile(r"^(C\d{3}) \[(\w+), строка \d+\][^:]*: (.*)$", re.M)
REQ_RE = re.compile(r"^(R-\d+) \[[^\]]*\]: (.*)$", re.M)
DOC_LINE_RE = re.compile(r"^\s*(\d+)\| (.*)$", re.M)
FINDING_RE = re.compile(r"^(F-\d+|D-\d+) \[[^\]]*\] (.*?) \| цитата: «(.*)»$", re.M)


def words(text: str, n: int = 8) -> str:
    return " ".join(text.split()[:n])


class FakeLLM:
    """Stands in for reqcheck.llm.LLM: small schema-valid answers per role, built from the prompt."""

    provider = "fake"
    model = "fake"

    def __init__(self, use_cache: bool = True, cache_dir: str = ""):
        self.trace: list[dict] = []

    def json(self, role: str, system: str, user: str):
        self.trace.append({"role": role, "cached": False, "seconds": 0.0, "in_tokens": len(system + user) // 4,
                           "out_tokens": 0})
        return getattr(self, role.lower())(user)

    def segmenter(self, user: str) -> dict:
        reqs = [{"candidates": [cid], "type": "functional", "doc_id": "", "short": words(text, 6)}
                for cid, kind, text in CAND_RE.findall(user) if kind in ("bullet", "para", "table_row")]
        return {"doc_title": "Тестовый документ", "is_requirements_doc": True, "requirements": reqs}

    def auditor(self, user: str) -> dict:
        results = []
        for rid, text in REQ_RE.findall(user.split("Требования для проверки:")[-1]):
            if not results and len(text.split()) >= 8 and "|" not in text:
                results.append({"req_id": rid, "fail": ["verifiable"], "findings": [
                    {"criterion": "verifiable", "severity": "важно", "quote": words(text),
                     "problem": "Не задан измеримый критерий выполнения требования.",
                     "impact": "Тестировщик не знает ожидаемый результат.", "fix": "Указать число и единицу.",
                     "test_hint": "Граничное значение и значение за границей."}]})
            else:
                results.append({"req_id": rid, "fail": [], "findings": []})
        return {"results": results}

    def crosschecker(self, user: str) -> dict:
        reqs = [t for _, t in REQ_RE.findall(user.split("Требования (id и строки):")[-1]) if "|" not in t]
        finding = {"criterion": "set_complete", "severity": "важно", "quotes": [words(reqs[-1])],
                   "problem": "Не описано поведение при недоступности смежной системы.",
                   "impact": "Нельзя написать негативный тест.", "fix": "Описать таймаут и повтор.", "test_hint": ""}
        return {"steps": [{"step": "6", "checked": "Интеграция.", "findings": [finding] if reqs else []}],
                "set_summary": [{"criterion": "set_complete", "status": "partial", "comment": "Есть пропуски."}],
                "checklist": []}

    def critic(self, user: str) -> dict:
        ids = [fid for fid, _, _ in FINDING_RE.findall(user)]
        return {"decisions": [{"id": fid, "action": "keep", "into": "", "severity": "", "reason": "Верно."}
                              for fid in ids], "fix_first": ids[:1]}

    def clarifier(self, user: str) -> dict:
        qs = [{"text": f"Вопрос {n} к автору: как исправить «{words(problem, 5)}»?", "quotes": [words(quote)],
               "blocks": "Тест-кейс.", "options": ["Вариант A", "Вариант B"], "default": f"Вариант A для {fid}",
               "addressee": "аналитик", "finding_ids": [fid], "answered_in_doc": ""}
              for n, (fid, problem, quote) in enumerate(FINDING_RE.findall(user)[:4], start=1)]
        return {"questions": qs}

    def wholedoc(self, user: str) -> dict:
        for no, text in DOC_LINE_RE.findall(user):
            if len(text.split()) >= 8 and "|" not in text:
                return {"findings": [{"criterion": "srs_ranked", "severity": "мелочь",
                                      "quotes": [{"start": int(no), "end": int(no), "text": words(text)}],
                                      "problem": "У требований нет приоритета и признака стабильности.",
                                      "impact": "Непонятно, что делать первым.", "fix": "Добавить приоритет."}]}
        return {"findings": []}

    def edgecaser(self, user: str) -> dict:
        return {"findings": []}

    def rewriter(self, user: str) -> dict:
        items = []
        for qid, body in re.findall(r"^(Q-\d+)\. (.*?)(?=^Q-\d+\. |\Z)", user, re.M | re.S):
            reqs = re.findall(r"^\s+(R-\d+): ", body, re.M)
            items.append({"q_id": qid, "rewrites": [{"req_id": r, "requirement": f"Уточнено по {qid}: правило {r}.",
                                                     "acceptance": []} for r in reqs[:1]]})
        return {"items": items}

    def delta(self, user: str) -> dict:
        old = re.findall(r"^(D-\d+) \[[^\]]*связано с ответом", user, re.M)
        return {"old": [{"id": i, "status": "closed", "reason": "Снято."} for i in old], "new": []}
