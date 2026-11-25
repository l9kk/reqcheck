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


def cell(s: str, n: int = 0) -> str:
    s = clean(s).replace("|", "\\|")
    return (s[:n] + "…") if n and len(s) > n else s


def crit_name(crit: dict, cid: str) -> str:
    c = crit.get(cid)
    return f"{c['name']} ({c['std']})" if c else cid


def finding_md(f: Finding, crit: dict) -> list[str]:
    out = [f"**{f.id}** · {f.severity} · {crit_name(crit, f.criterion)}" + (f" · {', '.join(f.req_ids)}" if f.req_ids else "")]
    for q in f.quotes:
        out.append(f"> «{cell(q.text, 300)}» ({q.loc})")
    out.append(f"- Проблема: {f.problem}")
    if f.impact:
        out.append(f"- Последствия: {f.impact}")
    if f.fix:
        out.append(f"- Как исправить: {f.fix}")
    if f.test_hint:
        out.append(f"- Тесты: {f.test_hint}")
    out.append("")
    return out


def render(rep: Report, crit: dict) -> str:
    p = rep.passport
    L: list[str] = []
    title = p.get("doc_title") or p.get("document")
    L += [f"# Отчёт о проверке требований: {title}", ""]

    L += ["## 1. Паспорт прогона", "", "| Поле | Значение |", "| --- | --- |"]
    rows = [("Документ", p.get("document")), ("SHA-256 документа", p.get("sha256", "")[:16] + "…" if p.get("sha256") else "-"),
            ("Формат", p.get("format", "-")), ("Дата прогона", p.get("date")),
            ("Модель", f"{p.get('model')} ({p.get('provider')})"), ("Версия агента", p.get("agent_version")),
            ("Стандарты", p.get("standards")),
            ("Запросов к модели", f"{p.get('llm_calls', 0)} (из кэша: {p.get('llm_cached', 0)})"),
            ("Время прогона", f"{p.get('seconds')} с")]
    L += [f"| {a} | {b} |" for a, b in rows] + [""]

    if any(d.level == "error" for d in rep.diagnostics) and not rep.requirements:
        L += ["## Диагностика", ""]
        for d in rep.diagnostics:
            L.append(f"- **{d.level}** `{d.code}`: {d.message}" + (f" Что сделать: {d.hint}" if d.hint else ""))
        L += ["", "## Итог", "", f"**{rep.verdict.get('status', 'Нет')}.** {rep.verdict.get('text', '')}", ""]
        return "\n".join(L)

    counts = {s: sum(1 for f in rep.findings if f.severity == s) for s in SEVERITIES}
    req_with = {r for f in rep.findings for r in f.req_ids}
    L += ["## 2. Сводка", "",
          f"- Требований выделено: **{len(rep.requirements)}**, из них с замечаниями: **{len(req_with)}**.",
          f"- Нарушений: **{len(rep.findings)}** (критично: {counts['критично']}, важно: {counts['важно']}, мелочь: {counts['мелочь']}).",
          f"- Уточняющих вопросов к автору: **{len(rep.questions)}**.",
          f"- Вердикт: **{rep.verdict.get('status')}**. {rep.verdict.get('text', '')}", ""]
    crit_f = [f for f in rep.findings if f.severity == "критично"]
    if crit_f:
        L += ["Критичные дефекты:", ""]
        for f in crit_f:
            L.append(f"- **{f.id}** ({crit_name(crit, f.criterion)}; {f.quotes[0].loc}): {f.problem}")
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
            fails = set(rep.req_checks.get(r.id, []))
            fails |= {f.criterion for f in rep.findings if r.id in f.req_ids and f.scope == "req"}
            label = f"{r.id}" + (f" ({r.doc_id})" if r.doc_id else "")
            L.append(f"| {label} | " + " | ".join("✗" if c in fails else "✓" for c in SINGLE_ORDER) + " |")
        L.append("")
    else:
        L += ["Проверка свойств моделью не выполнялась (см. диагностику); ниже замечания по правилам.", ""]
    req_f = [f for f in rep.findings if f.scope == "req"]
    for r in rep.requirements:
        fs = [f for f in req_f if r.id in f.req_ids]
        if not fs:
            continue
        L += [f"### {r.id}" + (f" ({r.doc_id})" if r.doc_id else "") + f": {cell(r.short, 100)}", ""]
        for f in fs:
            L += finding_md(f, crit)
    orphan = [f for f in req_f if not f.req_ids]
    if orphan:
        L += ["### Замечания к формулировкам вне выделенных требований", ""]
        for f in orphan:
            L += finding_md(f, crit)

    L += ["## 6. Проверка набора требований", "",
          "Свойства набора по ISO/IEC/IEEE 29148:2018 п. 5.2.6 и спецификации по IEEE 830-1998 п. 4.3.", ""]
    if rep.set_summary:
        L += ["| Свойство | Оценка | Комментарий |", "| --- | --- | --- |"]
        for s in rep.set_summary:
            L.append(f"| {crit_name(crit, s['criterion'])} | {STATUS.get(s['status'], s['status'])} | {cell(s['comment'], 300)} |")
        L.append("")
    for f in [f for f in rep.findings if f.scope == "set"]:
        L += finding_md(f, crit)

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
                L.append(f"{n}. **{fid}** ({f.quotes[0].loc}): {f.problem}" + (f" Исправление: {f.fix}" if f.fix else ""))
        L.append("")

    L += ["## 9. Как работал агент", "",
          "Конвейер ролей: Reader (код) → Segmenter (модель + проверка цитат кодом) → Linter (код, правила 29148 п. 5.2.7) → "
          "Auditor (модель, 5.2.5) → CrossChecker (модель, 5.2.6 и IEEE 830) → Critic (модель) → Clarifier (модель) → Reporter (код).", ""]
    if rep.trace:
        L += ["| Роль | Из кэша | Секунд | Токены вход/выход |", "| --- | --- | --- | --- |"]
        for t in rep.trace:
            L.append(f"| {t['role']} | {'да' if t['cached'] else 'нет'} | {t['seconds']} | {t['in_tokens']}/{t['out_tokens']} |")
        L.append("")
    if rep.drops:
        L += [f"Защитные проверки отбросили {len(rep.drops)} элементов (цитата не найдена в документе, дубликат, решение критика):", ""]
        for d in rep.drops[:40]:
            L.append(f"- {d['role']}: {d['reason']}. {cell(d.get('item', ''), 160)}")
        L.append("")
    if rep.diagnostics:
        L += ["### Диагностика", ""]
        for d in rep.diagnostics:
            L.append(f"- **{d.level}** `{d.code}`: {d.message}" + (f" Что сделать: {d.hint}" if d.hint else ""))
        L.append("")
    return "\n".join(L)
