import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

FONT = Path(__file__).resolve().parent.parent / "fonts" / "NotoSans-VF.ttf"
SUBST = {"→": "->", "↔": "<->", "≠": "!=", "≤": "<=", "≥": ">=", "✓": "+", "✗": "НЕТ", "…": "...", " ": " "}


def _t(s: str) -> str:
    for a, b in SUBST.items():
        s = s.replace(a, b)
    return s.replace("\\|", "|")


def _plain(s: str) -> str:
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"(?<![*\w])\*(?!\*)([^*]+?)\*(?!\*)", r"\1", s)
    return _t(s)


def _cells(s: str) -> str:
    return re.sub(r"«\|?\s*([^«»]*?)\s*\|?»", lambda m: "«" + " · ".join(
        c.strip() for c in m.group(1).split("|") if c.strip()) + "»" if "|" in m.group(1) else m.group(0), s)


NL = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}


class PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Noto", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, f"reqcheck · стр. {self.page_no()}", align="C")


def write_pdf(md_path: Path, pdf_path: Path) -> None:
    lines = Path(md_path).read_text(encoding="utf-8").splitlines()
    pdf = PDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(16, 14, 16)
    pdf.add_font("Noto", "", str(FONT), variations={"wght": 400})
    pdf.add_font("Noto", "B", str(FONT), variations={"wght": 700})
    pdf.add_font("Noto", "I", str(FONT), variations={"wght": 400})
    pdf.add_page()
    pdf.set_font("Noto", size=10)
    w = pdf.epw
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            pdf.ln(2)
            i += 1
            continue
        if s.startswith("```"):
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            level = len(m.group(1))
            size = {1: 16, 2: 13, 3: 11}.get(level, 10)
            if level == 2 and pdf.get_y() > pdf.h - 60:
                pdf.add_page()
            pdf.ln(3 if level > 1 else 0)
            pdf.set_font("Noto", "B", size)
            pdf.set_text_color(13, 80, 84) if level <= 2 else pdf.set_text_color(20, 32, 35)
            pdf.multi_cell(w, size * 0.5, _plain(m.group(2)), align="L", **NL)
            pdf.set_text_color(20, 32, 35)
            pdf.set_font("Noto", size=10)
            pdf.ln(1)
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                r = lines[i].strip()
                if not re.match(r"^\|\s*:?-{3,}", r):
                    cells = [c.strip() for c in re.split(r"(?<!\\)\|", r.strip("|"))]
                    rows.append([_cells(_plain(c.replace("**", ""))) for c in cells])
                i += 1
            if not rows:
                continue
            n = max(len(r) for r in rows)
            rows = [r + [""] * (n - len(r)) for r in rows]
            font = 7 if n >= 6 else 8.5
            pdf.set_font("Noto", size=font)
            pad = 3.4
            want = [min(max(pdf.get_string_width(r[k]) for r in rows), 70) + pad for k in range(n)]
            need = [max(pdf.get_string_width(x) for r in rows for x in (r[k].split() or [""])) + pad for k in range(n)]
            if sum(need) <= w:
                extra = w - sum(need)
                grow = [max(a - b, 0) for a, b in zip(want, need)]
                if sum(grow) >= extra:
                    widths = tuple(b + extra * x / sum(grow) for b, x in zip(need, grow))
                else:
                    widths = tuple(b + x + (extra - sum(grow)) / n for b, x in zip(need, grow))
            else:
                widths = tuple(x / sum(need) * w for x in need)
            with pdf.table(col_widths=widths, line_height=font * 0.55, padding=1.2, text_align="LEFT",
                           headings_style=FontFace(emphasis="BOLD", fill_color=(226, 240, 240)),
                           borders_layout="SINGLE_TOP_LINE" if n > 9 else "ALL") as t:
                for r in rows:
                    row = t.row()
                    for c in r:
                        row.cell(c)
            pdf.set_font("Noto", size=10)
            pdf.ln(2)
            continue
        if s.startswith(">"):
            pdf.set_font("Noto", "I", 9)
            pdf.set_text_color(70, 85, 88)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(w - 4, 4.6, _cells(_plain(s.lstrip("> ").replace("**", ""))), align="L", **NL)
            pdf.set_text_color(20, 32, 35)
            pdf.set_font("Noto", size=10)
            i += 1
            continue
        bullet = re.match(r"^(?:[-*]|\d+\.)\s+(.*)", s)
        if not bullet:
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(
                    r"^(#{1,6}\s|\||>|```|[-*]\s|\d+\.\s)", lines[i + 1].strip()):
                i += 1
                s = s + " " + lines[i].strip()
        text = _plain(bullet.group(1) if bullet else s)
        if bullet:
            pad = 8 if ln.startswith("  ") else 3
            pdf.set_x(pdf.l_margin + pad)
            pdf.multi_cell(w - pad, 5, ("- " if s[0] in "-*" else s.split()[0] + " ") + text, markdown=True, align="L", **NL)
        else:
            pdf.multi_cell(w, 5, text, markdown=True, align="L", **NL)
        i += 1
    pdf.output(str(pdf_path))
