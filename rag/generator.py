"""Answer generation. Uses Claude when available; otherwise falls back to an
extractive answer built from the best-matching sentences."""
from .chunker import Chunk, split_sentences
from .retriever import tokenize

SYSTEM_PROMPT = (
    "You answer questions using only the provided context excerpts from a document. "
    "If the context does not contain the answer, say you couldn't find it in the document. "
    "Cite the excerpt numbers you used, like [1] or [2]."
)


def build_prompt(question: str, hits: list[tuple[Chunk, float]]) -> str:
    context = "\n\n".join(f"[{i + 1}] {chunk.text}" for i, (chunk, _) in enumerate(hits))
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


class ClaudeGenerator:
    def __init__(self, model: str = "claude-opus-5-5"):
        import anthropic  # imported lazily so the project runs without it

        self.client = anthropic.Anthropic()
        self.model = model

    def answer(self, question: str, hits: list[tuple[Chunk, float]]) -> str:
        if not hits:
            return "I couldn't find anything related to that in the document."
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": build_prompt(question, hits)}],
        )
        if response.stop_reason == "refusal":
            return "The model declined to answer this question."
        return "".join(b.text for b in response.content if b.type == "text").strip()


class ExtractiveGenerator:
    """Offline fallback: return the sentences that overlap most with the question."""

    def answer(self, question: str, hits: list[tuple[Chunk, float]], max_sentences: int = 3) -> str:
        if not hits:
            return "I couldn't find anything related to that in the document."
        q = set(tokenize(question))
        candidates = []
        for rank, (chunk, _) in enumerate(hits):
            for sent in split_sentences(chunk.text):
                overlap = len(q & set(tokenize(sent)))
                if overlap:
                    candidates.append((overlap, -rank, sent))
        candidates.sort(reverse=True)
        seen, picked = set(), []
        for _, _, sent in candidates:
            if sent not in seen:
                seen.add(sent)
                picked.append(sent)
            if len(picked) == max_sentences:
                break
        return " ".join(picked) or hits[0][0].text
