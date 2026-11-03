from .chunker import Chunk, chunk_text
from .loader import load_document
from .retriever import BM25Retriever


class RAG:
    """Load -> chunk -> index once, then retrieve + generate per question."""

    def __init__(self, path: str, generator, chunk_words: int = 120, top_k: int = 4):
        self.chunks = chunk_text(load_document(path), max_words=chunk_words)
        self.retriever = BM25Retriever(self.chunks)
        self.generator = generator
        self.top_k = top_k

    def ask(self, question: str):
        hits = self.retriever.search(question, self.top_k)
        return self.generator.answer(question, hits), hits
