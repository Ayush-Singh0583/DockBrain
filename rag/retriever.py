"""BM25 retrieval implemented from scratch (no external libraries)."""
import math
import re
from collections import Counter

from .chunker import Chunk

STOPWORDS = set(
    "a an the and or but if of to in on at by for with from as is are was were be been being "
    "this that these those it its into than then so such not no do does did has have had "
    "what which who whom whose when where why how i you he she we they me him her us them my your our their".split()
)


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [stem(t) for t in tokens if t not in STOPWORDS]


def stem(word: str) -> str:
    """Tiny suffix-stripping stemmer so 'running'/'runs' match 'run'."""
    for suffix in ("ingly", "edly", "ing", "ies", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.doc_tokens = [tokenize(c.text) for c in chunks]
        self.doc_freqs = [Counter(toks) for toks in self.doc_tokens]
        self.doc_lens = [len(toks) for toks in self.doc_tokens]
        self.avg_len = sum(self.doc_lens) / max(len(self.doc_lens), 1)

        df = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        n = len(chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def score(self, query_tokens: list[str], i: int) -> float:
        freqs, length = self.doc_freqs[i], self.doc_lens[i]
        s = 0.0
        for term in query_tokens:
            tf = freqs.get(term, 0)
            if tf:
                norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
                s += self.idf[term] * norm
        return s

    def search(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        q = tokenize(query)
        scored = [(self.chunks[i], self.score(q, i)) for i in range(len(self.chunks))]
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
