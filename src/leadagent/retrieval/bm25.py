"""Dependency-free BM25 over markdown sections."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from leadagent.config.schemas import KnowledgeDoc
from leadagent.retrieval.base import Hit

STOPWORDS = frozenset(
    """a an and are as at be but by can could do does for from had has have how i if in is it its
    me my of on or our so than that the their them then there these they this to us was we were
    what when where which who why will with would you your about any get got just""".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def tokenize(text: str) -> list[str]:
    out = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in STOPWORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


@dataclass
class _Chunk:
    source: str
    heading: str
    text: str
    counts: Counter
    length: int


def chunk_markdown(doc: KnowledgeDoc) -> list[tuple[str, str]]:
    """Split a doc into (heading, text) sections; the top-level title is kept as context."""
    title = ""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    text = re.sub(r"<!--.*?-->", "", doc.text, flags=re.S)  # notes for editors, not for leads
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1 and not title:
            title = m.group(2).strip()
            continue
        if m:
            current = (m.group(2).strip(), [])
            sections.append(current)
        else:
            if current is None:
                current = (title, [])
                sections.append(current)
            current[1].append(line)
    chunks = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            chunks.append((heading or title, body))
    return chunks


class BM25Retriever:
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        min_score: float = 0.5,
        min_coverage: float = 0.4,
    ):
        # min_coverage: share of distinct query terms a chunk must contain, so one shared
        # word ("install") does not make an unrelated question look answered.
        self.k1, self.b, self.min_score, self.min_coverage = k1, b, min_score, min_coverage
        self._chunks: list[_Chunk] = []
        self._df: Counter = Counter()
        self._avg_len = 0.0

    def index(self, docs: list[KnowledgeDoc]) -> None:
        self._chunks = []
        self._df = Counter()
        for doc in docs:
            for heading, text in chunk_markdown(doc):
                # heading words count toward matching, so "warranty" finds its section
                tokens = tokenize(f"{heading} {heading} {text}")
                counts = Counter(tokens)
                self._chunks.append(_Chunk(doc.source, heading, text, counts, len(tokens)))
                self._df.update(counts.keys())
        total = sum(c.length for c in self._chunks)
        self._avg_len = total / len(self._chunks) if self._chunks else 0.0

    def search(self, query: str, k: int = 3) -> list[Hit]:
        terms = tokenize(query)
        if not terms or not self._chunks:
            return []
        n = len(self._chunks)
        unique = set(terms)
        hits: list[Hit] = []
        for c in self._chunks:
            score = 0.0
            if sum(1 for t in unique if t in c.counts) / len(unique) < self.min_coverage:
                continue
            for t in unique:
                tf = c.counts.get(t, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * c.length / self._avg_len)
                score += idf * tf * (self.k1 + 1) / denom
            if score >= self.min_score:
                hits.append(Hit(source=c.source, heading=c.heading, text=c.text, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
