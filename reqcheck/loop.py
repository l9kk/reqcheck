import re

from . import roles
from .ground import norm
from .model import Finding, Quote
from .segment import clean


def affected(rep, q) -> list[str]:
    ids = [r.id for r in rep.requirements
           if any(r.quote.start <= x.end and x.start <= r.quote.end for x in q.quotes)]
    if not ids:
        by_id = {f.id: f for f in rep.findings}
        for fid in q.finding_ids:
            for rid in by_id[fid].req_ids if fid in by_id else []:
                if rid not in ids:
                    ids.append(rid)
    return ids


def scope(rep, items: list[dict]):
    """rewritten: req id -> {text, qs}; neighbours: req ids next to them in document order."""
    order = [r.id for r in rep.requirements]
    rewritten: dict[str, dict] = {}
    for v in items:
        ids = affected(rep, v["q"])
        if not ids:
            continue
        text = v["requirement"] + (" Критерии приёмки: " + " ".join(v["acceptance"]) if v["acceptance"] else "")
        cur = rewritten.setdefault(ids[0], {"text": "", "qs": []})
        cur["text"] = (cur["text"] + " " + text).strip()
        cur["qs"].append(v["q"].id)
    neigh = []
    for rid in list(rewritten):
        i = order.index(rid)
        for j in (i - 1, i + 1):
            if 0 <= j < len(order) and order[j] not in rewritten and order[j] not in neigh:
                neigh.append(order[j])
    return rewritten, neigh


def req_table(pipe, rep, rewritten: dict, neigh: list[str]) -> str:
    by_id = {r.id: r for r in rep.requirements}
    rows = []
    for rid in sorted(set(rewritten) | set(neigh)):
        r = by_id[rid]
        if rid in rewritten:
            rows.append(f"{rid} [{r.type or '-'}; {r.doc_id or 'без id'}; {r.section}] "
                        f"[ПЕРЕПИСАНО по {', '.join(rewritten[rid]['qs'])}]: {rewritten[rid]['text']}")
        else:
            rows.append(f"{rid} [{r.type or '-'}; {r.doc_id or 'без id'}; строки {r.quote.start}-{r.quote.end}; "
                        f"{r.section}]: {clean(r.quote.text)[:600]}")
    return "\n".join(rows)


def patched_doc(pipe, rep, rewritten: dict) -> str:
    swap = {}
    for r in rep.requirements:
        if r.id in rewritten:
            swap[r.quote.start] = f"[{r.id}, ПЕРЕПИСАНО по {', '.join(rewritten[r.id]['qs'])}] {rewritten[r.id]['text']}"
            for n in range(r.quote.start + 1, r.quote.end + 1):
                swap[n] = f"[заменено переписанным {r.id}]"
    return "\n".join(f"{l.no:>4}| {swap.get(l.no, l.text)}" for l in pipe.doc.lines)


def grounder(pipe, rewritten: dict):
    texts = {rid: norm(v["text"]) for rid, v in rewritten.items()}

    def ground(raw, hint=None):
        out = []
        for q in raw:
            if not isinstance(q, str) or not q.strip():
                continue
            nq = norm(q).strip(' ."')
            hit = next((rid for rid, t in texts.items() if len(nq) >= 4 and nq in t), None)
            if hit:
                out.append(Quote(text=q.strip(), start=-int(re.sub(r"\D", "", hit) or 1), end=0,
                                 loc=f"{hit}, переписанный текст"))
            else:
                gq = pipe.g.locate(q, hint)
                if gq:
                    out.append(gq)
        return out
    return ground


def fmt_old(f, linked: bool) -> str:
    return (f"{f.id} [{f.criterion}; {f.severity}; {', '.join(f.req_ids) or 'набор'}"
            f"{'; связано с ответом' if linked else ''}] {f.problem}")


def recheck(pipe, rep, items: list[dict], say=print) -> dict | None:
    rewritten, neigh = scope(rep, items)
    if not rewritten:
        say("Перепроверка: не удалось сопоставить ответы с требованиями.")
        return None
    calls0, drops0 = len(pipe.llm.trace), len(pipe.drops)
    say(f"\nПерепроверка: переписано требований {len(rewritten)}, соседей {len(neigh)}.")
    table = req_table(pipe, rep, rewritten, neigh)
    numbered = patched_doc(pipe, rep, rewritten)
    ground = grounder(pipe, rewritten)

    sys_a, usr_a = roles.auditor_prompt(pipe.cr, numbered, table)
    data = pipe._llm("Auditor", sys_a + roles.RECHECK_NOTE, usr_a, rep)
    results = {r.get("req_id"): r for r in (data or {}).get("results", []) or [] if isinstance(r, dict)}
    if not isinstance(data, dict) or not all(rid in results for rid in rewritten):
        say("Перепроверка не выполнена: аудитор не вернул разбор переписанных требований. Закрытыми ничего не считаем.")
        return None
    new: list[Finding] = []
    for rid in sorted(set(rewritten) | set(neigh)):
        for d in results.get(rid, {}).get("findings", []) or []:
            f = pipe._mk(d, "req", "Auditor", [rid], None, ground) if isinstance(d, dict) else None
            if f:
                new.append(f)

    sys_c, usr_c = roles.cross_prompt(pipe.cr, numbered, table, "- нет", False)
    cdata = pipe._llm("CrossChecker", sys_c + roles.RECHECK_CROSS_NOTE, usr_c, rep)
    cross_ok = isinstance(cdata, dict)
    if cross_ok:
        raw = list(cdata.get("findings", []) or [])
        for st in cdata.get("steps", []) or []:
            if isinstance(st, dict):
                raw += [d for d in st.get("findings", []) or [] if isinstance(d, dict)]
        for d in raw:
            f = pipe._mk(d, "set", "CrossChecker", [], None, ground)
            if f:
                f.req_ids = [r for r in (re.findall(r"R-\d+", " ".join(q.loc for q in f.quotes))) if r in rewritten] \
                    or list(rewritten)[:1]
                new.append(f)
    for i, f in enumerate(new, start=1):
        f.id = f"N-{i:02d}"

    linked_ids = {x for v in items for x in v["q"].finding_ids}
    in_scope = set(rewritten) | set(neigh)
    old = [f for f in rep.findings if f.id in linked_ids or (set(f.req_ids) & in_scope)]
    linked = [f for f in rep.findings if f.id in linked_ids or (set(f.req_ids) & set(rewritten))]
    return judge(pipe, rep, items, rewritten, old, linked, new, calls0, drops0, cross_ok, say)


def judge(pipe, rep, items, rewritten, old, linked, new, calls0, drops0, cross_ok, say) -> dict:
    lid = {f.id for f in linked}
    rw = "\n".join(f"{rid}: {v['text']}" for rid, v in rewritten.items())
    sys_j, usr_j = roles.delta_prompt(rw, "\n".join(fmt_old(f, f.id in lid) for f in old),
                                      "\n".join(f"{f.id} [{f.criterion}; {f.severity}; {', '.join(f.req_ids)}] {f.problem}"
                                                for f in new))
    jd = pipe._llm("Delta", sys_j, usr_j, rep)
    olds = {x.get("id"): x for x in (jd or {}).get("old", []) or [] if isinstance(x, dict)} if isinstance(jd, dict) else {}
    news = {x.get("id"): x for x in (jd or {}).get("new", []) or [] if isinstance(x, dict)} if isinstance(jd, dict) else {}
    judged = bool(olds)
    by_old = {f.id: f for f in old}
    closed, remains, fresh = [], [], []
    for f in linked:
        j = olds.get(f.id, {})
        if judged and j.get("status") == "closed":
            closed.append((f, str(j.get("reason", ""))))
        else:
            why = str(j.get("reason", "")) if judged else "автоматическая сверка: оценка модели недоступна"
            remains.append((f, why))
    for f in new:
        same = str(news.get(f.id, {}).get("same_as", "") or "")
        if judged and same in by_old:
            if same in lid and not any(x is by_old[same] for x, _ in remains + closed):
                remains.append((by_old[same], "найдено повторно при перепроверке"))
            continue
        if not judged:
            twin = next((o for o in linked if o.criterion == f.criterion and set(o.req_ids) & set(f.req_ids)), None)
            if twin:
                continue
        fresh.append((f, str(news.get(f.id, {}).get("reason", ""))))
    closed_ids = {f.id for f, _ in closed}
    remains = [(f, w) for f, w in remains if f.id not in closed_ids]
    trace = pipe.llm.trace[calls0:]
    return {"rewritten": rewritten, "closed": closed, "remains": remains, "new": fresh, "judged": judged,
            "cross_ok": cross_ok, "calls": len(trace), "seconds": round(sum(t["seconds"] for t in trace), 1),
            "guard_drops": len(pipe.drops) - drops0}


def _line(f, why, answer_q=None) -> str:
    q = f.quotes[0] if f.quotes else None
    where = f"{', '.join(f.req_ids)}" if f.req_ids else "набор"
    quote = f" «{clean(q.text)[:140]}» ({q.loc})" if q else ""
    tail = f" Почему: {why}" if why else ""
    return f"- {f.id} [{f.severity}, {f.criterion}, {where}]{quote}: {f.problem}{tail}"


def render_delta(d: dict) -> str:
    md = ["## Дельта после ответов", "",
          f"Переписано требований: {len(d['rewritten'])} ({', '.join(d['rewritten'])}). Перепроверка: Аудитор и "
          f"Кросс-проверка на переписанных требованиях и соседних, затем сверка. Вызовов модели: {d['calls']}, "
          f"{d['seconds']} с. Замечания на переписанном тексте ссылаются на номер требования и его новую формулировку; "
          f"номера строк документа у них нет.", ""]
    if not d["judged"]:
        md += ["Оценка модели по сверке недоступна: закрытыми ничего не считаем.", ""]
    if not d["cross_ok"]:
        md += ["Кросс-проверка не ответила: новые противоречия могли остаться незамеченными.", ""]
    md += [f"Итог: закрыто {len(d['closed'])}, осталось {len(d['remains'])}, новых {len(d['new'])}.", ""]
    for title, key in (("Закрыто ответами", "closed"), ("Осталось", "remains"), ("Появилось новое", "new")):
        md += [f"### {title} ({len(d[key])})", ""]
        rows = [_line(f, w) + ("" if key != "new" or set(f.req_ids) & set(d["rewritten"]) else " (сосед, текст не менялся)")
                for f, w in d[key]]
        md += rows or ["- нет"]
        md.append("")
    return "\n".join(md)
