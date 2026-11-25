import datetime as dt
import re
import subprocess
import time
import tomllib
from pathlib import Path

from . import __version__, roles
from .ground import Grounder
from .lint import lint
from .llm import LLM, LLMError
from .model import SEVERITIES, ChecklistRow, Diagnostic, Finding, Question, Report, Requirement
from .reader import Document, ReadError, read_document
from .segment import Candidate, clean, extract_candidates, render_candidates

ROOT = Path(__file__).resolve().parent.parent
AUDIT_BATCH = 22
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
REQ_MARKERS = re.compile(r"должн|требовани|обязан|систем|сервис|пользовател|клиент|приложени|\bapi\b|shall|must|"
                         r"requirement|функциональн|интеграц|запрос|ответ", re.I)


def load_criteria() -> dict:
    with open(ROOT / "criteria.toml", "rb") as f:
        return tomllib.load(f)


def agent_version() -> str:
    try:
        desc = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{__version__} ({desc})" if desc else __version__
    except Exception:
        return __version__


def all_criteria(cr: dict) -> dict:
    out = {}
    for group in ("single", "set", "srs"):
        for c in cr[group]:
            out[c["id"]] = c
    return out


class Pipeline:
    def __init__(self, llm: LLM, log=print):
        self.llm = llm
        self.llm_obj = llm
        self.log = log
        self.cr = load_criteria()
        self.crit = all_criteria(self.cr)
        self.drops: list[dict] = []

    def step(self, name: str, msg: str):
        self.log(f"[{name}] {msg}")

    def run(self, path: str) -> Report:
        t0 = time.time()
        passport = {"document": Path(path).name, "sha256": "", "date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "model": self.llm.model or "-", "provider": self.llm.provider, "agent_version": agent_version(),
                    "llm_calls": 0, "seconds": 0, "standards": "ISO/IEC/IEEE 29148:2018 п. 5.2.5-5.2.7; IEEE 830-1998 п. 4.3"}
        rep = Report(passport=passport)
        try:
            self.step("Reader", f"читаю {Path(path).name}")
            doc = read_document(path)
        except ReadError as e:
            rep.diagnostics.append(Diagnostic("error", e.code, e.message, e.hint))
            rep.verdict = {"status": "Нет", "text": "Проверка не выполнена: документ не удалось прочитать.", "fix_first": []}
            return self._finish(rep, t0)
        passport["sha256"] = doc.sha256
        passport["format"] = doc.kind
        passport["lines"] = len(doc.lines)
        for w in doc.warnings:
            rep.diagnostics.append(Diagnostic("warning", "reader", w))
        self.doc = doc
        self.g = Grounder(doc)
        numbered = doc.numbered()

        markers = len(REQ_MARKERS.findall(doc.text))
        if markers < max(3, len(doc.lines) // 40):
            rep.diagnostics.append(Diagnostic("error", "not_requirements",
                                              f"Документ не похож на требования: почти нет признаков ТЗ (найдено {markers}).",
                                              "Проверьте, что передан нужный файл. Проверка не выполнялась."))
            rep.verdict = {"status": "Нет", "text": "Документ не является документом с требованиями.", "fix_first": []}
            return self._finish(rep, t0)

        cands = extract_candidates(doc)
        self.step("Segmenter", f"фрагментов: {len(cands)}")
        try:
            self.llm.check()
        except LLMError as e:
            rep.diagnostics.append(Diagnostic("error", e.code, e.message, e.hint))
            self.llm = None
        reqs = self.segment(cands, rep)
        rep.requirements = reqs
        self.step("Segmenter", f"требований: {len(reqs)}")

        findings = lint(doc, self.cr)
        self.step("Linter", f"замечаний по правилам: {len(findings)}")

        if self.llm is not None and reqs:
            findings += self.audit(numbered, reqs, rep)
            findings += self.cross(numbered, reqs, findings, rep)
        self.attach_reqs(findings, reqs)
        findings = self.dedupe(findings)
        for i, f in enumerate(findings, start=1):
            f.id = f"F-{i:02d}"

        fix_first = []
        if self.llm is not None and findings:
            findings, fix_first = self.critic(numbered, findings, rep)
        findings.sort(key=lambda f: (SEV_RANK.get(f.severity, 3), f.quotes[0].start if f.quotes else 0))
        renum = {}
        for i, f in enumerate(findings, start=1):
            renum[f.id] = f"D-{i:02d}"
            f.id = renum[f.id]
        fix_first = [renum[x] for x in fix_first if x in renum]
        rep.findings = findings

        if self.llm is not None and findings:
            rep.questions = self.clarify(numbered, findings, rep)
        elif findings:
            rep.questions = self.fallback_questions(findings)
        rep.verdict = self.verdict(findings, fix_first, reqs)
        if self.drops:
            passport["guard_drops"] = len(self.drops)
        rep.drops = self.drops
        return self._finish(rep, t0)

    def _finish(self, rep: Report, t0: float) -> Report:
        rep.passport["seconds"] = round(time.time() - t0, 1)
        tr = self.llm_obj.trace
        rep.trace = tr
        rep.passport["llm_calls"] = sum(1 for t in tr if not t["cached"])
        rep.passport["llm_cached"] = sum(1 for t in tr if t["cached"])
        return rep

    def _llm(self, role: str, system: str, user: str, rep: Report):
        try:
            self.step(role, "запрос к модели")
            data = self.llm.json(role, system, user)
            if not isinstance(data, dict):
                rep.diagnostics.append(Diagnostic("warning", "bad_shape", f"{role}: ответ модели не в ожидаемом формате.",
                                                  "Шаг пропущен, остальные роли работают."))
                return None
            return data
        except LLMError as e:
            rep.diagnostics.append(Diagnostic("error", e.code, f"{role}: {e.message}", e.hint))
            if e.code in ("no_key", "auth", "quota_day", "bad_request", "no_model"):
                self.llm = None
            return None

    def segment(self, cands: list[Candidate], rep: Report) -> list[Requirement]:
        by_id = {c.id: c for c in cands}
        data = None
        if self.llm is not None:
            system, user = roles.segmenter_prompt(self.cr, render_candidates(cands))
            data = self._llm("Segmenter", system, user, rep)
        items = []
        if isinstance(data, dict) and isinstance(data.get("requirements"), list):
            if data.get("doc_title"):
                rep.passport["doc_title"] = str(data["doc_title"])[:200]
            if data.get("is_requirements_doc") is False:
                rep.diagnostics.append(Diagnostic("error", "not_requirements",
                                                  "Модель считает, что документ не является документом с требованиями.",
                                                  "Проверьте, что передан нужный файл."))
            used = set()
            for r in data["requirements"]:
                ids = [c for c in r.get("candidates", []) if c in by_id and c not in used]
                if not ids:
                    self.drops.append({"role": "Segmenter", "reason": "нет валидных фрагментов", "item": str(r)[:200]})
                    continue
                used.update(ids)
                items.append((ids, r.get("type", ""), str(r.get("doc_id", "") or ""), str(r.get("short", "") or "")))
        else:
            if self.llm is not None or not rep.diagnostics:
                rep.diagnostics.append(Diagnostic("warning", "segment_fallback",
                                                  "Требования выделены эвристикой без модели.", ""))
            for c in cands:
                if c.kind in ("bullet", "para", "table_row") and not self._is_meta(c):
                    items.append(([c.id], "", c.doc_id, clean(c.text)[:90]))
        reqs = []
        for n, (ids, typ, doc_id, short) in enumerate(items, start=1):
            cs = [by_id[i] for i in ids]
            start, end = min(c.start for c in cs), max(c.end for c in cs)
            q = self.g.quote_lines(start, end)
            if not doc_id:
                doc_id = next((c.doc_id for c in cs if c.doc_id), "")
            if doc_id and not re.search(re.escape(doc_id), q.text):
                doc_id = ""
            reqs.append(Requirement(id=f"R-{n:02d}", doc_id=doc_id, type=typ, short=short,
                                    section=cs[0].section, quote=q, candidate_ids=ids))
        return reqs

    def _is_meta(self, c: Candidate) -> bool:
        low = (c.section + " " + c.context).lower()
        return any(w in low for w in ("общие сведения", "ревью", "согласу", "общие параметры")) or "да / нет" in c.text.lower()

    def req_table(self, reqs: list[Requirement]) -> str:
        return "\n".join(f"{r.id} [{r.type or '-'}; {r.doc_id or 'без id'}; строки {r.quote.start}-{r.quote.end}; "
                         f"{r.section}]: {clean(r.quote.text)[:600]}" for r in reqs)

    def _ground_quotes(self, raw_quotes, hint=None):
        out = []
        for q in raw_quotes:
            if not isinstance(q, str) or not q.strip():
                continue
            gq = self.g.locate(q, hint)
            if gq:
                out.append(gq)
        return out

    def _mk(self, d: dict, scope: str, role: str, req_ids: list[str], hint=None) -> Finding | None:
        crit = str(d.get("criterion", "")).strip()
        if crit not in self.crit:
            self.drops.append({"role": role, "reason": f"неизвестный критерий {crit}", "item": str(d.get("problem", ""))[:160]})
            return None
        raw = d.get("quotes") or ([d.get("quote")] if d.get("quote") else [])
        quotes = self._ground_quotes(raw, hint)
        if not quotes:
            self.drops.append({"role": role, "reason": "цитата не найдена в документе", "item": str(raw)[:200]})
            return None
        if scope == "set" and crit == "set_consistent" and len({q.start for q in quotes}) < 2 and len(raw) >= 2:
            self.drops.append({"role": role, "reason": "противоречие без второй найденной цитаты", "item": str(raw)[:200]})
            return None
        sev = d.get("severity") if d.get("severity") in SEVERITIES else "важно"
        problem = str(d.get("problem", "")).strip()
        if len(problem) < 15:
            self.drops.append({"role": role, "reason": "пустое описание", "item": problem})
            return None
        return Finding(id="", scope=scope, req_ids=req_ids, criterion=crit, severity=sev, quotes=quotes,
                       problem=problem, impact=str(d.get("impact", "")).strip(), fix=str(d.get("fix", "")).strip(),
                       test_hint=str(d.get("test_hint", "")).strip(), role=role)

    def audit(self, numbered: str, reqs: list[Requirement], rep: Report) -> list[Finding]:
        out = []
        by_id = {r.id: r for r in reqs}
        for b in range(0, len(reqs), AUDIT_BATCH):
            batch = reqs[b:b + AUDIT_BATCH]
            system, user = roles.auditor_prompt(self.cr, numbered, self.req_table(batch))
            data = self._llm("Auditor", system, user, rep)
            if not isinstance(data, dict):
                if self.llm is None:
                    break
                continue
            for res in data.get("results", []) or []:
                rid = res.get("req_id")
                if rid not in by_id:
                    continue
                r = by_id[rid]
                r_fail = [c for c in res.get("fail", []) or [] if c in self.crit]
                rep.req_checks[rid] = r_fail
                for d in res.get("findings", []) or []:
                    f = self._mk(d, "req", "Auditor", [rid], r.quote.start)
                    if f:
                        out.append(f)
        self.step("Auditor", f"замечаний: {len(out)}")
        return out

    def cross(self, numbered: str, reqs: list[Requirement], known: list[Finding], rep: Report) -> list[Finding]:
        has_checklist = "да / нет" in self.doc.text.lower() or "чек-лист" in self.doc.text.lower()
        known_s = "\n".join(f"- {f.problem} ({f.quotes[0].loc})" for f in known) or "- нет"
        system, user = roles.cross_prompt(self.cr, numbered, self.req_table(reqs), known_s, has_checklist)
        data = self._llm("CrossChecker", system, user, rep)
        out = []
        if not isinstance(data, dict):
            return out
        raw = list(data.get("findings", []) or [])
        for st in data.get("steps", []) or []:
            if isinstance(st, dict):
                raw += [d for d in st.get("findings", []) or [] if isinstance(d, dict)]
        for d in raw:
            f = self._mk(d, "set", "CrossChecker", [])
            if f:
                out.append(f)
        for s in data.get("set_summary", []) or []:
            if s.get("criterion") in self.crit:
                rep.set_summary.append({"criterion": s["criterion"], "status": str(s.get("status", "")),
                                        "comment": str(s.get("comment", ""))})
        for c in data.get("checklist", []) or []:
            if c.get("item"):
                rep.checklist.append(ChecklistRow(item=str(c["item"]), value=str(c.get("value", "")),
                                                  evidence=str(c.get("evidence", ""))))
        self.step("CrossChecker", f"замечаний: {len(out)}")
        return out

    def attach_reqs(self, findings: list[Finding], reqs: list[Requirement]) -> None:
        for f in findings:
            if f.req_ids:
                continue
            ids = []
            for q in f.quotes:
                for r in reqs:
                    if r.quote.start <= q.end and q.start <= r.quote.end and r.id not in ids:
                        ids.append(r.id)
            f.req_ids = ids

    def dedupe(self, findings: list[Finding]) -> list[Finding]:
        out: list[Finding] = []
        for f in findings:
            key = (f.criterion, tuple(sorted(q.start for q in f.quotes)))
            if any((o.criterion, tuple(sorted(q.start for q in o.quotes))) == key for o in out):
                self.drops.append({"role": "Guard", "reason": "дубликат", "item": f.problem[:160]})
                continue
            out.append(f)
        return out

    def finding_table(self, findings: list[Finding]) -> str:
        return "\n".join(f"{f.id} [{f.role}; {f.criterion}; {f.severity}; {', '.join(q.loc for q in f.quotes)}] "
                         f"{f.problem} | цитата: «{clean(f.quotes[0].text)[:200]}»" for f in findings)

    def critic(self, numbered: str, findings: list[Finding], rep: Report):
        system, user = roles.critic_prompt(self.cr, numbered, self.finding_table(findings))
        data = self._llm("Critic", system, user, rep)
        if not isinstance(data, dict):
            return findings, []
        by_id = {f.id: f for f in findings}
        drop = set()
        for d in data.get("decisions", []) or []:
            fid = d.get("id")
            if fid not in by_id:
                continue
            act = d.get("action")
            if act == "drop":
                drop.add(fid)
                self.drops.append({"role": "Critic", "reason": str(d.get("reason", ""))[:200], "item": by_id[fid].problem[:160]})
            elif act == "merge" and d.get("into") in by_id and d.get("into") != fid:
                drop.add(fid)
                tgt = by_id[d["into"]]
                for q in by_id[fid].quotes:
                    if all(q.start != x.start for x in tgt.quotes):
                        tgt.quotes.append(q)
                for r in by_id[fid].req_ids:
                    if r not in tgt.req_ids:
                        tgt.req_ids.append(r)
                self.drops.append({"role": "Critic", "reason": f"объединено с {d['into']}", "item": by_id[fid].problem[:160]})
            if fid not in drop and d.get("severity") in SEVERITIES:
                by_id[fid].severity = d["severity"]
        kept = [f for f in findings if f.id not in drop]
        fix_first = [x for x in data.get("fix_first", []) or [] if x in by_id and x not in drop]
        self.step("Critic", f"оставлено {len(kept)} из {len(findings)}")
        return kept, fix_first

    def clarify(self, numbered: str, findings: list[Finding], rep: Report) -> list[Question]:
        system, user = roles.clarifier_prompt(self.cr, numbered, self.finding_table(findings))
        data = self._llm("Clarifier", system, user, rep)
        if not isinstance(data, dict):
            return self.fallback_questions(findings)
        ids = {f.id for f in findings}
        out = []
        for q in data.get("questions", []) or []:
            text = str(q.get("text", "")).strip()
            if len(text) < 15:
                continue
            ans = str(q.get("answered_in_doc", "") or "").strip()
            if ans and self.g.locate(ans):
                self.drops.append({"role": "Clarifier", "reason": "ответ уже есть в документе", "item": text[:160]})
                continue
            quotes = self._ground_quotes(q.get("quotes") or [])
            if not quotes:
                self.drops.append({"role": "Clarifier", "reason": "вопрос без найденной цитаты", "item": text[:160]})
                continue
            out.append(Question(id=f"Q-{len(out) + 1:02d}", text=text, quotes=quotes, blocks=str(q.get("blocks", "")),
                                options=[str(o) for o in (q.get("options") or [])][:4], default=str(q.get("default", "")),
                                addressee=str(q.get("addressee", "")),
                                finding_ids=[x for x in (q.get("finding_ids") or []) if x in ids]))
        self.step("Clarifier", f"вопросов: {len(out)}")
        return out[:14]

    def fallback_questions(self, findings: list[Finding]) -> list[Question]:
        out = []
        for f in [f for f in findings if f.severity != "мелочь"][:10]:
            out.append(Question(id=f"Q-{len(out) + 1:02d}", text=f"{f.problem} Как должно быть?", quotes=f.quotes[:2],
                                blocks=f.impact, options=[], default=f.fix, addressee="аналитик", finding_ids=[f.id]))
        return out

    def verdict(self, findings: list[Finding], fix_first: list[str], reqs: list[Requirement]) -> dict:
        crit = [f for f in findings if f.severity == "критично"]
        major = [f for f in findings if f.severity == "важно"]
        if not fix_first:
            fix_first = [f.id for f in (crit + major)[:7]]
        if not reqs:
            return {"status": "Нет", "text": "В документе не выделено ни одного требования.", "fix_first": []}
        if crit:
            return {"status": "Нет", "fix_first": fix_first,
                    "text": f"Начинать разработку и тестирование нельзя: {len(crit)} критичных дефектов "
                            f"(противоречия, непроверяемые или неполные требования). Сначала исправить их и ответить на уточняющие вопросы."}
        if len(major) > 5:
            return {"status": "С оговорками", "fix_first": fix_first,
                    "text": f"Можно начинать с оговорками: критичных дефектов нет, но {len(major)} важных замечаний заставят команду додумывать."}
        return {"status": "Да", "fix_first": fix_first, "text": "Документ пригоден для начала разработки и тестирования."}
