import re
from bisect import bisect_right
from difflib import SequenceMatcher

from .model import Quote
from .reader import Document

FENCE_RE = re.compile(r"^\s*```")

_TRANS = str.maketrans({"ё": "е", "Ё": "Е", "«": '"', "»": '"', "“": '"', "”": '"', "„": '"',
                        "—": "-", "–": "-", "−": "-", " ": " ", " ": " ", "’": "'"})


def norm(s: str) -> str:
    s = s.translate(_TRANS).replace("**", "").replace("`", "").replace("|", " ")
    s = re.sub(r"^\s*(?:(?:#{1,6}|[*\-•]|\d+[.)])\s+)+", "", s, flags=re.M)
    s = re.sub(r"(?<=[^\w\s])\s+\d+[.)]\s+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


class Grounder:
    def __init__(self, doc: Document):
        self.doc = doc
        self.norm_lines = [norm(l.text) for l in doc.lines]
        self.content = [i for i, nl in enumerate(self.norm_lines) if nl and not FENCE_RE.match(doc.lines[i].text)]
        self.content_set = set(self.content)
        self.offsets, pos = [], 0
        for i in self.content:
            self.offsets.append(pos)
            pos += len(self.norm_lines[i]) + 1
        self.joined = " ".join(self.norm_lines[i] for i in self.content)

    def locate(self, quote: str, hint_line: int | None = None) -> Quote | None:
        q = norm(quote).strip(' ."')
        if len(q) < 4:
            i = next((i for i, nl in enumerate(self.norm_lines) if nl.strip(' ."') == q), None) if len(q) == 3 else None
            return None if i is None else self._q(i + 1, i + 1, quote)
        n = len(self.norm_lines)
        for i, nl in enumerate(self.norm_lines):
            if q in nl:
                return self._q(i + 1, i + 1, quote)
        span = self._span(q, hint_line)
        if span:
            return self._q(span[0], span[1], quote)
        best, best_i, best_w = 0.0, -1, 1
        qlen = len(q)
        for width in (1, 2, 3):
            for i in range(n - width + 1):
                joined = " ".join(self.norm_lines[i:i + width])
                if not joined or len(joined) < qlen * 0.5:
                    continue
                sm = SequenceMatcher(None, q, joined, autojunk=False)
                m = sm.find_longest_match(0, len(q), 0, len(joined))
                if m.size < min(12, qlen):
                    continue
                score = sum(b.size for b in sm.get_matching_blocks()) / qlen
                if hint_line and i + 1 <= hint_line <= i + width:
                    score += 0.05
                if score > best:
                    best, best_i, best_w = score, i, width
        if best >= 0.85:
            return self._q(best_i + 1, best_i + best_w, None)
        return None

    def _span(self, q: str, hint_line: int | None) -> tuple[int, int] | None:
        """Exact match of q across consecutive content lines (blank and ``` fence lines skipped)."""
        first = None
        pos = self.joined.find(q)
        while pos >= 0:
            a = bisect_right(self.offsets, pos) - 1
            b = bisect_right(self.offsets, pos + len(q) - 1) - 1
            span = (self.content[a] + 1, self.content[b] + 1)
            if not hint_line or span[0] <= hint_line <= span[1]:
                return span
            first = first or span
            pos = self.joined.find(q, pos + 1)
        return first

    def _q(self, start: int, end: int, original: str | None) -> Quote:
        src = " ".join(self.doc.lines[k - 1].text.strip() for k in range(start, end + 1))
        body = " ".join(self.norm_lines[k] for k in range(start - 1, end) if k in self.content_set)
        text = original.strip() if original and (norm(original) in norm(src) or norm(original).strip(' ."') in body) else src
        return Quote(text=text, start=start, end=end, loc=self.doc.loc(start, end))

    def quote_lines(self, start: int, end: int) -> Quote:
        return self._q(start, end, None)
