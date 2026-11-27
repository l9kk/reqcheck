import re

from .model import SEVERITIES, Finding, Report
from .segment import clean

SINGLE_ORDER = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
                "correct", "conforming"]
SHORT = {"necessary": "Необх.", "appropriate": "Уместн.", "unambiguous": "Однозн.", "complete": "Полн.",
         "singular": "Единич.", "feasible": "Реализ.", "verifiable": "Провер.", "correct": "Коррект.",
         "conforming": "Шаблон"}
STATUS = {"ok": "выполнено", "partial": "частично", "fail": "нарушено"}
TYPES = {"functional": "функциональное", "nonfunctional": "нефункциональное", "data": "данные",
         "integration": "интеграция", "api": "API", "ui": "интерфейс", "acceptance": "критерий приёмки",
         "business": "бизнес-цель", "process": "процесс"}
MERGE_SEP = " Также: "
QUOTE_MISSES = ("цитата не найдена в документе", "вопрос без найденной цитаты", "противоречие без второй найденной цитаты")


def cell(s: str, n: int = 0) -> str:
    s = clean(s).replace("|", "\\|")
    return brief(s, n) if n else s


def brief(s: str, n: int) -> str:
    s = clean(s)
    if len(s) <= n:
        return s
    cut = s[:n + 1]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end >= n // 2:
        return cut[:end + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else s[:n]).rstrip(" ,;:—-–") + "…"


def num(n) -> str:
    return f"{n:,}".replace(",", " ")


def where(loc: str) -> str:
    return loc.split(" (")[0]


def crit_name(crit: dict, cid: str) -> str:
    c = crit.get(cid)
    return f"{c['name']} ({c['std']})" if c else cid


LEVELS = {"error": "ошибка", "warning": "предупреждение", "info": "инфо"}


def diag_md(d) -> str:
    return f"- **{LEVELS.get(d.level, d.level)}** `{d.code}`: {d.message}" + (f" Что сделать: {d.hint}" if d.hint else "")


def short_crit(crit: dict, cid: str) -> str:
    c = crit.get(cid)
    return c["name"] if c else cid


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"\w+", s.lower().replace("ё", "е")) if len(w) > 2}


def problem_parts(problem: str) -> list[str]:
    parts = [p.strip() for p in problem.split(MERGE_SEP) if p.strip()]
    kept: list[str] = []
    for p in parts:
        w = _words(p)
        if kept and (not w or any(len(w & _words(k)) >= 0.7 * len(w) for k in kept)):
            continue
        kept.append(p)
    return kept or [problem]


def gist(f: Finding) -> str:
    return problem_parts(f.problem)[0]


def finding_md(f: Finding, crit: dict, asks: dict | None = None) -> list[str]:
    out = [f"**{f.id}** · {f.severity} · {crit_name(crit, f.criterion)}" + (f" · {', '.join(f.req_ids)}" if f.req_ids else "")
           + (f" · граничный случай {f.edge}" if f.edge else "")]
    for q in f.quotes:
        out.append(f"> «{cell(q.text, 300)}» ({q.loc})")
    main, *extra = problem_parts(f.problem)
    out.append(f"- Проблема: {main}")
    out += [f"  - Также: {p}" for p in extra]
    if f.impact:
        out.append(f"- Последствия: {f.impact}")
    qs = ", ".join(asks.get(f.id, [])) if asks else ""
    if f.fix:
        out.append("- Как исправить" + (f" (окончательно после ответа на {qs})" if qs else "") + f": {f.fix}")
    elif qs:
        out.append(f"- Окончательное исправление зависит от ответа на {qs}.")
    if f.test_hint:
        out.append(f"- Тесты: {f.test_hint}")
    out.append("")
    return out


def passport_rows(rep: Report) -> list[tuple[str, str]]:
    p = rep.passport
    calls, cached = p.get("llm_calls", 0), p.get("llm_cached", 0)
    total = calls + cached
    if cached and not calls:
        asked = f"{total}, все ответы взяты из кэша прошлого прогона (новых обращений к модели не было)"
    elif cached:
        asked = f"{total} ({cached} из кэша прошлого прогона, {calls} новых)"
    else:
        asked = str(total)
    rows = [("Документ", p.get("document")), ("SHA-256 документа", p.get("sha256", "")[:16] + "…" if p.get("sha256") else "-"),
            ("Формат", p.get("format", "-")), ("Дата прогона", p.get("date")),
            ("Модель", f"{p.get('model')} ({p.get('provider')})"), ("Версия агента", p.get("agent_version")),
            ("Стандарты", p.get("standards")), ("Запросов к модели", asked)]
    tr = rep.trace
    note = " (в исходном прогоне, до кэша)" if cached and not calls else (" (с исходными запросами из кэша)" if cached else "")
    model_secs = p.get("llm_seconds_uncached") if cached else (round(sum(t["seconds"] for t in tr), 1) if tr else None)
    if model_secs is not None:
        rows.append(("Время работы модели", f"{model_secs} с{note}"))
    if tr:
        rows.append(("Токены модели, вход / выход",
                     f"{num(sum(t['in_tokens'] for t in tr))} / {num(sum(t['out_tokens'] for t in tr))}{note}"))
    rows.append(("Время этого прогона", f"{p.get('seconds')} с" + (", ответы модели взяты из кэша" if cached and not calls else "")))
    return rows


def first_screen(rep: Report, crit: dict, asks: dict, counts: dict) -> list[str]:
    v = rep.verdict
    crit_f = [f for f in rep.findings if f.severity == "критично"]
    crit_ids = {f.id for f in crit_f}
    known = {f.id for f in rep.findings}
    head = (f"**Начинать разработку и тестирование: {v.get('status')}.** "
            f"Критичных дефектов: {len(crit_f)}, вопросов к автору: {len(rep.questions)}.")
    first_q = [q.id for q in rep.questions if crit_ids & set(q.finding_ids)][:5]
    ff = [x for x in v.get("fix_first") or [] if x in known][:5]
    todo = ([f"ответить на {', '.join(first_q)}"] if first_q else []) + ([f"исправить {', '.join(ff)}"] if ff else [])
    if todo:
        head += " Сначала " + " и ".join(todo) + "."
    req_with = {r for f in rep.findings for r in f.req_ids}
    n_fq = sum(len(f.quotes) for f in rep.findings)
    n_qq = sum(len(q.quotes) for q in rep.questions)
    missed = sum(1 for d in rep.drops if d.get("reason") in QUOTE_MISSES)
    L = ["## Главное за 2 минуты", "", head, "",
         f"- Замечаний: **{len(rep.findings)}** (критично: {counts['критично']}, важно: {counts['важно']}, "
         f"мелочь: {counts['мелочь']}), затронуто требований: {len(req_with)} из {len(rep.requirements)}.",
         f"- Цитат: **{n_fq + n_qq}** ({n_fq} в замечаниях, {n_qq} в вопросах). Каждую код нашёл в тексте документа "
         f"и сам поставил номер строки; предложений модели с ненайденной цитатой отброшено: {missed}.", ""]
    if crit_f:
        L += ["### Критичные дефекты", ""]
        for f in crit_f:
            tag = ", ".join([short_crit(crit, f.criterion)] + [f"вопрос {x}" for x in asks.get(f.id, [])])
            L.append(f"**{f.id}** ({tag}): {brief(gist(f), 240)}")
            for q in f.quotes[:2]:
                L.append(f"> «{cell(q.text, 160)}» ({where(q.loc)})")
            if len(f.quotes) > 2:
                L.append(f"> ещё цитат: {len(f.quotes) - 2}, полностью в разделе {5 if f.scope == 'req' else 6}")
            if f.impact:
                L.append(f"- Последствия: {brief(f.impact, 200)}")
            L.append("")
    if rep.questions:
        L += ["### Главные вопросы к автору", ""]
        for q in rep.questions[:5]:
            meta = "; ".join(x for x in [q.addressee, f"закрывает {', '.join(q.finding_ids)}" if q.finding_ids else ""] if x)
            L.append(f"**{q.id}**" + (f" ({meta})" if meta else "") + f": {q.text}")
            if q.options:
                L.append("- Варианты: " + "; ".join(f"({chr(1072 + i)}) {o}" for i, o in enumerate(q.options)))
            if q.default:
                L.append(f"- Рекомендация агента: {q.default}")
            L.append("")
    L += ["Подробно: все замечания в разделе 2, все вопросы в разделе 3, проверка требований в разделах 5 и 6.", ""]
    return L


def drop_reason(d: dict) -> str:
    r = d.get("reason", "")
    if r.startswith("объединено с"):
        return "объединено с другим замечанием, текст добавлен к нему"
    if r.startswith("неизвестный критерий"):
        return "неизвестный критерий"
    if d.get("role") == "Critic":
        return "отклонено критиком"
    return r or "без причины"


def render(rep: Report, crit: dict) -> str:
    p = rep.passport
    L: list[str] = []
    title = p.get("doc_title") or p.get("document")
    L += [f"# Отчёт о проверке требований: {title}", ""]

    passport = ["## 1. Паспорт прогона", "", "| Поле | Значение |", "| --- | --- |"]
    passport += [f"| {a} | {b} |" for a, b in passport_rows(rep)] + [""]

    if any(d.level == "error" for d in rep.diagnostics) and not rep.requirements:
        L += passport + ["## Диагностика", ""]
        for d in rep.diagnostics:
            L.append(diag_md(d))
        L += ["", "## Итог", "", f"**{rep.verdict.get('status', 'Нет')}.** {rep.verdict.get('text', '')}", ""]
        return "\n".join(L)

    counts = {s: sum(1 for f in rep.findings if f.severity == s) for s in SEVERITIES}
    asks: dict[str, list[str]] = {}
    for q in rep.questions:
        for fid in q.finding_ids:
            asks.setdefault(fid, []).append(q.id)
    L += first_screen(rep, crit, asks, counts) + passport

    req_with = {r for f in rep.findings for r in f.req_ids}
    L += ["## 2. Сводка", "",
          f"- Требований выделено: **{len(rep.requirements)}**, из них с замечаниями: **{len(req_with)}**.",
          f"- Нарушений: **{len(rep.findings)}** (критично: {counts['критично']}, важно: {counts['важно']}, мелочь: {counts['мелочь']}).",
          f"- Уточняющих вопросов к автору: **{len(rep.questions)}**.",
          f"- Вердикт: **{rep.verdict.get('status')}**. {rep.verdict.get('text', '')}", ""]
    if rep.findings:
        L += ["Все замечания (подробности в разделах 5 и 6, по ID):", "",
              "| ID | Важность | Где | Свойство | Суть | Вопрос |", "| --- | --- | --- | --- | --- | --- |"]
        for f in rep.findings:
            at = where(f.quotes[0].loc) if f.quotes else "-"
            L.append(f"| {f.id} | {f.severity} | {at} | {short_crit(crit, f.criterion)} | {cell(gist(f), 160)} | "
                     f"{', '.join(asks.get(f.id, [])) or '-'} |")
        L.append("")

    L += ["## 3. Уточняющие вопросы к автору", "",
          "Без ответов на эти вопросы нельзя однозначно реализовать или протестировать требования. Порядок: по важности.", ""]
    if not rep.questions:
        L += ["Вопросов нет.", ""]
    for q in rep.questions:
        L.append(f"**{q.id}.** {q.text}" + (f" *Кому: {q.addressee}.*" if q.addressee else ""))
        for qq in q.quotes:
            L.append(f"> «{cell(qq.text, 250)}» ({qq.loc})")
        if q.blocks:
            L.append(f"- Что блокирует: {q.blocks}")
        if q.options:
            L.append("- Варианты: " + "; ".join(f"({chr(1072 + i)}) {o}" for i, o in enumerate(q.options)))
        if q.default:
            L.append(f"- Рекомендация агента: {q.default}")
        if q.finding_ids:
            L.append(f"- Закрывает замечания: {', '.join(q.finding_ids)}")
        L.append("")

    L += ["## 4. Как агент нарезал требования", "",
          "Фрагменты выделены кодом с точными номерами строк, модель только классифицирует и объединяет их, поэтому каждая цитата дословно есть в документе.", "",
          "| ID в отчёте | ID в документе | Тип | Где | Краткая формулировка | Цитата |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rep.requirements:
        L.append(f"| {r.id} | {r.doc_id or '— (нет)'} | {TYPES.get(r.type, r.type or '-')} | строки {r.quote.start}-{r.quote.end} | "
                 f"{cell(r.short, 90)} | «{cell(r.quote.text, 140)}» |")
    L.append("")

    L += ["## 5. Проверка каждого требования", "",
          "Свойства по ISO/IEC/IEEE 29148:2018 п. 5.2.5. ✓ выполнено, ✗ нарушено (подробности ниже).", ""]
    if rep.req_checks:
        L += ["| Требование | " + " | ".join(SHORT[c] for c in SINGLE_ORDER) + " |",
              "| --- |" + " :---: |" * len(SINGLE_ORDER)]
        for r in rep.requirements:
            fails = {f.criterion for f in rep.findings if r.id in f.req_ids and f.scope == "req"}
            label = f"{r.id}" + (f" ({r.doc_id})" if r.doc_id else "")
            L.append(f"| {label} | " + " | ".join("✗" if c in fails else "✓" for c in SINGLE_ORDER) + " |")
        L.append("")
    else:
        L += ["Проверка свойств моделью не выполнялась (см. диагностику); ниже замечания по правилам.", ""]
    req_f = [f for f in rep.findings if f.scope == "req"]
    home: dict[str, str] = {}
    for r in rep.requirements:
        for f in req_f:
            if r.id in f.req_ids:
                home.setdefault(f.id, r.id)
    if any(len(f.req_ids) > 1 for f in req_f):
        L += ["Замечание, которое касается нескольких требований, описано полностью один раз, "
              "под первым из них; у остальных стоит ссылка.", ""]
    for r in rep.requirements:
        fs = [f for f in req_f if r.id in f.req_ids]
        if not fs:
            continue
        L += [f"### {r.id}" + (f" ({r.doc_id})" if r.doc_id else "") + f": {cell(r.short, 100)}", ""]
        for f in fs:
            if home[f.id] == r.id:
                L += finding_md(f, crit, asks)
        refs = [f for f in fs if home[f.id] != r.id]
        for f in refs:
            L.append(f"- См. **{f.id}** ({f.severity}, описано под {home[f.id]}): {brief(gist(f), 110)}")
        if refs:
            L.append("")
    orphan = [f for f in req_f if f.id not in home]
    if orphan:
        L += ["### Замечания к формулировкам вне выделенных требований", ""]
        for f in orphan:
            L += finding_md(f, crit, asks)

    L += ["## 6. Проверка набора требований", "",
          "Свойства набора по ISO/IEC/IEEE 29148:2018 п. 5.2.6 и спецификации по IEEE 830-1998 п. 4.3.", ""]
    if rep.set_summary:
        L += ["| Свойство | Оценка | Комментарий |", "| --- | --- | --- |"]
        for s in rep.set_summary:
            L.append(f"| {crit_name(crit, s['criterion'])} | {STATUS.get(s['status'], s['status'])} | {cell(s['comment'], 300)} |")
        L.append("")
    for f in [f for f in rep.findings if f.scope == "set"]:
        L += finding_md(f, crit, asks)

    if rep.checklist:
        L += ["## 7. Чек-лист ревью из документа (заполнен агентом)", "", "| Проверка | Ответ | Обоснование |", "| --- | --- | --- |"]
        for c in rep.checklist:
            L.append(f"| {cell(c.item, 160)} | {cell(c.value)} | {cell(c.evidence, 300)} |")
        L.append("")
    else:
        L += ["## 7. Чек-лист ревью", "", "В документе нет чек-листа ревью или он не заполнен моделью.", ""]

    L += ["## 8. Итог", "", f"**Можно ли начинать разработку и тестирование: {rep.verdict.get('status')}.** {rep.verdict.get('text', '')}", ""]
    ff = rep.verdict.get("fix_first") or []
    if ff:
        by = {f.id: f for f in rep.findings}
        L += ["Что исправить в первую очередь:", ""]
        for n, fid in enumerate(ff, start=1):
            if fid in by:
                f = by[fid]
                L.append(f"{n}. **{fid}** ({f.quotes[0].loc}): {gist(f)}" + (f" Исправление: {f.fix}" if f.fix else ""))
        L.append("")

    whole = " и WholeDoc (модель, весь документ одним запросом)" if any(t.get("role") == "WholeDoc" for t in rep.trace) else ""
    L += ["## 9. Как работал агент", "",
          "Конвейер ролей: Reader (код) → Segmenter (модель + проверка цитат кодом) → Linter (код, правила 29148 п. 5.2.7) → "
          "Auditor (модель, 5.2.5, пачки требований параллельно) → параллельно: CrossChecker (модель, 5.2.6 и IEEE 830) → "
          f"EdgeCaser (модель, граничные случаи){whole} → Critic (модель) → Clarifier (модель) → Reporter (код).", ""]
    if rep.trace:
        L += ["| Роль | Ответ из кэша | Время модели, с | Токены вход / выход |", "| --- | --- | --- | --- |"]
        for t in rep.trace:
            secs = t.get("orig_seconds", "-") if t["cached"] else t["seconds"]
            L.append(f"| {t['role']} | {'да' if t['cached'] else 'нет'} | {secs} | {num(t['in_tokens'])} / {num(t['out_tokens'])} |")
        L.append("")
        if any(t["cached"] for t in rep.trace):
            L += ["Для ответов из кэша указаны время и токены исходного запроса к модели.", ""]
    if rep.drops:
        by_reason: dict[str, int] = {}
        for d in rep.drops:
            k = f"{d['role']}: {drop_reason(d)}"
            by_reason[k] = by_reason.get(k, 0) + 1
        L += [f"Защитные проверки отбросили элементов: {len(rep.drops)}.", ""]
        L += [f"- {k}: {v}" for k, v in by_reason.items()]
        L += ["", "Полный список с текстами: JSON-отчёт рядом с этим файлом, поле `drops`.", ""]
    if rep.diagnostics:
        L += ["### Диагностика", ""]
        for d in rep.diagnostics:
            L.append(diag_md(d))
        L.append("")
    return "\n".join(L)


