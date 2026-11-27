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
SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«\"(])")
MD_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
VERDICT_GLYPH = {"Да": "✓", "С оговорками": "!", "Нет": "✕"}
VERDICT_PREFIX_RE = re.compile(r"^\s*Начинать разработку и тестирование[^:.]*:\s*")


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
        short = f"строки {sp[0]}-{sp[1]}" if sp[1] != sp[0] else f"строка {sp[0]}"
        ref = (f'<a class="qref" href="#L{sp[0]}" data-start="{sp[0]}" data-end="{sp[1]}"'
               + (f' data-owner="{e(owner)}"' if owner else "") + f' title="{loc}">{short}</a>')
    else:
        ref = f'<span class="qref-none">{loc}</span>'
    return f'<blockquote class="quote"><p>«{e(clean(q.text))}»</p><footer>{ref}</footer></blockquote>'


def first_sentence(s: str) -> tuple[str, str]:
    s = (s or "").strip()
    m = SENT_RE.search(s)
    return (s[:m.start()].strip(), s[m.end():].strip()) if m else (s, "")


def short_title(f: Finding, max_words: int = 6) -> str:
    s = first_sentence(problem_parts(f.problem)[0])[0]
    s = re.sub(r"\s*\([^()]*\)", "", s)
    s = re.sub(r"[«»\"`*]", "", s)
    words = [w for w in s.split() if w not in ("-", "–", "—")]
    clause: list[str] = []
    for w in words:
        clause.append(w)
        if len(clause) >= 3 and re.search(r"[:;,.!?]$", w):
            break
    cut = clause[:max_words]
    t = " ".join(cut).rstrip(",;:.!?—–- ")
    return t + ("…" if len(cut) < len(words) and not re.search(r"[:;,.!?]$", cut[-1] if cut else "") else "")


def md_inline(text: str) -> str:
    t = e(text.rstrip())
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t.replace("**", "")


def md_line(text: str) -> tuple[str, str]:
    if not text.strip():
        return "blank", ""
    m = re.match(r"^\s*(#{1,6})\s+(.*)$", text)
    if m:
        return f"h{len(m.group(1))}", md_inline(m.group(2).rstrip("# "))
    if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", text):
        return "hr", ""
    if MD_SEP_RE.match(text):
        return "sep", ""
    if re.match(r"^\s*\|.*\|\s*$", text):
        cells = [c.strip() for c in text.strip().strip("|").split("|")]
        return "tr", "".join(f'<span class="c">{md_inline(c)}</span>' for c in cells)
    m = re.match(r"^\s*[-*+]\s+(.*)$", text)
    if m:
        return "li", f'<span class="bul" aria-hidden="true"></span>{md_inline(m.group(1))}'
    m = re.match(r"^\s*>\s?(.*)$", text)
    if m:
        return "bq", md_inline(m.group(1))
    return "p", md_inline(text)


def ranges_attr(quotes: list[Quote], n_lines: int) -> str:
    return " ".join(f"{sp[0]}-{sp[1]}" for sp in (span(q, n_lines) for q in quotes) if sp)


def finding_html(f: Finding, crit: dict, asks: dict, qnum: dict, fnum: dict, n_lines: int) -> str:
    fid = fnum[f.id]
    sev = SEV_CLASS.get(f.severity, "s-minor")
    meta = [f'<span class="crit">{e(crit_name(crit, f.criterion))}</span>']
    if f.req_ids:
        meta.append(f'<span class="reqs">{e(", ".join(f.req_ids))}</span>')
    if f.scope == "set":
        meta.append('<span class="tag">набор требований</span>')
    if f.edge:
        meta.append(f'<span class="tag">граничный случай {e(f.edge)}</span>')
    main, *extra = problem_parts(f.problem)
    lead, rest = first_sentence(main)
    out = [f'<article class="finding" id="{fid}" data-sev="{e(f.severity)}" data-ranges="{ranges_attr(f.quotes, n_lines)}" tabindex="-1">',
           f'<header><button type="button" class="fsel" aria-controls="doc" title="Показать цитаты в документе">'
           f'<span class="fmeta-l"><span class="fid">{e(f.id)}</span><span class="sev {sev}"><i class="dot {sev}" aria-hidden="true"></i>{e(f.severity)}</span></span>'
           f'<span class="ftitle">{e(lead)}</span></button></header>']
    out += [quote_html(q, n_lines, fid) for q in f.quotes]
    more = []
    if rest:
        more.append(f'<p class="prest">{e(rest)}</p>')
    if extra:
        more.append('<ul class="also">' + "".join(f"<li>Также: {e(p)}</li>" for p in extra) + "</ul>")
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
    dl.append(("Критерий", f'<span class="fmeta">{"".join(meta)}</span>'))
    more.append('<dl class="fdl">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in dl) + "</dl>")
    out.append('<details class="more"><summary>Подробнее</summary>' + "".join(more) + "</details>")
    out.append("</article>")
    return "".join(out)


def chip_html(f: Finding, fnum: dict) -> str:
    sev = SEV_CLASS.get(f.severity, "s-minor")
    lab = "" if f.severity == "критично" else f' · <span class="clab">{e(f.severity)}</span>'
    return (f'<a class="flink chip" href="#{fnum[f.id]}" data-sev="{e(f.severity)}"><i class="dot {sev}" aria-hidden="true"></i>'
            f'<b>{e(f.id)}</b>{lab}<span class="ct">{e(short_title(f))}</span>'
            f'<span class="ctl" aria-hidden="true">{e(first_sentence(problem_parts(f.problem)[0])[0])}</span></a>')


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


def table(head: list[str], rows: list[list[str]], cls: str = "") -> str:
    return (f'<div class="tw{" " + cls if cls else ""}"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f'<td data-label="{e(h)}">{c}</td>' for h, c in zip(head, r)) + "</tr>" for r in rows)
            + "</tbody></table></div>")


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
    by_id = {f.id: f for f in rep.findings}
    fix_first = [by_id[x] for x in v.get("fix_first") or [] if x in fnum]
    ff_crit = [f for f in fix_first if f.severity == "критично"]
    ff_rest = [f for f in fix_first if f.severity != "критично"]
    vtext = v.get("text") or ""
    vshort = VERDICT_PREFIX_RE.sub("", vtext)
    if vshort != vtext and vshort:
        vshort = vshort[0].upper() + vshort[1:]
    glyph = VERDICT_GLYPH.get(status, "?")
    sev_line = "".join(f'<span class="sev {SEV_CLASS[s]}">{e(s)}: {counts[s]}</span>' for s in SEVERITIES)
    stats = ('<dl class="stats">'
             f'<div><dt>Требований</dt><dd><span class="big">{num(len(rep.requirements))}</span>'
             f'<span class="sub">, с замечаниями {num(len(req_with))}</span></dd></div>'
             f'<div><dt>Замечаний</dt><dd><span class="big">{num(len(rep.findings))}</span>'
             f'<span class="sevs vh">{sev_line}</span></dd></div>'
             f'<div><dt>Вопросов к автору</dt><dd><span class="big">{num(len(rep.questions))}</span></dd></div></dl>')
    head = ['<header class="top"><div class="titlebar"><div class="tt">'
            f'<h1>{e(title)}</h1><p class="kicker">Отчёт о проверке требований · ISO/IEC/IEEE 29148, IEEE 830</p></div>'
            f"{stats}</div>",
            f'<div class="verdict {VERDICT_CLASS.get(status, "v-none")}"><p class="vline">Начинать разработку и тестирование: '
            f'<span class="pill"><span class="pg" aria-hidden="true">{glyph}</span><strong>{e(status)}</strong></span></p>'
            + (f'<p class="vtext">{e(vshort)}</p>' if vshort else "")]
    if fix_first:
        groups = []
        if ff_crit:
            groups.append(f'<div class="ffg"><span class="ffl vh">Критично · {len(ff_crit)}</span><div class="chips">'
                          + "".join(chip_html(f, fnum) for f in ff_crit) + "</div></div>")
        if ff_rest:
            groups.append(f'<details class="ffg ffmore"><summary class="ffl">Ещё в первую очередь · {len(ff_rest)}</summary><div class="chips">'
                          + "".join(chip_html(f, fnum) for f in ff_rest) + "</div></details>")
        head.append('<div class="ff"><p class="ffh vh">Исправить в первую очередь</p>' + "".join(groups) + "</div>")
    head.append("</div>")
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
           f'<span class="muted">{e(p.get("document"))}' + (", строки с замечаниями отмечены слева" if line_f else "")
           + '</span><button type="button" class="dtog" id="dtog" aria-expanded="false" aria-controls="lines">Показать документ</button></div>']
    if doc_lines:
        doc.append('<div class="lines" id="lines">')
        w = len(str(n_lines))
        kinds = [md_line(t) for t in doc_lines]
        for n, text in enumerate(doc_lines, start=1):
            fs = line_f.get(n)
            kind, md = kinds[n - 1]
            if kind == "tr" and n < n_lines and kinds[n][0] == "sep":
                kind = "th"
            cls = f"ln md-{kind}" + (f" q{line_sev[n]}" if fs else "")
            attrs = f' data-f="{" ".join(fs)}" tabindex="0" role="button" aria-label="Строка {n}: замечаний {len(fs)}"' if fs else ""
            if kind not in ("blank", "sep", "hr"):
                attrs += f' data-md="{e(md)}"'
            doc.append(f'<div class="{cls}" id="L{n}"{attrs}><span class="no" style="min-width:{w}ch">{n}</span>'
                       f'<span class="tx">{e(text) if text.strip() else "&#8203;"}</span></div>')
        doc.append("</div>")
    else:
        doc.append('<p class="empty">Текст документа недоступен: документ не был прочитан.</p>')
    doc.append("</section>")

    crit_n = counts["критично"]
    fl = ['<section class="pane fl" id="findings" aria-label="Замечания"><div class="pane-head"><h2>Замечания</h2>'
          '<span class="vh" id="fcount" aria-live="polite"></span></div>']
    if rep.findings:
        fl.append(f'<div class="tools"><div class="seg" role="group" aria-label="Фильтр по важности" data-default="{"критично" if crit_n else ""}">'
                  f'<button type="button" data-sev="" aria-pressed="{"false" if crit_n else "true"}">Все <span class="cnt">{len(rep.findings)}</span></button>'
                  + "".join(f'<button type="button" data-sev="{s}" aria-pressed="{"true" if s == "критично" and crit_n else "false"}">'
                            f'<i class="dot {SEV_CLASS[s]}"></i>{s}<span class="cnt vh"> {counts[s]}</span></button>' for s in SEVERITIES)
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
          table(["Поле", "Значение"], [[e(a), e(b if b not in (None, "") else "-")] for a, b in passport_rows(rep)], "kv")]
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
            + "".join(fl) + "".join(doc) + "</div></section>" + "".join(qp) + "".join(sp_) + "".join(pp))
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">'
            f"<title>{e(title)}: отчёт о проверке требований</title><style>{CSS}</style></head>"
            f'<body><div class="wrap">{body}</div><script>{JS}</script></body></html>\n')


def write_html(rep: Report, doc_lines: list[str], path, crit: dict | None = None) -> Path:
    path = Path(path)
    path.write_text(render_html(rep, doc_lines, crit), encoding="utf-8")
    return path


CSS = """
:root{--bg:#f7f7f5;--surface:#fff;--raise:#f3f4f6;--ink:#1c2024;--muted:#5d6670;--line:#dfe2e5;--soft:#eef0f2;
--accent:#1f5c99;--accent-soft:#e3edf7;--hl:#fff1bf;--hl-edge:#c99a06;
--crit:#a3221b;--crit-bg:#fbe9e7;--major:#7a4d00;--major-bg:#fbf0d9;--minor:#4a5562;--minor-bg:#eceff2;
--ok:#1e6b3a;--ok-bg:#e4f3e8;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--surface:#1a1d21;--raise:#24282e;--ink:#e4e6e8;--muted:#9aa3ad;--line:#2d3238;--soft:#22262b;
--accent:#7fb0e6;--accent-soft:#1d2d40;--hl:#3b3216;--hl-edge:#d9a92a;
--crit:#ffaba3;--crit-bg:#3a1d1b;--major:#f0c46a;--major-bg:#352a14;--minor:#b6c0cb;--minor-bg:#262b31;
--ok:#86d19e;--ok-bg:#183022;color-scheme:dark}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;overflow-x:hidden}
.wrap{max-width:1600px;margin:0 auto;padding:20px 24px 48px}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible,.ln:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1{font-size:20px;line-height:1.3;margin:0;font-weight:650;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:15px;margin:0;font-weight:650}
h3{font-size:14px;margin:22px 0 8px;font-weight:650}
.kicker{margin:2px 0 0;color:var(--muted);font-size:12.5px}
.muted{color:var(--muted);font-size:12.5px}
.vh,.chip .ct{position:absolute!important;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.titlebar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:8px 24px;margin:4px 0 16px}
.tt{min-width:0;flex:1 1 420px}
.stats{display:flex;flex-wrap:wrap;gap:4px 20px;margin:0;font-size:13px;color:var(--muted)}
.stats>div{display:flex;align-items:baseline;gap:6px;white-space:nowrap}
.stats dd{margin:0;display:flex;align-items:baseline}
.big{font-size:15px;font-weight:650;color:var(--ink);font-variant-numeric:tabular-nums}.sub{color:var(--muted)}
.sub .big{font-size:inherit;font-weight:inherit}
.verdict{--vc:var(--minor);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px 22px 14px;margin-bottom:18px}
.verdict.v-bad{--vc:var(--crit)}.verdict.v-warn{--vc:var(--major)}.verdict.v-ok{--vc:var(--ok)}
.vline{margin:0;font-size:22px;line-height:1.3;font-weight:600;letter-spacing:-.01em;display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:16px;line-height:1;padding:6px 12px 6px 10px;border-radius:999px;color:var(--minor);background:var(--minor-bg)}
.pill strong{font-weight:650}.pg{font-size:14px;font-weight:700}
.v-bad .pill{color:var(--crit);background:var(--crit-bg)}.v-warn .pill{color:var(--major);background:var(--major-bg)}.v-ok .pill{color:var(--ok);background:var(--ok-bg)}
.vtext{margin:6px 0 0;color:var(--muted);font-size:15px;max-width:none;text-wrap:pretty}
.ff{margin-top:12px;display:grid;gap:6px}
.ffg>.chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,520px),1fr));gap:2px 20px;margin:0 -8px}
.ffmore>summary{cursor:pointer;color:var(--accent);font-size:13px;width:max-content;max-width:100%;padding:2px 0}
.ffmore[open]>summary{margin-bottom:2px}
.chip{min-width:0;display:flex;align-items:baseline;gap:8px;font-size:14px;line-height:20px;padding:5px 8px;border-radius:6px;color:var(--ink);text-decoration:none}
.chip:hover{background:var(--soft)}
.chip .dot{align-self:center}
.chip b{font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap;min-width:3.2em}
.chip .clab{color:var(--muted);font-weight:500;white-space:nowrap}
.chip .ctl{min-width:0;overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;text-wrap:pretty}
.chip:hover .ctl{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
.diag{background:var(--crit-bg);border:1px solid var(--line);border-radius:6px;padding:10px 16px;margin-bottom:14px}
.diag p{margin:0}.diag ul{margin:6px 0 0;padding-left:18px}
.sev,.tag,.st{display:inline-block;font-size:12px;line-height:18px;padding:0 7px;border-radius:4px;white-space:nowrap}
.s-crit{color:var(--crit);background:var(--crit-bg)}.s-major{color:var(--major);background:var(--major-bg)}.s-minor{color:var(--minor);background:var(--minor-bg)}
.tag{color:var(--muted);background:var(--soft)}
.st-fail{color:var(--crit);background:var(--crit-bg)}.st-partial{color:var(--major);background:var(--major-bg)}.st-ok{color:var(--ok);background:var(--ok-bg)}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:14px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs button{font:inherit;background:none;border:0;border-bottom:2px solid transparent;margin-bottom:-1px;padding:8px 12px;color:var(--muted);cursor:pointer;white-space:nowrap;flex:none}
.tabs button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
.tabs button:hover{color:var(--ink)}
.cnt{color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums}
.work{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:start}
.work>.doc{order:-1}
.pane{background:var(--surface);border:1px solid var(--line);border-radius:6px;position:sticky;top:8px;height:calc(100vh - 16px);display:flex;flex-direction:column;min-height:0}
.pane-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;padding:10px 14px;border-bottom:1px solid var(--line)}
.dtog{display:none}
.lines{overflow:auto;flex:1;min-height:0;padding:6px 0;font:14px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;position:relative}
.ln{display:flex;gap:12px;padding:0 14px 0 0;border-left:4px solid transparent}
.ln .no{flex:none;text-align:right;color:var(--muted);user-select:none;padding-left:8px;opacity:.75;font-size:12px;font-variant-numeric:tabular-nums;padding-top:2px}
.ln .tx{white-space:pre-wrap;overflow-wrap:anywhere;flex:1;min-width:0}
.ln .tx.r{white-space:normal}
.md-h1 .tx.r{font-size:18px;font-weight:650;padding-top:4px}
.md-h2 .tx.r{font-size:16px;font-weight:650;padding-top:8px}
.md-h3 .tx.r,.md-h4 .tx.r,.md-h5 .tx.r,.md-h6 .tx.r{font-weight:650;padding-top:4px}
.md-tr .tx.r,.md-th .tx.r{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,3fr);gap:0 12px;border-bottom:1px solid var(--soft)}
.md-th .tx.r{color:var(--muted);font-size:12.5px;font-weight:600}
.tx.r .c:only-child{grid-column:1/-1}
.md-sep .tx,.md-hr .tx{font-size:0;line-height:0;align-self:center;border-top:1px solid var(--line);height:0}
.md-sep,.md-blank{height:8px;overflow:hidden}.md-sep .no,.md-blank .no,.md-hr .no{visibility:hidden}
.md-li .tx.r{padding-left:14px;position:relative}
.bul{position:absolute;left:3px;top:.68em;width:5px;height:5px;border-radius:50%;background:var(--muted)}
.md-bq .tx.r{color:var(--muted);border-left:2px solid var(--line);padding-left:8px}
.tx code,.quote code{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--soft);padding:0 3px;border-radius:3px}
.ln[data-f]{cursor:pointer}
.ln.q0{border-left-color:var(--crit);background:color-mix(in srgb,var(--crit) 5%,transparent)}
.ln.q1{border-left-color:var(--major);background:color-mix(in srgb,var(--major) 5%,transparent)}
.ln.q2{border-left-color:var(--minor);background:color-mix(in srgb,var(--minor) 8%,transparent)}
.ln[data-f]:hover{background:var(--soft)}
.ln.hl{background:var(--hl)}.ln.hl .no{color:var(--ink);opacity:1}
.ln.pick{box-shadow:inset 0 0 0 1px var(--hl-edge)}
.fl .tools{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.seg{display:flex;flex-wrap:wrap;gap:4px}
.seg button,.linef button,.dtog{font:inherit;font-size:12.5px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:5px;padding:3px 9px;cursor:pointer;align-items:center;gap:5px}
.seg button,.linef button{display:inline-flex}
.seg button[aria-pressed=true]{border-color:var(--accent);background:var(--accent-soft);color:var(--ink)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
.dot.s-crit{background:var(--crit)}.dot.s-major{background:var(--major)}.dot.s-minor{background:var(--minor)}
#q{font:inherit;flex:1 1 180px;min-width:0;padding:5px 9px;border:1px solid var(--line);border-radius:5px;background:var(--surface);color:var(--ink)}
.linef{margin:0;flex-basis:100%;font-size:12.5px;color:var(--muted);display:flex;align-items:center;gap:8px}
.flist{overflow:auto;flex:1;min-height:0;padding:10px 14px 24px}
.question{border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:10px;background:var(--surface)}
.finding{padding:14px 10px 12px;margin:0 -10px;border-radius:8px;border-top:1px solid var(--soft)}
.finding:first-of-type,.finding.active,.finding.active+.finding{border-top-color:transparent}
.finding.active{background:var(--accent-soft)}
.question header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}
.finding header{display:block}
.fsel{font:inherit;background:none;border:0;padding:0;margin:0;cursor:pointer;color:inherit;text-align:left;display:block;width:100%;border-radius:4px}
.fmeta-l{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--muted);margin-bottom:3px}
.fmeta-l .sev{background:none;padding:0;display:inline-flex;align-items:center;gap:5px;color:var(--muted)}
.ftitle{display:block;font-size:15px;line-height:1.45;font-weight:600;max-width:75ch;text-wrap:pretty}
.fsel:hover .ftitle{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;text-decoration-color:var(--muted)}
.fid{font-weight:650;font-variant-numeric:tabular-nums}
.fmeta{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.crit,.reqs{font-size:12.5px;color:var(--muted)}
.qtext{margin:8px 0 6px;max-width:75ch}
.prest{margin:6px 0;max-width:75ch}
.also{margin:0 0 6px;padding-left:18px;color:var(--ink);max-width:75ch}
.quote{margin:8px 0;padding:7px 12px;color:var(--ink);background:var(--raise);border-radius:6px;max-width:75ch}
.quote p{margin:0;font-size:13.5px}.quote footer{font-size:12px;color:var(--muted);margin-top:2px}
.more{margin-top:4px}
.more>summary{cursor:pointer;color:var(--accent);font-size:12.5px;width:max-content;list-style-position:inside}
.more[open]>summary{margin-bottom:4px}
.fdl{margin:6px 0 0;display:grid;grid-template-columns:max-content 1fr;gap:4px 12px}
.fdl dt{color:var(--muted);font-size:12.5px;padding-top:1px}.fdl dd{margin:0;min-width:0;max-width:75ch}
.opts{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.opts li{padding:4px 8px;border:1px solid var(--line);border-radius:4px}
.opts li.rec{border-color:var(--accent)}
.ol{font-weight:600}
.rec-tag{margin-left:6px;font-size:12px;color:var(--accent)}
.panel>.question{max-width:980px}
.panel>.muted{max-width:75ch}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--surface);max-width:1100px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;vertical-align:top;padding:7px 12px;border-bottom:1px solid var(--line)}
th{font-size:12.5px;color:var(--muted);font-weight:600;background:var(--soft)}
tr:last-child td{border-bottom:0}
.empty{color:var(--muted);padding:16px 14px;margin:0}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.panel ul{padding-left:18px}
@media (max-width:767px){.wrap{padding:14px 16px 40px}.work{grid-template-columns:minmax(0,1fr)}.work>.doc{order:0}
.pane{position:static;height:auto}.doc .lines{max-height:60vh}.flist{overflow:visible}
.doc:not(.open) .lines{display:none}.doc:not(.open) .pane-head{border-bottom:0}
.dtog{display:inline-flex;margin-left:auto}
.vline{font-size:17px;gap:4px 8px}.pill{font-size:14px;padding:4px 9px 4px 8px}.verdict{padding:12px 12px 8px;margin-bottom:14px}.vtext{font-size:13.5px}
.ffg>.chips{display:flex;flex-wrap:wrap;gap:4px;margin:0}.chip{padding:3px 8px;font-size:13.5px;border:1px solid var(--line)}.chip b{min-width:0}.chip .ctl{display:none}.kicker{display:none}
.titlebar{margin-bottom:12px}.stats{gap:2px 14px}
.fdl{grid-template-columns:1fr}.fdl dt{padding-top:4px}
.tabs{margin-left:-16px;margin-right:-16px;padding:0 16px}
.tabs.more-r{-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 40px),transparent);mask-image:linear-gradient(to right,#000 calc(100% - 40px),transparent)}
.md-tr .tx.r,.md-th .tx.r{grid-template-columns:minmax(0,1fr)}}
@media (max-width:600px){.tw thead{display:none}.tw table,.tw tbody,.tw tr,.tw td{display:block}
.tw tr{border-bottom:1px solid var(--line);padding:6px 0}.tw tr:last-child{border-bottom:0}.tw td{border:0;padding:2px 12px}
.tw td::before{content:attr(data-label);display:block;font-size:12px;color:var(--muted)}
.tw.kv td::before{content:none}.tw.kv td:first-child{font-size:12.5px;color:var(--muted)}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

JS = r"""
(function(){
var d=document,reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function mobile(){return window.matchMedia&&matchMedia('(max-width: 767px)').matches;}
[].forEach.call(d.querySelectorAll('.ln[data-md]'),function(el){var t=el.querySelector('.tx');if(t){t.innerHTML=el.getAttribute('data-md');t.classList.add('r');}});
var tabs=[].slice.call(d.querySelectorAll('[data-tab]')),tabbar=d.querySelector('.tabs');
function fade(){if(tabbar)tabbar.classList.toggle('more-r',tabbar.scrollLeft+tabbar.clientWidth<tabbar.scrollWidth-2);}
if(tabbar){tabbar.addEventListener('scroll',fade,{passive:true});window.addEventListener('resize',fade);fade();}
function show(k){tabs.forEach(function(b){var on=b.getAttribute('data-tab')===k;b.setAttribute('aria-selected',on?'true':'false');
var p=d.getElementById('panel-'+b.getAttribute('data-tab'));if(p)p.hidden=!on;});}
tabs.forEach(function(b){b.addEventListener('click',function(){show(b.getAttribute('data-tab'));});});
show('main');
var lines=d.getElementById('lines'),flist=d.getElementById('flist'),docp=d.getElementById('doc'),dtog=d.getElementById('dtog');
function openDoc(on){if(!docp)return;docp.classList.toggle('open',on);if(dtog){dtog.setAttribute('aria-expanded',on?'true':'false');dtog.textContent=on?'Скрыть документ':'Показать документ';}}
if(dtog)dtog.addEventListener('click',function(){openDoc(!docp.classList.contains('open'));});
var fs=[].slice.call(d.querySelectorAll('.finding'));
var segs=[].slice.call(d.querySelectorAll('.seg button')),segbox=d.querySelector('.seg');
var KEYS={'':'all','критично':'crit','важно':'major','мелочь':'minor'},SEVS={};for(var k in KEYS)SEVS[KEYS[k]]=k;
function fromHash(){var m=/(?:^#|&)sev=([a-z]+)/.exec(location.hash);return m&&m[1] in SEVS?SEVS[m[1]]:null;}
var h0=fromHash(),sev=h0!==null?h0:(segbox?segbox.getAttribute('data-default')||'':''),query='',line=0;
function setSev(v,write){sev=v;segs.forEach(function(x){x.setAttribute('aria-pressed',x.getAttribute('data-sev')===v?'true':'false');});
if(write&&history.replaceState)history.replaceState(null,'','#sev='+KEYS[v]);}
function norm(s){return s.toLowerCase().replace(/ё/g,'е');}
fs.forEach(function(f){f._t=norm(f.textContent);f._r=(f.getAttribute('data-ranges')||'').split(' ').filter(Boolean).map(function(x){var a=x.split('-');return[+a[0],+a[1]];});});
function covers(f,n){return f._r.some(function(r){return n>=r[0]&&n<=r[1];});}
var cnt=d.getElementById('fcount'),none=d.getElementById('fnone'),lf=d.getElementById('linef');
function apply(){var shown=0;fs.forEach(function(f){var ok=(!sev||f.getAttribute('data-sev')===sev)&&(!query||f._t.indexOf(query)>=0)&&(!line||covers(f,line));f.hidden=!ok;if(ok)shown++;});
if(cnt)cnt.textContent=fs.length?('показано '+shown+' из '+fs.length):'';if(none)none.hidden=shown>0;
if(lf){lf.hidden=!line;if(line)lf.firstChild.textContent='Только замечания к строке '+line+'.';}}
segs.forEach(function(b){b.addEventListener('click',function(){setSev(b.getAttribute('data-sev'),true);apply();});});
window.addEventListener('hashchange',function(){var v=fromHash();if(v!==null&&v!==sev){setSev(v,false);apply();}});
setSev(sev,false);
var qi=d.getElementById('q');if(qi)qi.addEventListener('input',function(){query=norm(qi.value.trim());apply();});
var lx=d.getElementById('linef-x');if(lx)lx.addEventListener('click',function(){line=0;clearPick();apply();});
function L(n){return d.getElementById('L'+n);}
function clearHl(){[].forEach.call(d.querySelectorAll('.ln.hl'),function(x){x.classList.remove('hl');});}
function clearPick(){[].forEach.call(d.querySelectorAll('.ln.pick'),function(x){x.classList.remove('pick');});}
function scrollIn(box,el,center){if(!box||!el)return;if(mobile()&&box===lines){openDoc(true);docp.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});}
var y=el.offsetTop-(center?box.clientHeight/3:8);
box.scrollTo?box.scrollTo({top:Math.max(0,y),behavior:reduce?'auto':'smooth'}):(box.scrollTop=y);}
function select(f,at){fs.forEach(function(x){x.classList.toggle('active',x===f);});clearHl();var first=0;
f._r.forEach(function(r){for(var n=r[0];n<=r[1];n++){var el=L(n);if(el)el.classList.add('hl');}if(!first)first=r[0];});
var target=at||first;if(target)scrollIn(lines,L(target),true);}
fs.forEach(function(f){var b=f.querySelector('.fsel');if(b)b.addEventListener('click',function(){select(f);});});
d.addEventListener('click',function(ev){var a=ev.target.closest&&ev.target.closest('a');if(!a)return;
if(a.classList.contains('qref')){ev.preventDefault();var o=a.getAttribute('data-owner'),s=+a.getAttribute('data-start'),en=+a.getAttribute('data-end');
show('main');if(o){select(d.getElementById(o),s);}else{fs.forEach(function(x){x.classList.remove('active');});clearHl();for(var n=s;n<=en;n++){var el=L(n);if(el)el.classList.add('hl');}scrollIn(lines,L(s),true);}return;}
if(a.classList.contains('flink')){ev.preventDefault();var f=d.getElementById(a.getAttribute('href').slice(1));if(!f)return;
show('main');if(line){line=0;clearPick();}apply();if(f.hidden){query='';if(qi)qi.value='';setSev('',true);apply();}
select(f);if(mobile()){f.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});}else{scrollIn(flist,f,false);}f.focus({preventScroll:true});return;}
if(a.classList.contains('qlink')){ev.preventDefault();var q=d.getElementById(a.getAttribute('href').slice(1));if(!q)return;
show('questions');q.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});q.focus({preventScroll:true});}});
function pickLine(el){var n=+el.id.slice(1);line=n;clearPick();el.classList.add('pick');apply();
var vis=fs.filter(function(f){return !f.hidden;});if(vis.length===1)select(vis[0],n);else{fs.forEach(function(x){x.classList.remove('active');});}
if(flist){flist.scrollTop=0;if(mobile())d.getElementById('findings').scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});}}
if(lines){lines.addEventListener('click',function(ev){var el=ev.target.closest('.ln[data-f]');if(el)pickLine(el);});
lines.addEventListener('keydown',function(ev){if(ev.key!=='Enter'&&ev.key!==' ')return;var el=ev.target.closest('.ln[data-f]');if(el){ev.preventDefault();pickLine(el);}});}
apply();
})();
"""
