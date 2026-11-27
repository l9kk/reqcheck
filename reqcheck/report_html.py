import re
from html import escape
from pathlib import Path

from .model import SEVERITIES, Finding, Quote, Report
from .report_md import LEVELS, STATUS, crit_name, drop_reason, num, passport_rows, problem_parts, short_crit
from .segment import clean

SEV_CLASS = {"критично": "s-crit", "важно": "s-major", "мелочь": "s-minor"}
VERDICT_CLASS = {"Да": "v-ok", "С оговорками": "v-warn", "Нет": "v-bad"}
STATUS_CLASS = {"ok": "st-ok", "partial": "st-partial", "fail": "st-fail"}
REC_RE = re.compile(r"^\s*Вариант\s*\(([а-я])\)")


def e(s) -> str:
    return escape("" if s is None else str(s), quote=True)


def letter(i: int) -> str:
    return chr(1072 + i)


def span(q: Quote, n_lines: int) -> tuple[int, int] | None:
    if not n_lines or not q.start or q.start < 1 or q.start > n_lines:
        return None
    return q.start, min(max(q.end or q.start, q.start), n_lines)


def quote_html(q: Quote, n_lines: int, owner: str = "") -> str:
    sp = span(q, n_lines)
    loc = e(q.loc or (f"строки {q.start}-{q.end}" if q.end != q.start else f"строка {q.start}"))
    if sp:
        ref = (f'<a class="qref" href="#L{sp[0]}" data-start="{sp[0]}" data-end="{sp[1]}"'
               + (f' data-owner="{e(owner)}"' if owner else "") + f">{loc}</a>")
    else:
        ref = f'<span class="qref-none">{loc}</span>'
    return f'<blockquote class="quote"><p>«{e(clean(q.text))}»</p><footer>{ref}</footer></blockquote>'


def ranges_attr(quotes: list[Quote], n_lines: int) -> str:
    return " ".join(f"{sp[0]}-{sp[1]}" for sp in (span(q, n_lines) for q in quotes) if sp)


def finding_html(f: Finding, crit: dict, asks: dict, qnum: dict, fnum: dict, n_lines: int) -> str:
    fid = fnum[f.id]
    sev = SEV_CLASS.get(f.severity, "s-minor")
    meta = [f'<span class="sev {sev}">{e(f.severity)}</span>', f'<span class="crit">{e(crit_name(crit, f.criterion))}</span>']
    if f.req_ids:
        meta.append(f'<span class="reqs">{e(", ".join(f.req_ids))}</span>')
    if f.scope == "set":
        meta.append('<span class="tag">набор требований</span>')
    if f.edge:
        meta.append(f'<span class="tag">граничный случай {e(f.edge)}</span>')
    out = [f'<article class="finding" id="{fid}" data-sev="{e(f.severity)}" data-ranges="{ranges_attr(f.quotes, n_lines)}" tabindex="-1">',
           f'<header><button type="button" class="fsel" aria-controls="doc" title="Показать цитаты в документе">'
           f'<span class="fid">{e(f.id)}</span></button><div class="fmeta">{"".join(meta)}</div></header>']
    main, *extra = problem_parts(f.problem)
    out.append(f'<p class="problem">{e(main)}</p>')
    if extra:
        out.append('<ul class="also">' + "".join(f"<li>Также: {e(p)}</li>" for p in extra) + "</ul>")
    out += [quote_html(q, n_lines, fid) for q in f.quotes]
    dl = []
    if f.impact:
        dl.append(("Последствия", e(f.impact)))
    qs = asks.get(f.id, [])
    qlinks = ", ".join(f'<a class="qlink" href="#{qnum[x]}">{e(x)}</a>' for x in qs if x in qnum)
    if f.fix:
        dl.append(("Как исправить", e(f.fix)))
    elif qlinks:
        dl.append(("Как исправить", f"зависит от ответа на {qlinks}"))
    if f.test_hint:
        dl.append(("Тесты", e(f.test_hint)))
    if qlinks:
        dl.append(("Вопрос к автору", qlinks))
    if dl:
        out.append('<dl class="fdl">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in dl) + "</dl>")
    out.append("</article>")
    return "".join(out)


def question_html(q, i: int, fnum: dict, n_lines: int) -> str:
    rec = REC_RE.match(q.default or "")
    rec_i = ord(rec.group(1)) - 1072 if rec else -1
    meta = f'<span class="tag">Кому: {e(q.addressee)}</span>' if q.addressee else ""
    out = [f'<article class="question" id="q-{i}" tabindex="-1"><header><span class="fid">{e(q.id)}</span>{meta}</header>',
           f'<p class="qtext">{e(q.text)}</p>']
    out += [quote_html(x, n_lines) for x in q.quotes]
    dl = []
    if q.blocks:
        dl.append(("Что блокирует", e(q.blocks)))
    if q.options:
        items = "".join(f'<li{" class=rec" if j == rec_i else ""}><span class="ol">({letter(j)})</span> <span>{e(o)}</span>'
                        + ('<span class="rec-tag">рекомендация</span>' if j == rec_i else "") + "</li>"
                        for j, o in enumerate(q.options))
        dl.append(("Варианты", f'<ul class="opts">{items}</ul>'))
    if q.default:
        dl.append(("Рекомендация агента", e(q.default)))
    if q.finding_ids:
        links = ", ".join(f'<a class="flink" href="#{fnum[x]}">{e(x)}</a>' if x in fnum else e(x) for x in q.finding_ids)
        dl.append(("Закрывает замечания", links))
    if dl:
        out.append('<dl class="fdl">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in dl) + "</dl>")
    out.append("</article>")
    return "".join(out)


def table(head: list[str], rows: list[list[str]]) -> str:
    return ('<div class="tw"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")


def render_html(rep: Report, doc_lines: list[str], crit: dict | None = None) -> str:
    if crit is None:
        from .pipeline import all_criteria, load_criteria
        crit = all_criteria(load_criteria())
    p, v = rep.passport, rep.verdict
    n_lines = len(doc_lines)
    title = p.get("doc_title") or p.get("document") or "документ"
    counts = {s: sum(1 for f in rep.findings if f.severity == s) for s in SEVERITIES}
    fnum = {f.id: f"f-{i}" for i, f in enumerate(rep.findings)}
    qnum = {q.id: f"q-{i}" for i, q in enumerate(rep.questions)}
    asks: dict[str, list[str]] = {}
    for q in rep.questions:
        for fid in q.finding_ids:
            asks.setdefault(fid, []).append(q.id)
    req_with = {r for f in rep.findings for r in f.req_ids}

    line_f: dict[int, list[str]] = {}
    line_sev: dict[int, int] = {}
    for f in rep.findings:
        rank = SEVERITIES.index(f.severity) if f.severity in SEVERITIES else 2
        for q in f.quotes:
            sp = span(q, n_lines)
            if not sp:
                continue
            for n in range(sp[0], sp[1] + 1):
                if fnum[f.id] not in line_f.setdefault(n, []):
                    line_f[n].append(fnum[f.id])
                line_sev[n] = min(line_sev.get(n, 9), rank)

    status = v.get("status") or "Не проверено"
    fix_first = [x for x in v.get("fix_first") or [] if x in fnum]
    head = [f'<header class="top"><p class="kicker">Отчёт о проверке требований · ISO/IEC/IEEE 29148, IEEE 830</p>',
            f"<h1>{e(title)}</h1>",
            f'<div class="verdict {VERDICT_CLASS.get(status, "v-none")}"><p class="vline">Начинать разработку и тестирование: '
            f"<strong>{e(status)}</strong></p>" + (f'<p class="vtext">{e(v.get("text"))}</p>' if v.get("text") else "")]
    if fix_first:
        head.append('<p class="vtext">Исправить в первую очередь: '
                    + ", ".join(f'<a class="flink" href="#{fnum[x]}">{e(x)}</a>' for x in fix_first) + "</p>")
    head.append("</div>")
    stats = [("Требований", num(len(rep.requirements)), f"с замечаниями: {len(req_with)}"),
             ("Замечаний", num(len(rep.findings)), None),
             ("Вопросов к автору", num(len(rep.questions)), None),
             ("Строк в документе", num(n_lines), None)]
    sev_line = "".join(f'<span class="sev {SEV_CLASS[s]}">{e(s)}: {counts[s]}</span>' for s in SEVERITIES)
    head.append('<dl class="stats">' + "".join(
        f'<div><dt>{a}</dt><dd><span class="big">{b}</span>'
        + (f'<span class="sub">{e(c)}</span>' if c else "")
        + (f'<span class="sevs">{sev_line}</span>' if a == "Замечаний" else "") + "</dd></div>"
        for a, b, c in stats) + "</dl>")
    errs = [d for d in rep.diagnostics if d.level == "error"]
    if errs:
        head.append('<div class="diag" role="alert"><p><strong>Диагностика</strong></p><ul>' + "".join(
            f"<li><code>{e(d.code)}</code> {e(d.message)}" + (f" Что сделать: {e(d.hint)}" if d.hint else "") + "</li>"
            for d in errs) + "</ul></div>")
    head.append("</header>")

    tabs = [("main", "Документ и замечания", len(rep.findings)), ("questions", "Вопросы к автору", len(rep.questions)),
            ("set", "Проверка набора", len(rep.set_summary)), ("passport", "Паспорт прогона", None)]
    nav = ['<nav class="tabs" role="tablist" aria-label="Разделы отчёта">']
    for k, (key, label, n) in enumerate(tabs):
        nav.append(f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" aria-selected="{"true" if k == 0 else "false"}"'
                   f' data-tab="{key}">{label}' + (f' <span class="cnt">{n}</span>' if n is not None else "") + "</button>")
    nav.append("</nav>")

    doc = ['<section class="pane doc" id="doc" aria-label="Исходный документ"><div class="pane-head"><h2>Документ</h2>'
           f'<span class="muted">{e(p.get("document"))}' + (", строки, на которые ссылаются замечания, отмечены слева" if line_f else "")
           + "</span></div>"]
    if doc_lines:
        doc.append('<div class="lines" id="lines">')
        w = len(str(n_lines))
        for n, text in enumerate(doc_lines, start=1):
            fs = line_f.get(n)
            cls = "ln" + (f" q{line_sev[n]}" if fs else "")
            attrs = f' data-f="{" ".join(fs)}" tabindex="0" role="button" aria-label="Строка {n}: замечаний {len(fs)}"' if fs else ""
            doc.append(f'<div class="{cls}" id="L{n}"{attrs}><span class="no" style="min-width:{w}ch">{n}</span>'
                       f'<span class="tx">{e(text) if text.strip() else "&#8203;"}</span></div>')
        doc.append("</div>")
    else:
        doc.append('<p class="empty">Текст документа недоступен: документ не был прочитан.</p>')
    doc.append("</section>")

    fl = ['<section class="pane fl" id="findings" aria-label="Замечания"><div class="pane-head"><h2>Замечания</h2>'
          '<span class="muted" id="fcount" aria-live="polite"></span></div>']
    if rep.findings:
        fl.append('<div class="tools"><div class="seg" role="group" aria-label="Фильтр по важности">'
                  f'<button type="button" data-sev="" aria-pressed="true">Все <span class="cnt">{len(rep.findings)}</span></button>'
                  + "".join(f'<button type="button" data-sev="{s}" aria-pressed="false"><i class="dot {SEV_CLASS[s]}"></i>{s} '
                            f'<span class="cnt">{counts[s]}</span></button>' for s in SEVERITIES)
                  + '</div><input type="search" id="q" placeholder="Поиск по замечаниям" aria-label="Поиск по замечаниям" autocomplete="off">'
                  '<p class="linef" id="linef" hidden><span></span> <button type="button" id="linef-x">Сбросить</button></p></div>')
        fl.append('<div class="flist" id="flist">' + "".join(finding_html(f, crit, asks, qnum, fnum, n_lines) for f in rep.findings)
                  + '<p class="empty" id="fnone" hidden>По этому фильтру замечаний нет.</p></div>')
    else:
        fl.append('<p class="empty">Замечаний нет.</p>')
    fl.append("</section>")

    qp = ['<section class="panel" id="panel-questions" role="tabpanel" aria-labelledby="tab-questions"><h2>Вопросы к автору</h2>']
    if rep.questions:
        qp.append('<p class="muted">Без ответов на эти вопросы нельзя однозначно реализовать или протестировать требования. Порядок: по важности.</p>')
        qp += [question_html(q, i, fnum, n_lines) for i, q in enumerate(rep.questions)]
    else:
        qp.append('<p class="empty">Вопросов нет.</p>')
    qp.append("</section>")

    sp_ = ['<section class="panel" id="panel-set" role="tabpanel" aria-labelledby="tab-set"><h2>Проверка набора требований</h2>',
           '<p class="muted">Свойства набора по ISO/IEC/IEEE 29148:2018 п. 5.2.6 и спецификации по IEEE 830-1998 п. 4.3.</p>']
    if rep.set_summary:
        sp_.append(table(["Свойство", "Оценка", "Комментарий"], [
            [e(crit_name(crit, s.get("criterion", ""))),
             f'<span class="st {STATUS_CLASS.get(s.get("status"), "")}">{e(STATUS.get(s.get("status"), s.get("status")))}</span>',
             e(clean(s.get("comment", "")))] for s in rep.set_summary]))
    else:
        sp_.append('<p class="empty">Проверка набора не выполнялась.</p>')
    set_f = [f for f in rep.findings if f.scope == "set"]
    if set_f:
        sp_.append("<h3>Замечания к набору</h3>" + table(["ID", "Важность", "Свойство", "Суть"], [
            [f'<a class="flink" href="#{fnum[f.id]}">{e(f.id)}</a>', f'<span class="sev {SEV_CLASS.get(f.severity, "s-minor")}">{e(f.severity)}</span>',
             e(short_crit(crit, f.criterion)), e(problem_parts(f.problem)[0])] for f in set_f]))
    sp_.append("</section>")

    pp = ['<section class="panel" id="panel-passport" role="tabpanel" aria-labelledby="tab-passport"><h2>Паспорт прогона</h2>',
          table(["Поле", "Значение"], [[e(a), e(b if b not in (None, "") else "-")] for a, b in passport_rows(rep)])]
    if rep.trace:
        pp.append("<h3>Роли и запросы к модели</h3>" + table(["Роль", "Ответ из кэша", "Время модели, с", "Токены вход / выход"], [
            [e(t.get("role")), "да" if t.get("cached") else "нет", e(t.get("orig_seconds", "-") if t.get("cached") else t.get("seconds")),
             f'{num(t.get("in_tokens", 0))} / {num(t.get("out_tokens", 0))}'] for t in rep.trace]))
    if rep.drops:
        by: dict[str, int] = {}
        for d in rep.drops:
            k = f"{d.get('role')}: {drop_reason(d)}"
            by[k] = by.get(k, 0) + 1
        pp.append(f"<h3>Защитные проверки отбросили элементов: {len(rep.drops)}</h3><ul>"
                  + "".join(f"<li>{e(k)}: {c}</li>" for k, c in by.items()) + "</ul>")
    if rep.diagnostics:
        pp.append("<h3>Диагностика</h3><ul>" + "".join(
            f"<li><strong>{e(LEVELS.get(d.level, d.level))}</strong> <code>{e(d.code)}</code>: {e(d.message)}"
            + (f" Что сделать: {e(d.hint)}" if d.hint else "") + "</li>" for d in rep.diagnostics) + "</ul>")
    pp.append("</section>")

    body = ("".join(head) + "".join(nav)
            + '<section class="panel" id="panel-main" role="tabpanel" aria-labelledby="tab-main"><div class="work">'
            + "".join(doc) + "".join(fl) + "</div></section>" + "".join(qp) + "".join(sp_) + "".join(pp))
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{e(title)}: отчёт о проверке требований</title><style>{CSS}</style></head>"
            f'<body><div class="wrap">{body}</div><script>{JS}</script></body></html>\n')


def write_html(rep: Report, doc_lines: list[str], path, crit: dict | None = None) -> Path:
    path = Path(path)
    path.write_text(render_html(rep, doc_lines, crit), encoding="utf-8")
    return path


CSS = """
:root{--bg:#f7f7f5;--surface:#fff;--ink:#1c2024;--muted:#5d6670;--line:#dfe2e5;--soft:#eef0f2;
--accent:#1f5c99;--accent-soft:#e3edf7;--hl:#fff1bf;--hl-edge:#c99a06;
--crit:#a3221b;--crit-bg:#fbe9e7;--major:#7a4d00;--major-bg:#fbf0d9;--minor:#4a5562;--minor-bg:#eceff2;
--ok:#1e6b3a;--ok-bg:#e4f3e8;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--surface:#1a1d21;--ink:#e4e6e8;--muted:#9aa3ad;--line:#2d3238;--soft:#22262b;
--accent:#7fb0e6;--accent-soft:#1d2d40;--hl:#3b3216;--hl-edge:#d9a92a;
--crit:#ff9c92;--crit-bg:#3a1d1b;--major:#f0c46a;--major-bg:#352a14;--minor:#b6c0cb;--minor-bg:#262b31;
--ok:#86d19e;--ok-bg:#183022;color-scheme:dark}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:20px 24px 48px}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,input:focus-visible,.ln:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1{font-size:22px;line-height:1.25;margin:2px 0 14px;font-weight:650}
h2{font-size:15px;margin:0;font-weight:650}
h3{font-size:14px;margin:22px 0 8px;font-weight:650}
.kicker{margin:0;color:var(--muted);font-size:12.5px}
.muted{color:var(--muted);font-size:12.5px}
.verdict{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--minor);border-radius:6px;padding:12px 16px;margin-bottom:14px}
.verdict.v-bad{border-left-color:var(--crit)}.verdict.v-warn{border-left-color:var(--major)}.verdict.v-ok{border-left-color:var(--ok)}
.vline{margin:0;font-size:16px}.v-bad .vline strong{color:var(--crit)}.v-warn .vline strong{color:var(--major)}.v-ok .vline strong{color:var(--ok)}
.vtext{margin:6px 0 0;color:var(--ink)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0 0 14px}
.stats>div{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:10px 14px}
.stats dt{color:var(--muted);font-size:12.5px}.stats dd{margin:2px 0 0;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px}
.big{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}.sub{color:var(--muted);font-size:12.5px}
.sevs{display:flex;flex-wrap:wrap;gap:4px}
.diag{background:var(--crit-bg);border:1px solid var(--line);border-radius:6px;padding:10px 16px;margin-bottom:14px}
.diag p{margin:0}.diag ul{margin:6px 0 0;padding-left:18px}
.sev,.tag,.st{display:inline-block;font-size:12px;line-height:18px;padding:0 7px;border-radius:4px;white-space:nowrap}
.s-crit{color:var(--crit);background:var(--crit-bg)}.s-major{color:var(--major);background:var(--major-bg)}.s-minor{color:var(--minor);background:var(--minor-bg)}
.tag{color:var(--muted);background:var(--soft)}
.st-fail{color:var(--crit);background:var(--crit-bg)}.st-partial{color:var(--major);background:var(--major-bg)}.st-ok{color:var(--ok);background:var(--ok-bg)}
.tabs{display:flex;flex-wrap:wrap;gap:2px;border-bottom:1px solid var(--line);margin-bottom:14px}
.tabs button{font:inherit;background:none;border:0;border-bottom:2px solid transparent;margin-bottom:-1px;padding:8px 12px;color:var(--muted);cursor:pointer}
.tabs button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
.tabs button:hover{color:var(--ink)}
.cnt{color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums}
.work{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start}
.pane{background:var(--surface);border:1px solid var(--line);border-radius:6px;position:sticky;top:8px;height:calc(100vh - 16px);display:flex;flex-direction:column;min-height:0}
.pane-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;padding:10px 14px;border-bottom:1px solid var(--line)}
.lines{overflow:auto;flex:1;min-height:0;padding:6px 0;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;position:relative}
.ln{display:flex;gap:12px;padding:0 14px 0 0;border-left:3px solid transparent}
.ln .no{flex:none;text-align:right;color:var(--muted);user-select:none;padding-left:8px;opacity:.75}
.ln .tx{white-space:pre-wrap;overflow-wrap:anywhere;flex:1;min-width:0}
.ln[data-f]{cursor:pointer}
.ln.q0{border-left-color:var(--crit)}.ln.q1{border-left-color:var(--major)}.ln.q2{border-left-color:var(--minor)}
.ln[data-f]:hover{background:var(--soft)}
.ln.hl{background:var(--hl)}.ln.hl .no{color:var(--ink);opacity:1}
.ln.pick{box-shadow:inset 0 0 0 1px var(--hl-edge)}
.fl .tools{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.seg{display:flex;flex-wrap:wrap;gap:4px}
.seg button,.linef button{font:inherit;font-size:12.5px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:5px;padding:3px 9px;cursor:pointer;display:inline-flex;align-items:center;gap:5px}
.seg button[aria-pressed=true]{border-color:var(--accent);background:var(--accent-soft);color:var(--ink)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot.s-crit{background:var(--crit)}.dot.s-major{background:var(--major)}.dot.s-minor{background:var(--minor)}
#q{font:inherit;flex:1 1 180px;min-width:0;padding:5px 9px;border:1px solid var(--line);border-radius:5px;background:var(--surface);color:var(--ink)}
.linef{margin:0;flex-basis:100%;font-size:12.5px;color:var(--muted);display:flex;align-items:center;gap:8px}
.flist{overflow:auto;flex:1;min-height:0;padding:10px 14px 24px}
.finding,.question{border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin-bottom:10px;background:var(--surface);transition:opacity .15s ease}
.finding.active{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.finding header,.question header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}
.fsel{font:inherit;background:none;border:0;padding:0;cursor:pointer;color:var(--accent)}
.fid{font-weight:650;font-variant-numeric:tabular-nums}
.fsel .fid{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}
.fmeta{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.crit,.reqs{font-size:12.5px;color:var(--muted)}
.problem,.qtext{margin:8px 0 6px}
.also{margin:0 0 6px;padding-left:18px;color:var(--ink)}
.quote{margin:6px 0;padding:4px 10px;border-left:2px solid var(--line);color:var(--ink);background:var(--soft);border-radius:0 4px 4px 0}
.quote p{margin:0}.quote footer{font-size:12px;color:var(--muted)}
.fdl{margin:6px 0 0;display:grid;grid-template-columns:max-content 1fr;gap:4px 12px}
.fdl dt{color:var(--muted);font-size:12.5px;padding-top:1px}.fdl dd{margin:0;min-width:0}
.opts{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.opts li{padding:4px 8px;border:1px solid var(--line);border-radius:4px}
.opts li.rec{border-color:var(--accent)}
.ol{font-weight:600}
.rec-tag{margin-left:6px;font-size:12px;color:var(--accent)}
.panel>.question{max-width:980px}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--surface);max-width:1100px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;vertical-align:top;padding:7px 12px;border-bottom:1px solid var(--line)}
th{font-size:12.5px;color:var(--muted);font-weight:600;background:var(--soft)}
tr:last-child td{border-bottom:0}
.empty{color:var(--muted);padding:16px 14px;margin:0}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.panel ul{padding-left:18px}
@media (max-width:900px){.wrap{padding:14px 16px 40px}.work{grid-template-columns:minmax(0,1fr)}
.pane{position:static;height:auto}.doc .lines{max-height:55vh}.flist{overflow:visible}
.fdl{grid-template-columns:1fr}.fdl dt{padding-top:4px}h1{font-size:19px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

JS = r"""
(function(){
var d=document,reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
var tabs=[].slice.call(d.querySelectorAll('[data-tab]'));
function show(k){tabs.forEach(function(b){var on=b.getAttribute('data-tab')===k;b.setAttribute('aria-selected',on?'true':'false');
var p=d.getElementById('panel-'+b.getAttribute('data-tab'));if(p)p.hidden=!on;});}
tabs.forEach(function(b){b.addEventListener('click',function(){show(b.getAttribute('data-tab'));});});
show('main');
var lines=d.getElementById('lines'),flist=d.getElementById('flist');
var fs=[].slice.call(d.querySelectorAll('.finding'));
var sev='',query='',line=0;
function norm(s){return s.toLowerCase().replace(/ё/g,'е');}
fs.forEach(function(f){f._t=norm(f.textContent);f._r=(f.getAttribute('data-ranges')||'').split(' ').filter(Boolean).map(function(x){var a=x.split('-');return[+a[0],+a[1]];});});
function covers(f,n){return f._r.some(function(r){return n>=r[0]&&n<=r[1];});}
var cnt=d.getElementById('fcount'),none=d.getElementById('fnone'),lf=d.getElementById('linef');
function apply(){var shown=0;fs.forEach(function(f){var ok=(!sev||f.getAttribute('data-sev')===sev)&&(!query||f._t.indexOf(query)>=0)&&(!line||covers(f,line));f.hidden=!ok;if(ok)shown++;});
if(cnt)cnt.textContent=fs.length?('показано '+shown+' из '+fs.length):'';if(none)none.hidden=shown>0;
if(lf){lf.hidden=!line;if(line)lf.firstChild.textContent='Только замечания к строке '+line+'.';}}
[].forEach.call(d.querySelectorAll('.seg button'),function(b){b.addEventListener('click',function(){sev=b.getAttribute('data-sev');
[].forEach.call(d.querySelectorAll('.seg button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});apply();});});
var qi=d.getElementById('q');if(qi)qi.addEventListener('input',function(){query=norm(qi.value.trim());apply();});
var lx=d.getElementById('linef-x');if(lx)lx.addEventListener('click',function(){line=0;clearPick();apply();});
function L(n){return d.getElementById('L'+n);}
function clearHl(){[].forEach.call(d.querySelectorAll('.ln.hl'),function(x){x.classList.remove('hl');});}
function clearPick(){[].forEach.call(d.querySelectorAll('.ln.pick'),function(x){x.classList.remove('pick');});}
function scrollIn(box,el,center){if(!box||!el)return;var y=el.offsetTop-(center?box.clientHeight/3:8);
box.scrollTo?box.scrollTo({top:Math.max(0,y),behavior:reduce?'auto':'smooth'}):(box.scrollTop=y);
if(window.matchMedia&&matchMedia('(max-width: 900px)').matches){box.scrollIntoView({block:'nearest',behavior:reduce?'auto':'smooth'});}}
function select(f,at){fs.forEach(function(x){x.classList.toggle('active',x===f);});clearHl();var first=0;
f._r.forEach(function(r){for(var n=r[0];n<=r[1];n++){var el=L(n);if(el)el.classList.add('hl');}if(!first)first=r[0];});
var target=at||first;if(target)scrollIn(lines,L(target),true);}
fs.forEach(function(f){var b=f.querySelector('.fsel');if(b)b.addEventListener('click',function(){select(f);});});
d.addEventListener('click',function(ev){var a=ev.target.closest&&ev.target.closest('a');if(!a)return;
if(a.classList.contains('qref')){ev.preventDefault();var o=a.getAttribute('data-owner'),s=+a.getAttribute('data-start'),en=+a.getAttribute('data-end');
show('main');if(o){select(d.getElementById(o),s);}else{fs.forEach(function(x){x.classList.remove('active');});clearHl();for(var n=s;n<=en;n++){var el=L(n);if(el)el.classList.add('hl');}scrollIn(lines,L(s),true);}return;}
if(a.classList.contains('flink')){ev.preventDefault();var f=d.getElementById(a.getAttribute('href').slice(1));if(!f)return;
show('main');sev='';query='';line=0;if(qi)qi.value='';clearPick();[].forEach.call(d.querySelectorAll('.seg button'),function(x){x.setAttribute('aria-pressed',x.getAttribute('data-sev')===''?'true':'false');});
apply();select(f);scrollIn(flist,f,false);f.focus({preventScroll:true});return;}
if(a.classList.contains('qlink')){ev.preventDefault();var q=d.getElementById(a.getAttribute('href').slice(1));if(!q)return;
show('questions');q.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});q.focus({preventScroll:true});}});
function pickLine(el){var n=+el.id.slice(1);line=n;clearPick();el.classList.add('pick');apply();
var vis=fs.filter(function(f){return !f.hidden;});if(vis.length===1)select(vis[0],n);else{fs.forEach(function(x){x.classList.remove('active');});}
if(flist){flist.scrollTop=0;if(window.matchMedia&&matchMedia('(max-width: 900px)').matches)d.getElementById('findings').scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});}}
if(lines){lines.addEventListener('click',function(ev){var el=ev.target.closest('.ln[data-f]');if(el)pickLine(el);});
lines.addEventListener('keydown',function(ev){if(ev.key!=='Enter'&&ev.key!==' ')return;var el=ev.target.closest('.ln[data-f]');if(el){ev.preventDefault();pickLine(el);}});}
apply();
})();
"""
