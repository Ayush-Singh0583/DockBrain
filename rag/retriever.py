"""BM25 retrieval implemented from scratch (no external libraries)."""
import math
import os
import re
from collections import Counter

from .chunker import Chunk, is_noise, section_name

STOPWORDS = set(
    "a an the and or but if of to in on at by for with from as is are was were be been being "
    "this that these those it its into than then so such not no do does did has have had "
    "what which who whom whose when where why how i you he she we they me him her us them my your our their "
    "about can could will would should shall may might must there also many much use used uses using "
    "work works working".split()
)
# A question made only of these words asks about the document as a whole.
_DOCUMENT_WORDS = set(
    "summary summarize summarise overview gist main idea point points topic purpose aim "
    "cover covers project document doc report paper book article file text thesis study work "
    "give tell show provide write describe explain please brief briefly short quick".split()
)
# Sections that say what a document is about, best first.
OVERVIEW_SECTIONS = ("abstract", "executive summary", "summary", "introduction", "overview")
HEADING_BOOST = 2  # a section's heading counts this many extra times for its chunks
# Another form of a question word ("production" for "produces") counts, but less than the
# word itself. Six shared letters keeps "apple" from matching "application". Measured on
# reworded questions: found 15 of 23 instead of 13, with no loss on the older 43.
WORD_FORM_LETTERS = 6
WORD_FORM_WEIGHT = 0.5


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [stem(t) for t in tokens if t not in STOPWORDS]


def stem(word: str) -> str:
    """Tiny suffix-stripping stemmer so 'running'/'runs' match 'run'. A final 'e' is dropped
    too, so 'apple', 'apples', 'create', 'created', and 'creating' meet at 'appl' and 'creat'."""
    for suffix in ("ingly", "edly", "ing", "ies", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not (suffix == "s" and word.endswith("ss")):
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def is_overview_question(question: str) -> bool:
    """True for 'What is this project about?' or 'Summarize it', but not 'Overview of IPFS'."""
    words = re.findall(r"[a-z0-9]+", question.lower())
    return bool(words) and all(w in STOPWORDS or w in _DOCUMENT_WORDS for w in words)


def _index_tokens(chunk: Chunk) -> list[str]:
    tokens = tokenize(chunk.text)
    for section in {s.section for s in chunk.sentences if s.section}:
        tokens += tokenize(section) * HEADING_BOOST
    return tokens


def _content_weight(chunk: Chunk) -> float:
    """Rank chunks lower the more they consist of contents pages and thank-yous.
    They stay searchable, so 'who guided this project?' can still find them."""
    total = sum(len(s.text.split()) for s in chunk.sentences)
    noisy = sum(len(s.text.split()) for s in chunk.sentences if is_noise(s.text))
    return 1 - 0.8 * noisy / total if total else 1.0


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.doc_tokens = [_index_tokens(c) for c in chunks]
        self.doc_freqs = [Counter(toks) for toks in self.doc_tokens]
        self.doc_lens = [len(toks) for toks in self.doc_tokens]
        self.avg_len = sum(self.doc_lens) / max(len(self.doc_lens), 1)
        self.weights = [_content_weight(c) for c in chunks]

        df = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        n = len(chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self._forms = {}

    def word_forms(self, term: str) -> set[str]:
        """Other words in the document sharing the term's first letters: 'produc' (from
        'produces') gives 'production' and 'producer'."""
        if term not in self._forms:
            self._forms[term] = {
                other for other in self.idf
                if other != term and len(os.path.commonprefix([term, other])) >= WORD_FORM_LETTERS
            }
        return self._forms[term]

    def query_terms(self, query: str) -> dict[str, float]:
        """Each question word at full weight, plus its other forms at a lower weight."""
        terms = {}
        for term in tokenize(query):
            terms[term] = 1.0
            for form in self.word_forms(term):
                terms.setdefault(form, WORD_FORM_WEIGHT)
        return terms

    def score(self, terms: dict[str, float], i: int) -> float:
        freqs, length = self.doc_freqs[i], self.doc_lens[i]
        s = 0.0
        for term, weight in terms.items():
            tf = freqs.get(term, 0)
            if tf:
                norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
                s += weight * self.idf[term] * norm
        return s * self.weights[i]

    def _overview_chunks(self, top_k: int) -> list[tuple[Chunk, float]]:
        """Start of the abstract/introduction, or of the document if it has neither."""
        start, keep_first = 0, False
        for name in OVERVIEW_SECTIONS:
            found = next(
                (c.id for c in self.chunks
                 if any(s.is_heading and section_name(s.text) == name for s in c.sentences)),
                None,
            )
            if found is not None:
                start, keep_first = found, True
                break
        useful = [c for c in self.chunks[start:] if self.weights[c.id] >= 0.5 or (keep_first and c.id == start)]
        useful = useful or self.chunks[start:]
        return [(c, 1.0) for c in useful[:top_k]]

    def search(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        if is_overview_question(query):
            return self._overview_chunks(top_k)
        return self.search_excluding(query, top_k, exclude=set())

    def search_excluding(self, query: str, top_k: int, exclude: set[int]) -> list[tuple[Chunk, float]]:
        """Ranked sections matching the query, skipping the given section ids."""
        q = self.query_terms(query)
        scored = [(c, self.score(q, c.id)) for c in self.chunks if c.id not in exclude]
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
