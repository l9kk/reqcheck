import re

from . import roles
from .pipeline import AUDIT_BATCH
from .ground import norm
from .model import SEVERITIES, Finding, Quote
from .segment import clean


def linked_reqs(rep, q, cap: int = 8) -> list[str]:
    by_id = {f.id: f for f in rep.findings}
    ids = [r.id for r in rep.requirements
           if any(r.quote.start <= x.end and x.start <= r.quote.end for x in q.quotes)]
    for fid in q.finding_ids:
        for rid in by_id[fid].req_ids if fid in by_id else []:
            if rid not in ids:
                ids.append(rid)
    return ids[:cap]


def scope(rep, items: list[dict]):
    """rewritten: req id -> {text, qs}; neighbours: req ids next to them in document order."""
    order = [r.id for r in rep.requirements]
    rewritten: dict[str, dict] = {}
    for v in items:
        for w in v.get("rewrites", []):
            text = w["requirement"] + (" Критерии приёмки: " + " ".join(w["acceptance"]) if w["acceptance"] else "")
            cur = rewritten.setdefault(w["req_id"], {"text": "", "qs": []})
            cur["text"] = (cur["text"] + " " + text).strip()
            if v["q"].id not in cur["qs"]:
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
                        f"[ПЕРЕПИСАНО по {', '.join(rewritten[rid]['qs'])}]: {' '.join(rewritten[rid]['text'].split())}")
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

    rows = table.split("\n")
    results: dict = {}
    for b0 in range(0, len(rows), AUDIT_BATCH):
        sys_a, usr_a = roles.auditor_prompt(pipe.cr, numbered, "\n".join(rows[b0:b0 + AUDIT_BATCH]))
        data = pipe._llm("Auditor", sys_a + roles.RECHECK_NOTE, usr_a, rep)
        for r in (data or {}).get("results", []) or []:
            if isinstance(r, dict):
                results[r.get("req_id")] = r
    unchecked = {rid for rid in rewritten if rid not in results}
    if len(unchecked) == len(rewritten):
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
    return judge(pipe, rep, rewritten, old, linked_ids, new, calls0, drops0, cross_ok, unchecked, rep.findings)


def judge(pipe, rep, rewritten, old, linked_ids, new, calls0, drops0, cross_ok, unchecked=frozenset(), all_old=()) -> dict:
    rw = "\n".join(f"{rid}: {v['text']}" for rid, v in rewritten.items())
    sys_j, usr_j = roles.delta_prompt(rw, "\n".join(fmt_old(f, f.id in linked_ids) for f in old),
                                      "\n".join(f"{f.id} [{f.criterion}; {f.severity}; {', '.join(f.req_ids)}] {f.problem}"
                                                for f in new))
    jd = pipe._llm("Delta", sys_j, usr_j, rep)
    olds = {x.get("id"): x for x in (jd or {}).get("old", []) or [] if isinstance(x, dict)}
    news = {x.get("id"): x for x in (jd or {}).get("new", []) or [] if isinstance(x, dict)}
    judged = bool(olds)
    by_old = {f.id: f for f in old}
    rw_ids = set(rewritten)
    can_close = rw_ids - set(unchecked)
    closed, remains = [], []
    for f in old:
        if f.id not in linked_ids:
            continue
        j = olds.get(f.id, {})
        if judged and j.get("status") == "closed" and set(f.req_ids) & can_close:
            closed.append((f, str(j.get("reason", ""))))
        else:
            why = str(j.get("reason", "")) if judged else "оценка модели недоступна, закрытым не считаем"
            if judged and j.get("status") == "closed":
                why = "требование не переписано или не перепроверено, закрытым не считаем"
            remains.append((f, why))
    fresh, repeat_nb, other_nb, noise = [], 0, 0, 0
    for f in new:
        same = str(news.get(f.id, {}).get("same_as", "") or "")
        if not judged:
            same = next((o.id for o in old if o.criterion == f.criterion and set(o.req_ids) & set(f.req_ids)), "")
        if same in by_old:
            if same in linked_ids:
                if not any(x is by_old[same] for x, _ in remains + closed):
                    remains.append((by_old[same], "найдено повторно при перепроверке"))
            elif not set(by_old[same].req_ids) & rw_ids:
                repeat_nb += 1
            continue
        on_rewritten = bool(set(f.req_ids) & rw_ids) or any("переписанный" in q.loc for q in f.quotes)
        if on_rewritten and f.req_ids and set(f.req_ids) <= rw_ids and \
                (f.criterion in NOISE_CRITERIA or DUP_RE.search(f.problem)):
            noise += 1
        elif on_rewritten:
            fresh.append((f, str(news.get(f.id, {}).get("reason", ""))))
        else:
            other_nb += 1
    closed_ids = {f.id for f, _ in closed}
    remains = [(f, w) for f, w in remains if f.id not in closed_ids]
    untouched = sum(1 for f in old if f.id not in linked_ids and set(f.req_ids) & rw_ids)
    trace = pipe.llm.trace[calls0:]
    return {"rewritten": rewritten, "closed": closed, "remains": remains, "new": fresh, "judged": judged,
            "cross_ok": cross_ok, "calls": len(trace), "seconds": round(sum(t["seconds"] for t in trace), 1),
            "guard_drops": len(pipe.drops) - drops0, "untouched": untouched, "repeat_nb": repeat_nb,
            "other_nb": other_nb, "noise": noise, "all_old": list(all_old)}


def _line(f, why, answer_q=None) -> str:
    q = f.quotes[0] if f.quotes else None
    where = f"{', '.join(f.req_ids)}" if f.req_ids else "набор"
    quote = f" «{clean(q.text)[:140]}» ({q.loc})" if q else ""
    tail = f" Почему: {why}" if why else ""
    return f"- {f.id} [{f.severity}, {f.criterion}, {where}]{quote}: {f.problem}{tail}"


CONTRADICTION = {"correct", "set_consistent"}


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


def group_new(items: list) -> list[list]:
    """New findings about one issue go together: same criterion (correct and set_consistent count as one, both
    are contradictions) and close wording (shared word stems)."""
    groups: list[dict] = []
    for f, why in items:
        fam = "contradiction" if f.criterion in CONTRADICTION else f.criterion
        st = _stems(f.problem)
        for g in groups:
            if g["fam"] == fam and any(st and s and len(st & s) / len(st | s) >= 0.3 for s in g["stems"]):
                g["items"].append((f, why))
                g["stems"].append(st)
                break
        else:
            groups.append({"fam": fam, "stems": [st], "items": [(f, why)]})
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    return [sorted(g["items"], key=lambda x: rank.get(x[0].severity, 3)) for g in groups]


def _group_line(group: list) -> str:
    if len(group) == 1:
        return _line(*group[0])
    f, why = group[0]
    ids = ", ".join(x.id for x, _ in group)
    crits = ", ".join(dict.fromkeys(x.criterion for x, _ in group))
    reqs = ", ".join(dict.fromkeys(r for x, _ in group for r in x.req_ids)) or "набор"
    q = f.quotes[0] if f.quotes else None
    quote = f" «{clean(q.text)[:140]}» ({q.loc})" if q else ""
    also = "; ".join(f"{x.id} «{clean(x.quotes[0].text)[:80]}» ({x.quotes[0].loc})" if x.quotes else x.id
                     for x, _ in group[1:])
    tail = f" Почему: {why}" if why else ""
    return f"- {ids} [{f.severity}, {crits}, {reqs}]{quote}: {f.problem}{tail} Та же проблема в других местах: {also}."


NOISE_CRITERIA = {"necessary", "singular"}
DUP_RE = re.compile(r"дублир|повторя|повторен|дважды|то же правило", re.I)


def counts(fs) -> str:
    return f"критично {sum(f.severity == 'критично' for f in fs)}, важно {sum(f.severity == 'важно' for f in fs)}, " \
           f"мелочь {sum(f.severity == 'мелочь' for f in fs)}"


def render_delta(d: dict) -> str:
    gone = {f.id for f, _ in d["closed"]}
    linked = len(d["closed"]) + len(d["remains"])
    rw = set(d["rewritten"])
    before = [f for f in d["all_old"] if set(f.req_ids) & rw]
    new_groups = group_new(d["new"])
    after = [f for f in before if f.id not in gone] + [g[0][0] for g in new_groups]
    md = ["## Дельта после ответов", "",
          f"По ответам: закрыто {len(d['closed'])} из {len(d['closed']) + len(d['remains'])} связанных замечаний, "
          f"осталось {len(d['remains'])}; новых последствий ответов: {len(new_groups)}.", "",
          f"Переписано требований: {len(d['rewritten'])} ({', '.join(d['rewritten'])}). Перепроверка: Аудитор и "
          f"Кросс-проверка на переписанных требованиях и соседних, затем сверка. Вызовов модели: {d['calls']}, "
          f"{d['seconds']} с. Замечания на переписанном тексте ссылаются на номер требования и его новую формулировку; "
          f"номера строк документа у них нет.", ""]
    if not d["judged"]:
        md += ["Оценка модели по сверке недоступна: закрытыми ничего не считаем.", ""]
    if not d["cross_ok"]:
        md += ["Кросс-проверка не ответила: новые противоречия могли остаться незамеченными.", ""]
    for title, key in (("Закрыто ответами", "closed"), ("Осталось", "remains")):
        md += [f"### {title} ({len(d[key])})", ""]
        md += [_line(f, w) for f, w in d[key]] or ["- нет"]
        md.append("")
    md += [f"### Появилось новое ({len(new_groups)})", ""]
    md += [_group_line(g) for g in new_groups] or ["- нет"]
    md.append("")
    md += [f"Не показано как шум: {d['noise']} замечаний о дублировании и единичности между переписанными "
           f"текстами этого же прогона.",
           f"Не относятся к ответам: на переписанных требованиях осталось {d['untouched']} старых замечаний, "
           f"которых ни один вопрос не касался.",
           f"На соседних требованиях повторно найдено {d['repeat_nb']} старых замечаний, без изменений; "
           f"ещё {d['other_nb']} замечаний к соседнему тексту, который не менялся, в дельту не включены.", ""]
    md += ["", f"Оценка только по изменённым требованиям (не по всему документу): было {counts(before)} "
           f"(всего {len(before)}), стало {counts(after)} (всего {len(after)}).", ""]
    return "\n".join(md)
