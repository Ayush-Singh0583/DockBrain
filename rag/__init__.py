from dataclasses import dataclass, field

from .chunker import Chunk, chunk_text
from .loader import load_document
from .retriever import BM25Retriever


@dataclass
class Reply:
    """An answer with its provenance, for callers that show more than the text."""

    text: str
    hits: list  # the passages the answer engine was given; [n] in `text` refers to hits[n-1]
    origin: str  # "document", "mixed", "general" or "insufficient" (see rag.generator)
    cited: set = field(default_factory=set)  # numbers of the hits the answer cites or quotes
    coverage: dict | None = None  # {"searched": sections read, "total": sections in the document}


class RAG:
    """Load -> chunk -> index once, then retrieve + generate per question."""

    def __init__(self, path: str, generator, chunk_words: int = 120, top_k: int = 4):
        self.chunks = chunk_text(load_document(path), max_words=chunk_words)
        self.retriever = BM25Retriever(self.chunks)
        self.generator = generator
        if hasattr(generator, "attach"):
            generator.attach(self.retriever)
        self.top_k = top_k

    def ask(self, question: str):
        """The answer, and the passages it was based on (an online mode may send more than
        the search found, such as a whole small document)."""
        hits = self.retriever.search(question, self.top_k)
        answer = self.generator.answer(question, hits)
        used = getattr(self.generator, "used_hits", None)
        return answer, hits if used is None else used

    def reply(self, question: str) -> Reply:
        """Like `ask`, plus where the answer came from, as the answer engine reported it."""
        text, hits = self.ask(question)
        engine = self.generator
        return Reply(
            text,
            hits,
            getattr(engine, "last_origin", None) or "document",
            set(getattr(engine, "last_cited", None) or ()),
            getattr(engine, "last_coverage", None),
        )
