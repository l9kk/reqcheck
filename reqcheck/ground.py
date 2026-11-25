import re
from difflib import SequenceMatcher

from .model import Quote
from .reader import Document

_TRANS = str.maketrans({"ё": "е", "Ё": "Е", "«": '"', "»": '"', "“": '"', "”": '"', "„": '"',
                        "—": "-", "–": "-", "−": "-", " ": " ", " ": " ", "’": "'"})


def norm(s: str) -> str:
    s = s.translate(_TRANS).replace("**", "").replace("`", "").replace("|", " ")
    s = re.sub(r"^\s*(?:[*\-•]|\d+[.)])\s+", "", s, flags=re.M)
    return re.sub(r"\s+", " ", s).strip().lower()


class Grounder:
    def __init__(self, doc: Document):
        self.doc = doc
        self.norm_lines = [norm(l.text) for l in doc.lines]

    def locate(self, quote: str, hint_line: int | None = None) -> Quote | None:
        q = norm(quote).strip(' ."')
        if len(q) < 4:
            return None
        n = len(self.norm_lines)
        for i, nl in enumerate(self.norm_lines):
            if q in nl:
                return self._q(i + 1, i + 1, quote)
        for width in (2, 3, 4, 6):
            for i in range(n - width + 1):
                joined = " ".join(self.norm_lines[i:i + width])
                if q in joined:
                    return self._q(i + 1, i + width, quote)
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

    def _q(self, start: int, end: int, original: str | None) -> Quote:
        src = " ".join(self.doc.lines[k - 1].text.strip() for k in range(start, end + 1))
        text = original.strip() if original and norm(original) in norm(src) else src
        return Quote(text=text, start=start, end=end, loc=self.doc.loc(start, end))

    def quote_lines(self, start: int, end: int) -> Quote:
        return self._q(start, end, None)
