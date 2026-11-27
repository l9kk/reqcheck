import hashlib
import io
import logging
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
logging.getLogger("pypdf").setLevel(logging.ERROR)


class ReadError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass
class Line:
    no: int
    text: str
    page: int | None = None
    section: str = ""


@dataclass
class Document:
    name: str
    path: str
    sha256: str
    kind: str
    lines: list[Line]
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def numbered(self) -> str:
        return "\n".join(f"{l.no:>4}| {l.text}" for l in self.lines)

    def loc(self, start: int, end: int | None = None) -> str:
        end = end or start
        first = self.lines[start - 1]
        where = f"стр. {first.page}, " if first.page else ""
        lines = f"строка {start}" if start == end else f"строки {start}-{end}"
        sec = f" ({first.section})" if first.section else ""
        return f"{where}{lines}{sec}"


def sniff(data: bytes, suffix: str) -> str:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            names = set()
        if "xl/workbook.xml" in names:
            return "xlsx"
        return "docx" if suffix != ".zip" else "zip"
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or data[:4] in (b"GIF8", b"RIFF"):
        return "image"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return "ole"
    if suffix in (".html", ".htm") or data[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    return "text"


def decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    text = data.decode("utf-8", errors="replace")
    bad = text.count("\ufffd")
    if bad <= max(3, len(text) // 1000):
        return text, f"utf-8, повреждённых байт заменено: {bad}"
    text = data.decode("cp1251", errors="replace")
    return text, "cp1251"


def looks_binary(text: str) -> bool:
    if not text:
        return False
    sample = text[:20000]
    bad = sum(1 for ch in sample if (ord(ch) < 32 and ch not in "\n\r\t") or ch == "�")
    return bad / len(sample) > 0.05


GLUE_MAX = 0.15
PUA_BULLETS = str.maketrans({"\uf0b7": "•", "\uf0a7": "•", "\uf076": "•", "\uf0d8": "•", "\uf0fc": "•"})
CYR_WORD = re.compile(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]+")


def glue_score(lines: list[tuple[str, int]]) -> float:
    words = CYR_WORD.findall("\n".join(t for t, _ in lines))
    total = sum(map(len, words))
    if total < 200:
        return 0.0
    return sum(len(w) for w in words if len(w) >= 20) / total


def pdf_lines(pages, mode: str = "plain") -> tuple[list[tuple[str, int]], int]:
    out, failed = [], 0
    for i, page in enumerate(pages, start=1):
        try:
            txt = page.extract_text(extraction_mode=mode) or ""
        except Exception:
            failed += 1
            txt = ""
        for ln in txt.splitlines():
            out.append((ln.rstrip(), i))
    return out, failed


def pdftotext_lines(data: bytes) -> list[tuple[str, int]]:
    exe = shutil.which("pdftotext")
    if not exe:
        return []
    try:
        res = subprocess.run([exe, "-layout", "-enc", "UTF-8", "-", "-"], input=data,
                             capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    text = res.stdout.decode("utf-8", errors="replace")
    return [(ln.rstrip(), i) for i, page in enumerate(text.split("\f"), start=1) for ln in page.splitlines()]


def read_pdf(data: bytes) -> tuple[list[tuple[str, int]], list[str]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    warnings = []
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise ReadError("pdf_encrypted", "PDF защищён паролем, текст недоступен.",
                                "Снимите пароль с файла или передайте документ в формате .md/.docx.")
            warnings.append("PDF был зашифрован без пароля на открытие, текст извлечён.")
        pages = reader.pages
        n = len(pages)
    except ReadError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as e:
        raise ReadError("pdf_broken", f"PDF повреждён и не читается: {type(e).__name__}.",
                        "Пересохраните PDF из исходного редактора или передайте .md/.docx.")
    if n == 0:
        raise ReadError("pdf_empty", "В PDF нет страниц.", "Проверьте, что файл экспортирован полностью.")
    out, failed = pdf_lines(pages)
    if glue_score(out) > GLUE_MAX:
        best, how = out, ""
        layout, _ = pdf_lines(pages, mode="layout")
        if glue_score(layout) < glue_score(best):
            best, how = layout, "layout"
        poppler = pdftotext_lines(data)
        if poppler and glue_score(poppler) < glue_score(best):
            best, how = poppler, "pdftotext"
        out = best
        if glue_score(out) > GLUE_MAX:
            warnings.append("В PDF слова слиплись при извлечении текста (обычно шрифт без кириллицы при экспорте). "
                            "Цитаты и замечания могут быть неточными: передайте .docx или .md, "
                            "или установите poppler (pdftotext), агент использует его сам.")
        elif how:
            warnings.append(f"Обычное извлечение текста PDF склеило слова; текст взят через {how}.")
    chars = sum(len(t.strip()) for t, _ in out)
    if failed == n:
        raise ReadError("pdf_broken", "Ни одну страницу PDF не удалось прочитать.",
                        "Пересохраните PDF или передайте .md/.docx.")
    if failed:
        warnings.append(f"Не прочитано страниц PDF: {failed} из {n}. Проверка неполная.")
    if chars < 30 * n:
        raise ReadError("pdf_no_text", f"В PDF ({n} стр.) нет текстового слоя: похоже на скан или картинки.",
                        "Нужен PDF с текстом или распознавание (OCR) перед проверкой.")
    return out, warnings


def read_docx(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                raise ReadError("zip_not_docx", "Файл является ZIP-архивом, но не документом Word.",
                                "Передайте .docx, .pdf или .md.")
    except zipfile.BadZipFile:
        raise ReadError("docx_broken", "DOCX повреждён (архив не открывается).",
                        "Пересохраните документ в Word или передайте PDF/MD.")
    from docx import Document as Docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        d = Docx(io.BytesIO(data))
    except Exception as e:
        raise ReadError("docx_broken", f"DOCX повреждён: {type(e).__name__}.",
                        "Пересохраните документ в Word или передайте PDF/MD.")
    out = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, d)
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            m = re.search(r"(heading|заголовок)\s*(\d)", style)
            if m:
                out.append("#" * int(m.group(2)) + " " + t)
            elif "list" in style or "спис" in style:
                out.append("* " + t)
            else:
                out.append(t)
        elif tag == "tbl":
            table = Table(el, d)
            for r_i, row in enumerate(table.rows):
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                out.append("| " + " | ".join(cells) + " |")
                if r_i == 0:
                    out.append("|" + " --- |" * len(cells))
            out.append("")
    return out


def _x(tag: str) -> str:
    return "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}" + tag


def read_xlsx(data: bytes) -> list[str]:
    import xml.etree.ElementTree as ET

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_x("si")):
                shared.append("".join(t.text or "" for t in si.iter(_x("t"))))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target", "") for r in rels}
        book = ET.fromstring(z.read("xl/workbook.xml"))
        rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        out = []
        for sh in book.iter(_x("sheet")):
            path = target.get(sh.get(rid), "").lstrip("/")
            path = path if path.startswith("xl/") else "xl/" + path
            rows = []
            for row in ET.fromstring(z.read(path)).iter(_x("row")):
                cells = []
                for c in row.iter(_x("c")):
                    v = c.find(_x("v"))
                    if c.get("t") == "s" and v is not None:
                        cells.append(shared[int(v.text)])
                    elif c.get("t") == "inlineStr":
                        cells.append("".join(t.text or "" for t in c.iter(_x("t"))))
                    else:
                        cells.append(v.text if v is not None and v.text else "")
                cells = [x.strip().replace("\n", " ") for x in cells]
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            out.append(f"## {sh.get('name', 'Лист')}")
            for i, cells in enumerate(rows):
                out.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    out.append("|" + " --- |" * len(cells))
            out.append("")
        return out
    except (KeyError, ValueError, IndexError, zipfile.BadZipFile, ET.ParseError) as e:
        raise ReadError("xlsx_broken", f"XLSX повреждён: {type(e).__name__}.",
                        "Пересохраните таблицу в Excel или передайте PDF/MD.")


def read_html(text: str) -> list[str]:
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out, self.buf, self.prefix, self.row, self.skip = [], [], "", None, 0

        def flush(self):
            t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            self.buf = []
            if t:
                self.out.append(self.prefix + t)
            self.prefix = ""

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.flush(); self.prefix = "#" * int(tag[1]) + " "
            elif tag == "li":
                self.flush(); self.prefix = "* "
            elif tag == "tr":
                self.flush(); self.row = []
            elif tag in ("td", "th"):
                self.buf = []
            elif tag in ("p", "div", "br", "section", "article"):
                self.flush()

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip = max(0, self.skip - 1)
            elif tag in ("td", "th") and self.row is not None:
                self.row.append(re.sub(r"\s+", " ", "".join(self.buf)).strip()); self.buf = []
            elif tag == "tr" and self.row is not None:
                if any(self.row):
                    self.out.append("| " + " | ".join(self.row) + " |")
                self.row = None
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "div"):
                self.flush()

        def handle_data(self, d):
            if not self.skip:
                self.buf.append(d)

    p = P()
    p.feed(text)
    p.close()
    p.flush()
    return p.out


def assign_sections(lines: list[Line]) -> None:
    stack: list[str] = []
    for l in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", l.text)
        if m:
            level = len(m.group(1))
            stack = stack[: level - 1] + [m.group(2).strip()]
        l.section = " / ".join(stack[-2:])


def read_document(path: str) -> Document:
    p = Path(path)
    if not p.exists():
        raise ReadError("not_found", f"Файл не найден: {p.name}.", "Проверьте путь к файлу.")
    if p.is_dir():
        raise ReadError("is_dir", f"Указана папка, а не файл: {p.name}.", "Передайте путь к файлу документа.")
    size = p.stat().st_size
    if size == 0:
        raise ReadError("empty", "Файл пустой (0 байт).", "Передайте файл с текстом требований.")
    if size > MAX_BYTES:
        raise ReadError("too_big", f"Файл слишком большой ({size // 1024 // 1024} МБ).",
                        "Разбейте документ на части до 20 МБ.")
    data = p.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    kind = sniff(data, p.suffix.lower())
    warnings: list[str] = []
    if kind != "text" and p.suffix.lower() in (".md", ".txt") or (kind == "text" and p.suffix.lower() in (".pdf", ".docx")):
        warnings.append(f"Расширение {p.suffix} не совпадает с содержимым ({kind}); файл прочитан как {kind}.")

    raw: list[tuple[str, int | None]]
    if kind == "pdf":
        pairs, w = read_pdf(data)
        warnings += w
        raw = [(t, pg) for t, pg in pairs]
    elif kind == "docx":
        raw = [(t, None) for t in read_docx(data)]
    elif kind == "xlsx":
        raw = [(t, None) for t in read_xlsx(data)]
    elif kind == "html":
        text, enc = decode_text(data)
        raw = [(t, None) for t in read_html(text)]
    elif kind == "image":
        raise ReadError("image", "Файл является изображением, а не документом с текстом.",
                        "Нужен документ с текстовым слоем или распознавание (OCR).")
    elif kind == "ole":
        raise ReadError("old_office", "Старый формат Office (.doc/.xls) не поддерживается.",
                        "Сохраните документ как .docx, .xlsx или .pdf.")
    elif kind == "zip":
        raise ReadError("zip", "Передан архив, а не документ.", "Распакуйте архив и передайте сам документ.")
    else:
        text, enc = decode_text(data)
        if looks_binary(text):
            raise ReadError("binary", "Файл не похож на текст: много нечитаемых байтов (возможно, повреждён).",
                            "Передайте документ в формате .md, .txt, .pdf или .docx.")
        if enc != "utf-8":
            warnings.append(f"Кодировка файла: {enc}.")
        raw = [(t, None) for t in text.splitlines()]

    lines = [Line(no=i, text=t.translate(PUA_BULLETS).rstrip(), page=pg) for i, (t, pg) in enumerate(raw, start=1)]
    if sum(len(l.text.strip()) for l in lines) < 20:
        raise ReadError("no_text", "В документе почти нет текста.", "Проверьте, что передан правильный файл.")
    assign_sections(lines)
    return Document(name=p.name, path=str(p), sha256=sha, kind=kind, lines=lines, warnings=warnings)
