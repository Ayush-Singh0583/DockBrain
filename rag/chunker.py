"""Split a document into overlapping, sentence-aligned chunks."""
import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n\s*\n")


@dataclass
class Chunk:
    id: int
    text: str


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text)
    return [" ".join(p.split()) for p in parts if p and p.strip()]


def chunk_text(text: str, max_words: int = 120, overlap_sentences: int = 1) -> list[Chunk]:
    """Greedily pack sentences into chunks of ~max_words, carrying the last
    `overlap_sentences` sentences into the next chunk so context isn't cut mid-thought."""
    sentences = split_sentences(text)
    chunks, current, count = [], [], 0

    for sent in sentences:
        n = len(sent.split())
        if current and count + n > max_words:
            chunks.append(Chunk(len(chunks), " ".join(current)))
            current = current[-overlap_sentences:] if overlap_sentences else []
            count = sum(len(s.split()) for s in current)
        current.append(sent)
        count += n

    if current:
        chunks.append(Chunk(len(chunks), " ".join(current)))
    return chunks
