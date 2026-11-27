import re
from dataclasses import dataclass

from .reader import Document

DOC_ID_RE = re.compile(
    r"^\s*(?:[*\-•]\s*)?(?:\*\*)?\s*((?:[A-ZА-ЯЁ]{1,6}[-_.]?\d+(?:\.\d+)*)|(?:\d+(?:\.\d+)+))\.?\s*(?:\*\*)?"
)
BULLET_RE = re.compile(r"^\s*(?:[*\-•]|\d+[.)])\s+")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


@dataclass
class Candidate:
    id: str
    kind: str
    start: int
    end: int
    section: str
    text: str
    doc_id: str = ""
    context: str = ""


def clean(text: str) -> str:
    t = text.replace("**", "").replace("`", "")
    t = re.sub(r"^\s*(?:[*\-•]|\d+[.)])\s+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def extract_candidates(doc: Document) -> list[Candidate]:
    out: list[Candidate] = []
    lines = doc.lines
    i = 0
    header = ""

    def add(kind, start, end, text, context=""):
        text = text.strip()
        if not text or len(clean(text)) < 3:
            return
        m = DOC_ID_RE.match(text)
        doc_id = m.group(1) if m and kind in ("bullet", "para") else ""
        out.append(Candidate(id=f"C{len(out) + 1:03d}", kind=kind, start=start, end=end,
                             section=lines[start - 1].section, text=text, doc_id=doc_id, context=context))

    while i < len(lines):
        l = lines[i]
        t = l.text
        s = t.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].text.strip().startswith("```"):
                j += 1
            end = min(j, len(lines) - 1)
            body = "\n".join(x.text for x in lines[i:end + 1])
            add("code", l.no, lines[end].no, body)
            i = end + 1
            continue
        if re.match(r"^#{1,6}\s", s):
            i += 1
            continue
        if s.startswith("|"):
            if TABLE_SEP_RE.match(s):
                i += 1
                continue
            nxt = lines[i + 1].text.strip() if i + 1 < len(lines) else ""
            if TABLE_SEP_RE.match(nxt):
                header = s
                i += 1
                continue
            add("table_row", l.no, l.no, t, context=header)
            i += 1
            continue
        header = ""
        if s in ("---", "***"):
            i += 1
            continue
        kind = "bullet" if BULLET_RE.match(t) else "para"
        j = i + 1
        if doc.kind == "pdf" and not COLUMNS_RE.search(s):
            while j < len(lines):
                gap = j + 1 if not lines[j].text.strip() and j + 1 < len(lines) else j
                nxt = lines[gap].text.strip()
                if gap > j and not (nxt[:1].islower()):
                    break
                if not is_wrap(lines[j - 1].text, lines[gap].text):
                    break
                j = gap + 1
        add(kind, l.no, lines[j - 1].no, " ".join(x.text.strip() for x in lines[i:j] if x.text.strip()))
        i = j
    return out


COLUMNS_RE = re.compile(r"\S\s{3,}\S")


def is_wrap(prev: str, nxt: str) -> bool:
    s = nxt.strip()
    m = DOC_ID_RE.match(nxt)
    if not s or COLUMNS_RE.search(s) or BULLET_RE.match(nxt) or (m and m.group(1)):
        return False
    if re.match(r"^\d+(?:\.\d+)*\.?\s", s) or prev.rstrip().endswith((":", ".", "!", "?", ";")):
        return False
    return s[0].islower() or s[0] in "«(\"-–—,0123456789"


def render_candidates(cands: list[Candidate]) -> str:
    rows = []
    last_sec = None
    for c in cands:
        if c.section != last_sec:
            rows.append(f"\n## {c.section or '(без раздела)'}")
            last_sec = c.section
        ctx = f"  [колонки: {clean(c.context)}]" if c.context else ""
        body = clean(c.text) if c.kind != "code" else c.text.replace("\n", " ")
        rows.append(f"{c.id} [{c.kind}, строка {c.start}]{ctx}: {body[:400]}")
    return "\n".join(rows)
