import re

from .ground import Grounder
from .model import Finding
from .reader import Document

WRITE_WORDS = ("save", "create", "update", "delete", "remove", "set", "add", "edit", "post", "change")
DESCRIBED_CODE_RE = re.compile(r"^\s*(?:\*\*|#{2,6}\s*)?([1-5]\d\d)\.(?:\*\*)?\s+\S")
CODE_RE = re.compile(r"(?<![\d.,])([1-5]\d\d)(?![\d.,])")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")
TEST_SEC_RE = re.compile(r"(?<![а-яё])тест(?!ируем)|при[её]м(?:к|о-сдат)", re.I)


def _f(scope, criterion, severity, quotes, problem, impact="", fix="", test_hint=""):
    return Finding(id="", scope=scope, req_ids=[], criterion=criterion, severity=severity, quotes=quotes,
                   problem=problem, impact=impact, fix=fix, test_hint=test_hint, role="linter")


def _test_section(doc: Document, line) -> bool:
    title = next((l.text.lstrip("#").strip() for l in doc.lines if l.text.startswith("# ")), None)
    return any(TEST_SEC_RE.search(p) for p in line.section.split(" / ") if p != title)


def _tables(doc: Document):
    """Yield (header_cells, [(line_no, cells)]) for markdown tables."""
    lines = doc.lines
    i = 0
    while i < len(lines) - 1:
        s = lines[i].text.strip()
        nxt = lines[i + 1].text.strip()
        if s.startswith("|") and re.match(r"^\|?\s*:?-{3,}", nxt):
            header = [c.strip().strip("*").strip() for c in s.strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].text.strip().startswith("|"):
                cells = [c.strip() for c in lines[j].text.strip().strip("|").split("|")]
                rows.append((lines[j].no, cells))
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


def rule_weak_words(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    out = []
    text_lines = [l for l in doc.lines if l.text.strip() and not l.text.strip().startswith(("#", "```", "{", "|"))]
    groups = [("superlatives", "превосходная степень"), ("subjective", "субъективная оценка"),
              ("vague_adverbs", "размытое наречие или прилагательное"), ("open_ended", "открытый перечень"),
              ("loopholes", "лазейка, необязательность")]
    for l in text_lines:
        low = l.text.lower()
        hits = []
        for key, label in groups:
            for w in lang[key]:
                if re.search(r"(?<![а-яёa-z])" + re.escape(w.lower()), low):
                    hits.append(f"«{w}» ({label})")
        if hits:
            out.append(_f("req", "unambiguous", "важно", [g.quote_lines(l.no, l.no)],
                          "Формулировка содержит слова, которые нельзя проверить однозначно: " + ", ".join(hits) + ".",
                          "Разработчик и тестировщик поймут условие по-разному.",
                          "Заменить на измеримое условие с числом, единицей и способом проверки."))
    return out


def rule_placeholders(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    out = []
    ph_lines = {}
    for l in doc.lines:
        for p in lang["placeholders"]:
            if p.lower() in l.text.lower():
                ph_lines.setdefault(p, []).append(l.no)
    for p, nos in ph_lines.items():
        runs = []
        for n in nos:
            if runs and n - runs[-1][1] <= 1:
                runs[-1][1] = n
            else:
                runs.append([n, n])
        for a, b in runs:
            q = g.quote_lines(a, b) if b - a < 3 else g.quote_lines(a, a)
            span = f" (строки {a}-{b})" if b > a else ""
            if any(_test_section(doc, doc.lines[n - 1]) for n in range(a, b + 1)):
                out.append(_f("set", "set_validatable", "критично", [q],
                              f"Раздел тестирования не заполнен: шаблонная заглушка «{p}»{span}.",
                              "Тест-кейсы и проверку приёмки написать нельзя: неизвестно, что и как проверять.",
                              "Заполнить раздел: что проверяется, тестовые данные, ожидаемые результаты, "
                              "кто и на каком стенде проверяет."))
                continue
            out.append(_f("set", "conforming", "важно", [q],
                          f"Шаблонная заглушка «{p}» не заменена содержанием{span}.",
                          "Раздел фактически пустой: по нему нельзя принять решение или написать тест.",
                          "Заполнить раздел или явно указать «Не требуется» с причиной."))
    return out


def rule_empty_test_section(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    out = []
    for k, l in enumerate(doc.lines):
        m = HEADING_RE.match(l.text)
        if not m or not TEST_SEC_RE.search(m.group(2)):
            continue
        body = []
        for nxt in doc.lines[k + 1:]:
            h = HEADING_RE.match(nxt.text)
            if h and len(h.group(1)) <= len(m.group(1)):
                break
            if nxt.text.strip() and not h:
                body.append(nxt)
        if not body:
            out.append(_f("set", "set_validatable", "критично", [g.quote_lines(l.no, l.no)],
                          f"Раздел «{m.group(2).strip()}» пустой.",
                          "Тест-кейсы и проверку приёмки написать нельзя: неизвестно, что и как проверять.",
                          "Заполнить раздел: что проверяется, тестовые данные, ожидаемые результаты."))
    return out


def rule_table_gaps(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    out = []
    for header, rows in _tables(doc):
        empty = [no for no, cells in rows if not any(c.strip() for c in cells)]
        if rows and len(empty) == len(rows):
            out.append(_f("set", "set_complete", "важно", [g.quote_lines(rows[0][0] - 2, rows[0][0] - 2)],
                          f"Таблица «{' | '.join(header)}» пустая: ни одной заполненной строки.",
                          "Нет ответственных и согласования: документ нельзя считать утверждённым.",
                          "Заполнить таблицу или удалить её из шаблона."))
        if len(header) >= 3 and rows and len(empty) < len(rows) and all(
                not any(c.strip() for c in cells[1:]) for _, cells in rows):
            out.append(_f("set", "set_complete", "важно", [g.quote_lines(rows[0][0], rows[-1][0])],
                          f"Таблица «{' | '.join(header)}» заполнена только в первой колонке: "
                          f"колонки «{', '.join(header[1:])}» пустые.",
                          "Нет ответственных и согласования: документ нельзя считать утверждённым.",
                          "Заполнить таблицу или удалить её из шаблона."))
        if len(header) != 2:
            continue
        for no, cells in rows:
            if len(cells) != 2:
                continue
            name, value = cells[0].strip("* "), cells[1].strip()
            if value in ("—", "-", "–", ""):
                out.append(_f("set", "set_complete", "важно", [g.quote_lines(no, no)],
                              f"Поле «{name}» не заполнено (прочерк или пусто).",
                              "Без этого значения работу нельзя реализовать и проверить полностью.",
                              "Указать значение или причину отсутствия."))
            elif re.search(r":\s*[—–-]\s*$|:\s*[—–-]\s*[.;]", value):
                out.append(_f("set", "set_complete", "важно", [g.quote_lines(no, no)],
                              f"Поле «{name}» заполнено частично: «{value}».",
                              "Часть окружений или значений не определена.",
                              "Указать значение для всех окружений."))
    return out


def rule_version_date(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    full = doc.text
    has_date = re.search(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", full)
    has_ver = re.search(r"(верси[яи]|version)\s*[:№]?\s*v?\d", full, re.I)
    if has_date and has_ver:
        return []
    what = "номера версии и даты" if not has_date and not has_ver else ("даты" if not has_date else "номера версии")
    pat = r"дата|date" if has_ver else r"верси|version"
    vl = next((l.no for l in doc.lines if re.search(pat, l.text, re.I)), doc.lines[0].no)
    return [_f("set", "srs_modifiable", "важно", [g.quote_lines(vl, vl)],
               f"У документа нет {what}.",
               "Нельзя понять, какую редакцию согласовали и по какой писать тесты.",
               "Добавить версию, дату и историю изменений.")]


def rule_tiyn_tenge(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    tiyn = [l.no for l in doc.lines if re.search(r"тиын", l.text, re.I)]
    tenge = [l.no for l in doc.lines if re.search(r"тенге|₸|\bkzt\b", l.text, re.I)]
    same = [n for n in tiyn if n in tenge]
    if not same:
        return []
    return [_f("set", "set_consistent", "важно", [g.quote_lines(same[0], same[0])],
               "В одном требовании суммы хранятся в разных единицах: тиыны и тенге.",
               "Сравнение суммы покупок с порогом без явного пересчёта даст ошибку в 100 раз.",
               "Хранить все суммы в одной единице (тиыны) и указать правило пересчёта.",
               "Порог 50 000 ₸ и покупки на 5 000 000 тиын: push должен прийти ровно на пороге.")]


def rule_secrets_in_logs(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    secret = re.compile(r"\bcvv2?\b|\bcvc2?\b|\bpin\b|пин-код|номер[а-я]* карты|\bpan\b|парол|\botp\b|одноразов[а-я]* код", re.I)
    for l in doc.lines:
        if re.search(r"лог(ир|ах|и\b|ов|\b)|журнал|\blog", l.text, re.I) and secret.search(l.text) and not re.search(
                r"не логир|не должн[а-я]* (попадать|записыва|логир)|маскир|запрещ", l.text, re.I):
            return [_f("req", "correct", "критично", [g.quote_lines(l.no, l.no)],
                       "Требование предписывает писать в логи чувствительные данные: "
                       + ", ".join(f"«{m}»" for m in dict.fromkeys(x.group(0) for x in secret.finditer(l.text))) + ".",
                       "Нарушение PCI DSS: CVV и PIN нельзя хранить после авторизации, номер карты только в маскированном "
                       "виде. Утечка логов означает компрометацию карт.",
                       "Номер карты маскировать (первые 6 и последние 4 цифры), CVV, PIN, пароли и коды не логировать никогда.",
                       "Провести операцию и проверить, что в логах нет CVV и полного номера карты.")]
    return []


def rule_get_writes_in_table(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    out = []
    for no, cells in [(no, cells) for _, rows in _tables(doc) for no, cells in rows]:
        if any(c.strip().upper() == "GET" for c in cells):
            row = " ".join(cells).lower()
            if any(w in row for w in WRITE_WORDS + ("pay", "transfer", "confirm", "cancel", "платёж", "платеж",
                                                     "оплат", "перевод", "списан", "сохран", "изменен", "удален")):
                out.append(_f("req", "correct", "критично", [g.quote_lines(no, no)],
                              "Метод GET используется для операции, которая меняет данные или списывает деньги.",
                              "GET должен быть безопасным и идемпотентным: прокси и клиенты повторяют его, параметры "
                              "попадают в логи и историю. Повтор запроса может провести операцию дважды.",
                              "Использовать POST с телом запроса и ключом идемпотентности.",
                              "Повторить тот же запрос дважды: операция должна выполниться один раз."))
    return out


def rule_get_method_line(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    method_line = next((l for l in doc.lines if re.search(r"(rest type|method|метод)\W+.*\bget\b", l.text, re.I)), None)
    if not method_line:
        return []
    url_lines = [l for l in doc.lines if re.search(r"/[a-z]+/\w+", l.text, re.I)
                 and any(w in l.text.lower() for w in WRITE_WORDS)]
    if not url_lines:
        return []
    u = url_lines[0]
    return [_f("req", "correct", "критично", [g.quote_lines(method_line.no, method_line.no), g.quote_lines(u.no, u.no)],
               "Метод GET используется для операции записи (сохранение настройки), параметры передаются в строке запроса.",
               "GET должен быть безопасным и идемпотентным: прокси и браузеры кэшируют и повторяют его, параметры попадают в логи.",
               "Использовать POST или PUT с телом запроса для сохранения.",
               "Повторный GET из кэша не должен менять настройку.")]


def rule_content_type_without_body(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    ct = next((l for l in doc.lines if re.search(r"content-type", l.text, re.I) and "json" in l.text.lower()), None)
    nobody = next((l for l in doc.lines if re.search(r"тело не используется|body is not used|без тела", l.text, re.I)), None)
    if not (ct and nobody):
        return []
    return [_f("set", "set_consistent", "важно", [g.quote_lines(ct.no, ct.no), g.quote_lines(nobody.no, nobody.no)],
               "Указан Content-Type application/json, но тело запроса не используется.",
               "Непонятно, что должен отправлять клиент и что проверять в тесте.",
               "Убрать Content-Type для запроса без тела или описать тело.")]


def rule_undescribed_codes(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    described = {}
    for l in doc.lines:
        m = DESCRIBED_CODE_RE.match(l.text)
        if m:
            described.setdefault(m.group(1), l.no)
    if not described:
        return []
    mentioned = {}
    for l in doc.lines:
        if l.text.strip().startswith(("{", "`")):
            continue
        if not re.search(r"результат|возвращ|ответ|status|код|успеш", l.text, re.I) and not re.match(r"^\s*\*\*\d{3}\*\*\s*$", l.text):
            continue
        for c in CODE_RE.findall(l.text):
            if c not in described:
                mentioned.setdefault(c, l.no)
    return [_f("set", "set_complete", "важно", [g.quote_lines(no, no)],
               f"Код ответа {c} упоминается, но не описан в списке статусов.",
               "Клиент и тестировщик не знают, когда возвращается этот код и что в теле ответа.",
               f"Добавить {c} в список статусов с условием и примером ответа или убрать упоминание.",
               f"Тест-кейс на условие, при котором сервис отвечает {c}.") for c, no in mentioned.items()]


def rule_param_types(doc: Document, lang: dict, g: Grounder) -> list[Finding]:
    params: dict[str, list[tuple[str, int, str]]] = {}
    for header, rows in _tables(doc):
        low = [h.lower() for h in header]
        if "parameter" in low and "format" in low:
            pi, fi = low.index("parameter"), low.index("format")
            title = next((doc.lines[k].text.strip("# ").strip() for k in range(rows[0][0] - 3, 0, -1)
                          if doc.lines[k - 1].text.startswith("#")), "") if rows else ""
            for no, cells in rows:
                if len(cells) > max(pi, fi):
                    name = cells[pi].strip("` ")
                    params.setdefault(name, []).append((cells[fi].strip().lower(), no, title))
    out = []
    for name, uses in params.items():
        fmts = {u[0] for u in uses}
        if len(uses) > 1 and len(fmts) > 1:
            out.append(_f("set", "set_consistent", "важно", [g.quote_lines(u[1], u[1]) for u in uses[:2]],
                          f"Параметр {name} имеет разный тип в разных таблицах: {', '.join(sorted(fmts))}.",
                          "Клиент и сервер разойдутся в сериализации; автотесты контракта упадут.",
                          f"Определить один тип для {name} в запросе и ответе."))
    return out


RULES = [rule_weak_words, rule_placeholders, rule_empty_test_section, rule_table_gaps, rule_version_date,
         rule_tiyn_tenge, rule_secrets_in_logs, rule_get_writes_in_table, rule_get_method_line,
         rule_content_type_without_body, rule_undescribed_codes, rule_param_types]


def lint(doc: Document, criteria: dict) -> list[Finding]:
    g = Grounder(doc)
    lang = criteria["language"]
    out: list[Finding] = []
    for rule in RULES:
        out += rule(doc, lang, g)
    return out

