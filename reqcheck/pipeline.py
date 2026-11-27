import datetime as dt
import os
import re
import subprocess
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
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
                         r"requirement|функциональн|интеграц|запрос|ответ|"
                         r"талап|талаб|жүйе|қажет|тиіс|керек|міндетт|пайдаланушы|сұраныс|жауап", re.I)
ASSUME_TAG = "[предложение, согласовать]"
NUM_RE = re.compile(r"(?<!\w)(?<![^\W\d_]-)(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+(?:[.,]\d+)?)(?!\d)")


def numbers(text: str) -> set[str]:
    out = set()
    for m in NUM_RE.findall(text):
        n = re.sub(r"[ \u00a0\u202f]", "", m).replace(",", ".")
        whole, _, frac = n.partition(".")
        out.add((whole.lstrip("0") or "0") + ("." + frac if frac else ""))
    return out


TAG_VARIANT_RE = re.compile(r"\[\s*([^\[\]]*?)[\s,;:.—–-]*\b(?:согласовать|уточнить|согласовани[еяю]|уточнени[еяю]|"
                            r"требу(?:ет|ется)\s+(?:уточнени|согласовани)[яе])\s*\]", re.I)
TAG_GENERIC = {"значение", "значения", "правило", "предложение", "число", "требует", "требуется", "нужно",
               "необходимо", "надо", "на"}
DOUBLE_TAG_RE = re.compile(rf"{re.escape(ASSUME_TAG)}(?:[\s,;]*{re.escape(ASSUME_TAG)})+")
DOT_ORDINAL_RE = re.compile(r"(?:^[ \t]*|(?<=[.;!?] ))\d{1,2}\.(?=\s)", re.M)
PAREN_ORDINAL_RE = re.compile(r"(?:^|(?<=[\s:;]))\d{1,2}\)")


def normalize_tags(text: str) -> str:
    def canon(m):
        x = m.group(1).strip(" ,;:.—–-")
        if not x or all(w in TAG_GENERIC for w in x.lower().split()):
            return ASSUME_TAG
        return f"{x} {ASSUME_TAG}"
    return DOUBLE_TAG_RE.sub(ASSUME_TAG, TAG_VARIANT_RE.sub(canon, text))


def strip_ordinals(text: str) -> str:
    text = DOT_ORDINAL_RE.sub(" ", text)
    return PAREN_ORDINAL_RE.sub(lambda m: m.group(0) if text[:m.start()].count("(") > text[:m.start()].count(")")
                                else " ", text)


def tag_assumptions(findings: list[Finding], doc_text: str) -> None:
    known = numbers(doc_text)
    for f in findings:
        if not f.fix:
            continue
        f.fix = normalize_tags(f.fix)
        if ASSUME_TAG not in f.fix and numbers(strip_ordinals(f.fix)) - known:
            f.fix = f"{f.fix.rstrip()} {ASSUME_TAG}"


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


def default_workers() -> int:
    try:
        return max(1, int(os.getenv("REQCHECK_WORKERS", "3")))
    except ValueError:
        return 3


ROLE_ORDER = ("Segmenter", "Auditor", "CrossChecker", "EdgeCaser", "WholeDoc", "Critic", "Clarifier")


def all_criteria(cr: dict) -> dict:
    out = {}
    for group in ("single", "set", "srs"):
        for c in cr[group]:
            out[c["id"]] = c
    return out


class Pipeline:
    def __init__(self, llm: LLM, log=print, wholedoc: bool = True, workers: int | None = None):
        self.llm = llm
        self.wholedoc = wholedoc
        self.workers = default_workers() if workers is None else max(1, int(workers))
        self.use_model = True
        self.log = log
        self._local = threading.local()
        self._log_lock = threading.Lock()
        self.cr = load_criteria()
        self.crit = all_criteria(self.cr)
        self.drops: list[dict] = []
        self.merged: dict[str, list[str]] = {}
        self.merge_into: dict[str, str] = {}

    @property
    def drops(self) -> list[dict]:
        return getattr(self._local, "drops", self._drops)

    @drops.setter
    def drops(self, value: list[dict]) -> None:
        self._drops = value

    def step(self, name: str, msg: str):
        with self._log_lock:
            self.log(f"[{name}] {msg}")

    def _parallel(self, tasks: list, rep: Report) -> list:
        """Run tasks (each takes a Report) in a thread pool. Each task writes diagnostics, checks and drops into
        its own buffers; they are merged in task order, so the result does not depend on timing."""
        subs = [Report(passport=rep.passport) for _ in tasks]
        drops: list[list[dict]] = [[] for _ in tasks]

        def call(i):
            self._local.drops = drops[i]
            try:
                return tasks[i](subs[i])
            finally:
                del self._local.drops

        if self.workers <= 1 or len(tasks) <= 1:
            results = [call(i) for i in range(len(tasks))]
        else:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(tasks))) as ex:
                results = list(ex.map(call, range(len(tasks))))
        for sub, dr in zip(subs, drops):
            for d in sub.diagnostics:
                if all((d.level, d.code, d.message) != (x.level, x.code, x.message) for x in rep.diagnostics):
                    rep.diagnostics.append(d)
            rep.req_checks.update(sub.req_checks)
            rep.set_summary += sub.set_summary
            rep.checklist += sub.checklist
            self.drops += dr
        return results

    def _bad(self, role: str, item) -> None:
        self.drops.append({"role": role, "reason": "неверный формат элемента", "item": str(item)[:200]})

    def _dicts(self, items, role: str, record: bool = True) -> list[dict]:
        if not isinstance(items, list):
            if items and record:
                self._bad(role, items)
            return []
        out = []
        for x in items:
            if isinstance(x, dict):
                out.append(x)
            elif record:
                self._bad(role, x)
        return out

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
            rep.verdict = {"status": "Не проверено", "text": "Проверка не выполнена: документ не удалось прочитать.", "fix_first": []}
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
            rep.verdict = {"status": "Не проверено", "text": "Документ не является документом с требованиями.", "fix_first": []}
            return self._finish(rep, t0)

        cands = extract_candidates(doc)
        self.step("Segmenter", f"фрагментов: {len(cands)}")
        reqs = self.segment(cands, rep)
        rep.requirements = reqs
        self.step("Segmenter", f"требований: {len(reqs)}")
        if not reqs and any(d.code == "not_requirements" for d in rep.diagnostics):
            rep.verdict = {"status": "Не проверено", "text": "Документ не является документом с требованиями.", "fix_first": []}
            return self._finish(rep, t0)

        findings = lint(doc, self.cr)
        self.step("Linter", f"замечаний по правилам: {len(findings)}")

        if self.use_model and reqs:
            findings += self.audit(numbered, reqs, rep)
            if self.use_model:
                findings += self.stage2(numbered, reqs, findings, rep)
        self.attach_reqs(findings, reqs)
        findings = self.dedupe(findings)
        for i, f in enumerate(findings, start=1):
            f.id = f"F-{i:02d}"

        fix_first = []
        if self.use_model and findings:
            findings, fix_first = self.critic(numbered, findings, rep)
        tag_assumptions(findings, doc.text)
        findings.sort(key=lambda f: (SEV_RANK.get(f.severity, 3), f.quotes[0].start if f.quotes else 0))
        renum = {}
        for i, f in enumerate(findings, start=1):
            renum[f.id] = f"D-{i:02d}"
            f.id = renum[f.id]
        fix_first = [renum[x] for x in fix_first if x in renum]
        for d in self.drops:
            if d.get("into"):
                d["reason"] = f"объединено с {renum.get(d.pop('into'), 'другим замечанием')}"
        rep.findings = findings
        rep.req_checks = {r: [f.criterion for f in findings if r in f.req_ids and f.scope == "req"]
                          for r in rep.req_checks}

        if self.use_model and findings:
            rep.questions = self.clarify(numbered, findings, rep)
        elif findings:
            rep.questions = self.fallback_questions(findings)
        rep.questions = self.rank_questions(rep.questions, findings)
        self.add_merged_text(findings, renum)
        rep.verdict = self.verdict(findings, fix_first, reqs, model_used=self.use_model)
        if self.drops:
            passport["guard_drops"] = len(self.drops)
        rep.drops = self.drops
        return self._finish(rep, t0)

    def _finish(self, rep: Report, t0: float) -> Report:
        rep.passport["seconds"] = round(time.time() - t0, 1)
        rank = {r: i for i, r in enumerate(ROLE_ORDER)}
        tr = self.llm.trace
        tr.sort(key=lambda t: rank.get(t.get("role"), len(rank)))
        rep.trace = tr
        rep.passport["llm_calls"] = sum(1 for t in tr if not t["cached"])
        rep.passport["llm_cached"] = sum(1 for t in tr if t["cached"])
        orig = [t.get("orig_seconds") if t["cached"] else t["seconds"] for t in tr]
        if tr and rep.passport["llm_cached"] and all(isinstance(x, (int, float)) for x in orig):
            rep.passport["llm_seconds_uncached"] = round(sum(orig), 1)
        return rep

    def _llm(self, role: str, system: str, user: str, rep: Report):
        try:
            self.step(role, "запрос к модели")
            data = self.llm.json(role, system, user)
            err = roles.shape_error(role, data)
            if err:
                self.step(role, f"формат ответа: {err}, повторяю")
                data = self.llm.json(role, system, user + roles.shape_note(err))
                err = roles.shape_error(role, data)
            if err:
                rep.diagnostics.append(Diagnostic("warning", "bad_shape", f"{role}: ответ модели не в ожидаемом формате ({err}).",
                                                  "Шаг пропущен, остальные роли работают."))
                return None
            return data
        except LLMError as e:
            rep.diagnostics.append(Diagnostic("error", e.code, f"{role}: {e.message}", e.hint))
            if e.code in ("no_key", "auth", "quota_day", "billing", "bad_request", "no_model"):
                self.use_model = False
            return None

    def segment(self, cands: list[Candidate], rep: Report) -> list[Requirement]:
        by_id = {c.id: c for c in cands}
        data = None
        if self.use_model:
            system, user = roles.segmenter_prompt(self.cr, render_candidates(cands))
            data = self._llm("Segmenter", system, user, rep)
        items = []
        if isinstance(data, dict) and isinstance(data.get("requirements"), list):
            if data.get("doc_title"):
                rep.passport["doc_title"] = str(data["doc_title"])[:200]
            if data.get("is_requirements_doc") is False:
                rep.diagnostics.append(Diagnostic("error", "not_requirements",
                                                  "Модель считает, что документ не является документом с требованиями.",
                                                  "Модель может ошибаться: проверьте, что передан нужный файл."))
            used = set()
            for r in self._dicts(data["requirements"], "Segmenter"):
                cand = r.get("candidates")
                ids = [c for c in (cand if isinstance(cand, list) else [])
                       if isinstance(c, str) and c in by_id and c not in used]
                if not ids:
                    self.drops.append({"role": "Segmenter", "reason": "нет валидных фрагментов", "item": str(r)[:200]})
                    continue
                used.update(ids)
                items.append((ids, str(r.get("type", "") or ""), str(r.get("doc_id", "") or ""), str(r.get("short", "") or "")))
        else:
            if self.use_model or not rep.diagnostics:
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
        return any(w in low for w in ("общие сведения", "ревью", "согласу")) or "да / нет" in c.text.lower()

    def req_table(self, reqs: list[Requirement]) -> str:
        return "\n".join(f"{r.id} [{r.type or '-'}; {r.doc_id or 'без id'}; строки {r.quote.start}-{r.quote.end}; "
                         f"{r.section}]: {clean(r.quote.text)[:600]}" for r in reqs)

    def _ground_quotes(self, raw_quotes, hint=None):
        if isinstance(raw_quotes, str):
            raw_quotes = [raw_quotes]
        if not isinstance(raw_quotes, list):
            return []
        out = []
        for q in raw_quotes:
            if not isinstance(q, str) or not q.strip():
                continue
            gq = self.g.locate(q, hint)
            if gq:
                out.append(gq)
        return out

    def _mk(self, d: dict, scope: str, role: str, req_ids: list[str], hint=None, ground=None) -> Finding | None:
        crit = str(d.get("criterion", "")).strip()
        if crit not in self.crit:
            self.drops.append({"role": role, "reason": f"неизвестный критерий {crit}", "item": str(d.get("problem", ""))[:160]})
            return None
        raw = d.get("quotes") or d.get("quote") or []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raw = []
        quotes = (ground or self._ground_quotes)(raw, hint)
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
        batches = [reqs[b:b + AUDIT_BATCH] for b in range(0, len(reqs), AUDIT_BATCH)]
        by_id = {r.id: r for r in reqs}
        parts = self._parallel([lambda r, b=b: self.audit_batch(numbered, b, by_id, r) for b in batches], rep)
        out = [f for part in parts for f in part]
        self.step("Auditor", f"замечаний: {len(out)}")
        return out

    def audit_batch(self, numbered: str, batch: list[Requirement], by_id: dict, rep: Report) -> list[Finding]:
        out = []
        if not self.use_model:
            return out
        system, user = roles.auditor_prompt(self.cr, numbered, self.req_table(batch))
        data = self._llm("Auditor", system, user, rep)
        if not isinstance(data, dict):
            return out
        for res in self._dicts(data.get("results"), "Auditor"):
            rid = res.get("req_id")
            if not isinstance(rid, str):
                self._bad("Auditor", res)
                continue
            if rid not in by_id:
                continue
            r = by_id[rid]
            fail = res.get("fail")
            r_fail = [c for c in fail if isinstance(c, str) and c in self.crit] if isinstance(fail, list) else []
            rep.req_checks[rid] = r_fail
            for d in self._dicts(res.get("findings"), "Auditor"):
                f = self._mk(d, "req", "Auditor", [rid], r.quote.start)
                if f:
                    out.append(f)
        return out

    def stage2(self, numbered: str, reqs: list[Requirement], known: list[Finding], rep: Report) -> list[Finding]:
        """CrossChecker then EdgeCaser in one lane, WholeDoc in a parallel lane. EdgeCaser waits for CrossChecker:
        it gets CrossChecker findings as known, and it must not be sent once the model is lost."""
        def set_lane(r):
            out = self.cross(numbered, reqs, known, r)
            if self.use_model:
                out += self.edge(numbered, reqs, known + out, r)
            return out

        lanes = [set_lane] + ([lambda r: self.whole(numbered, r)] if self.wholedoc else [])
        return [f for part in self._parallel(lanes, rep) for f in part]

    def cross(self, numbered: str, reqs: list[Requirement], known: list[Finding], rep: Report) -> list[Finding]:
        has_checklist = "да / нет" in self.doc.text.lower() or "чек-лист" in self.doc.text.lower()
        known_s = "\n".join(f"- {f.problem} ({f.quotes[0].loc})" for f in known) or "- нет"
        system, user = roles.cross_prompt(self.cr, numbered, self.req_table(reqs), known_s, has_checklist)
        data = self._llm("CrossChecker", system, user, rep)
        out = []
        if not isinstance(data, dict):
            return out
        raw = self._dicts(data.get("findings"), "CrossChecker")
        for st in self._dicts(data.get("steps"), "CrossChecker"):
            raw += self._dicts(st.get("findings"), "CrossChecker")
        for d in raw:
            f = self._mk(d, "set", "CrossChecker", [])
            if f:
                out.append(f)
        for s in self._dicts(data.get("set_summary"), "CrossChecker"):
            if isinstance(s.get("criterion"), str) and s["criterion"] in self.crit:
                rep.set_summary.append({"criterion": s["criterion"], "status": str(s.get("status", "")),
                                        "comment": str(s.get("comment", ""))})
        for c in self._dicts(data.get("checklist"), "CrossChecker"):
            if c.get("item"):
                rep.checklist.append(ChecklistRow(item=str(c["item"]), value=str(c.get("value", "")),
                                                  evidence=str(c.get("evidence", ""))))
        self.step("CrossChecker", f"замечаний: {len(out)}")
        return out

    def edge(self, numbered: str, reqs: list[Requirement], known: list[Finding], rep: Report) -> list[Finding]:
        known_s = "\n".join(f"- {f.problem} ({f.quotes[0].loc})" for f in known) or "- нет"
        system, user = roles.edge_prompt(self.cr, numbered, self.req_table(reqs), known_s)
        data = self._llm("EdgeCaser", system, user, rep)
        out = []
        if not isinstance(data, dict):
            return out
        edge_ids = {e["id"] for e in self.cr["edge"]}
        for d in self._dicts(data.get("findings"), "EdgeCaser", record=False):
            d = {**d, "criterion": "set_complete"}
            f = self._mk(d, "set", "EdgeCaser", [])
            if f:
                eid = str(d.get("edge", "")).strip()
                f.edge = eid if eid in edge_ids else ""
                out.append(f)
        self.step("EdgeCaser", f"замечаний: {len(out)}")
        return out

    def _ground_spans(self, raw, hint=None):
        out = []
        for q in raw:
            if isinstance(q, dict):
                start = q.get("start")
                q, h = q.get("text"), start if isinstance(start, int) and not isinstance(start, bool) else hint
            else:
                h = hint
            out += self._ground_quotes([q], h)
        return out

    def whole(self, numbered: str, rep: Report) -> list[Finding]:
        if not self.use_model:
            return []
        system, user = roles.wholedoc_prompt(self.cr, numbered)
        data = self._llm("WholeDoc", system, user, rep)
        out = []
        if not isinstance(data, dict):
            return out
        single = {c["id"] for c in self.cr["single"]}
        for d in self._dicts(data.get("findings"), "WholeDoc"):
            if isinstance(d.get("quotes"), dict):
                d = {**d, "quotes": [d["quotes"]]}
            scope = "req" if str(d.get("criterion", "")).strip() in single else "set"
            f = self._mk(d, scope, "WholeDoc", [], ground=self._ground_spans)
            if f:
                out.append(f)
        self.step("WholeDoc", f"замечаний: {len(out)}")
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

    @staticmethod
    def same_text(a: str, b: str) -> bool:
        wa = {w for w in re.findall(r"\w+", a.lower()) if len(w) > 3}
        wb = {w for w in re.findall(r"\w+", b.lower()) if len(w) > 3}
        if not wa or not wb:
            return a.strip().lower() == b.strip().lower()
        return len(wa & wb) / len(wa | wb) >= 0.5

    def dedupe(self, findings: list[Finding]) -> list[Finding]:
        out: list[Finding] = []
        for f in findings:
            key = (f.criterion, tuple(sorted(q.start for q in f.quotes)))
            if any((o.criterion, tuple(sorted(q.start for q in o.quotes))) == key and self.same_text(o.problem, f.problem)
                   and not (o.edge and f.edge and o.edge != f.edge) for o in out):
                self.drops.append({"role": "Guard", "reason": "дубликат", "item": f.problem[:160]})
                continue
            out.append(f)
        return out

    def add_merged_text(self, findings: list[Finding], renum: dict[str, str]):
        extra: dict[str, list[str]] = {}
        for k, v in self.merged.items():
            seen = {k}
            while k not in renum and k in self.merge_into and self.merge_into[k] not in seen:
                k = self.merge_into[k]
                seen.add(k)
            if k in renum:
                extra.setdefault(renum[k], []).extend(v)
        for f in findings:
            for text in extra.get(f.id, []):
                if text and text not in f.problem:
                    f.problem = f"{f.problem} Также: {text}"

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
        for d in self._dicts(data.get("decisions"), "Critic"):
            fid = d.get("id")
            if not isinstance(fid, str):
                self._bad("Critic", d)
                continue
            if fid not in by_id:
                continue
            into = d.get("into") if isinstance(d.get("into"), str) else ""
            act = d.get("action")
            if act == "drop":
                drop.add(fid)
                self.drops.append({"role": "Critic", "reason": str(d.get("reason", ""))[:200], "item": by_id[fid].problem[:160]})
            elif act == "merge" and into in by_id and into != fid:
                drop.add(fid)
                tgt = by_id[into]
                for q in by_id[fid].quotes:
                    if all(q.start != x.start for x in tgt.quotes):
                        tgt.quotes.append(q)
                for r in by_id[fid].req_ids:
                    if r not in tgt.req_ids:
                        tgt.req_ids.append(r)
                own = [] if by_id[fid].role == "linter" else [by_id[fid].problem]
                self.merged.setdefault(into, []).extend(own + self.merged.pop(fid, []))
                self.merge_into[fid] = into
                self.drops.append({"role": "Critic", "reason": "", "into": into, "item": by_id[fid].problem[:160]})
            if fid not in drop and d.get("severity") in SEVERITIES:
                by_id[fid].severity = d["severity"]
        kept = [f for f in findings if f.id not in drop]
        ff = data.get("fix_first")
        fix_first = [x for x in (ff if isinstance(ff, list) else [])
                     if isinstance(x, str) and x in by_id and x not in drop]
        self.step("Critic", f"оставлено {len(kept)} из {len(findings)}")
        return kept, fix_first

    def clarify(self, numbered: str, findings: list[Finding], rep: Report) -> list[Question]:
        system, user = roles.clarifier_prompt(self.cr, numbered, self.finding_table(findings))
        data = self._llm("Clarifier", system, user, rep)
        if not isinstance(data, dict):
            return self.fallback_questions(findings)
        ids = {f.id for f in findings}
        out = []
        for q in self._dicts(data.get("questions"), "Clarifier"):
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
            opts, fids = q.get("options"), q.get("finding_ids")
            out.append(Question(id=f"Q-{len(out) + 1:02d}", text=text, quotes=quotes, blocks=str(q.get("blocks", "")),
                                options=[str(o) for o in (opts if isinstance(opts, list) else [])][:4],
                                default=str(q.get("default", "")), addressee=str(q.get("addressee", "")),
                                finding_ids=[x for x in (fids if isinstance(fids, list) else [])
                                             if isinstance(x, str) and x in ids]))
        if not out:
            out = self.fallback_questions(findings)
        self.step("Clarifier", f"вопросов: {len(out)}")
        return out[:14]

    def fallback_questions(self, findings: list[Finding]) -> list[Question]:
        out = []
        for f in [f for f in findings if f.severity != "мелочь"][:10]:
            out.append(Question(id=f"Q-{len(out) + 1:02d}", text=f"{f.problem} Как должно быть?", quotes=f.quotes[:2],
                                blocks=f.impact, options=[], default=f.fix, addressee="аналитик", finding_ids=[f.id]))
        return out

    @staticmethod
    def rank_questions(questions: list[Question], findings: list[Finding]) -> list[Question]:
        sev = {f.id: SEV_RANK.get(f.severity, 3) for f in findings}
        ranked = sorted(questions, key=lambda q: min((sev.get(x, 3) for x in q.finding_ids), default=3))
        for i, q in enumerate(ranked, start=1):
            q.id = f"Q-{i:02d}"
        return ranked

    def verdict(self, findings: list[Finding], fix_first: list[str], reqs: list[Requirement],
                model_used: bool = True) -> dict:
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
        if not model_used:
            return {"status": "Не проверено", "fix_first": fix_first,
                    "text": f"Модель не использовалась, проверены только правила кода ({len(findings)} замечаний). "
                            "Это не подтверждает готовность документа: задайте ключ LLM и повторите проверку."}
        if len(major) > 5:
            return {"status": "С оговорками", "fix_first": fix_first,
                    "text": f"Можно начинать с оговорками: критичных дефектов нет, но {len(major)} важных замечаний заставят команду додумывать."}
        return {"status": "Да", "fix_first": fix_first, "text": "Документ пригоден для начала разработки и тестирования."}
