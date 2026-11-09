"""Memory cards (flashcards) for one document.

Each card has a question on the front and an answer on the back, tied to one sentence of
one passage (a `Chunk`), which the card cites.

With a model (Ollama, Gemini or Claude), it writes the cards from chosen passages, and each
is checked in code: its quote must be word for word from its passage, the quote must
support the answer, and the question must make sense alone without giving the answer away.
Cards that fail are dropped. If none passes, or the model fails, cards are built offline
and `CardSet.notice` says so.

Offline, or as that fallback, the answer appears word for word in the sentence.

Which sentences qualify, and which words can be asked about, start from the quiz's
safeguards in rag/quiz.py. Cards are stricter: they also skip reference lists, citations,
book titles and lists of names, so a long bibliography can't crowd out the document.

Offline cards are of two kinds:

- **definition:** "X is a …" gives the front "What is X?" and the back "a …";
- **cloze:** a sentence with one name or number blanked out gives the front
  "Fill in the blank: “… _____ …”" and the back the blanked words.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .chunker import Chunk
from .quiz import (BLANK, SPARE_ITEMS, InsufficientContent, QuizWriter, _is_statement, _norm, _spread, _supported,
                   _terms, body_passages, body_sentences, cited_passage, json_object, numbered_passages, per_passage_limit,
                   refers_to_itself, verbatim_quote)
from .retriever import tokenize

MAX_CARDS = 20
DEFAULT_CARDS = 10

# "Harbor Lights is a volunteer program …", "The Copper Spire is the tallest tower …",
# "An apple is the fruit …". "The result is a …" isn't one: it needs its context.
_DEFINITION = re.compile(
    r"^(?P<term>(?:(?:The|An?)\s+)?[A-Z][\w+.-]*(?:\s+[A-Z][\w+.-]*){0,3}|An?\s+[a-z][\w-]*(?:\s+[a-z][\w-]*){0,2})"
    r"\s+(?P<verb>is|are)\s+"
    r"(?P<answer>(?:a|an|the)\s+.+?)[.!]$"
)
_NOT_TERMS = {
    "it", "this", "that", "these", "those", "they", "there", "he", "she", "we", "our", "each", "every",
    "its", "their", "his", "her", "my", "your", "some", "many", "most", "several", "such", "both", "another",
}

# Citations and titles end in full stops, so they pass as statements. They make useless cards.
_CITATION = re.compile(
    r"https?://|\bwww\.|\b(?:Archived|Retrieved)\b|\bet al\b"
    r"|(?i:\bdoi\b|\bISBN\b|\bISSN\b|\bPMID\b|\barXiv\b)"
)
_MIN_LOWERCASE = 0.4  # of a sentence's words; book titles and lists of names have fewer
_MAX_ANSWER_WORDS = 25

CARDS_INSTRUCTION = (
    "You write flashcards for someone studying a document. Use only facts stated in the numbered "
    "passages you are given, never outside knowledge. Reply with JSON only."
)


@dataclass
class Card:
    id: str
    kind: str  # "definition" or "cloze" (built offline), or "question" (written by a model)
    prompt: str  # the front
    answer: str  # the back: words from `quote`, or a model's short answer that `quote` supports
    quote: str  # the sentence the card comes from, word for word
    passage: Chunk  # the passage that sentence is in


@dataclass
class CardSet:
    id: str
    title: str
    cards: list[Card]
    notice: str | None = None  # why there are fewer cards than asked for


def build_cards(chunks: list[Chunk], count: int = DEFAULT_CARDS, *, title: str,
                set_id: str = "cards", seed=None, writer: QuizWriter | None = None) -> CardSet:
    """Up to `count` cards spread through the document, in document order.

    Raises InsufficientContent if not even one grounded card can be made, and ValueError
    if `count` isn't a whole number from 1 to MAX_CARDS.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_CARDS:
        raise ValueError(f"A set has 1 to {MAX_CARDS} cards.")
    rng = random.Random(seed)
    reason = None
    if writer is not None:
        written, reason = _written_cards(chunks, count, writer)
        if written:
            cards = [Card(f"c{n}", "question", prompt, answer, quote, chunk)
                     for n, (chunk, prompt, answer, quote) in enumerate(written, start=1)]
            return CardSet(set_id, title, cards, _too_few(len(cards), count))
    candidates, used = [], set()
    for chunk, sentence in body_sentences(chunks):
        # Passages overlap by a sentence; each sentence gives at most one card.
        if not _is_statement(sentence) or not _reads_as_prose(sentence.text) or _norm(sentence.text) in used:
            continue
        card = _card_for(sentence.text, rng)
        if card:
            used.add(_norm(sentence.text))
            candidates.append((chunk, card))
    if not candidates:
        raise InsufficientContent(
            "This document doesn't have enough plain statements to make memory cards from. "
            "Cards need full sentences that define something or mention a name or a number."
        )
    picked = _spread(candidates, count)
    cards = [Card(f"c{n}", kind, prompt, answer, quote, chunk)
             for n, (chunk, (kind, prompt, answer, quote)) in enumerate(picked, start=1)]
    notice = " ".join(part for part in (reason, _too_few(len(cards), count)) if part) or None
    return CardSet(set_id, title, cards, notice)


def _too_few(made: int, asked: int) -> str | None:
    if made >= asked:
        return None
    return f"Only {made} card{'' if made == 1 else 's'} could be made from this document."


def cards_prompt(passages: list[Chunk], count: int) -> str:
    """The request for `count` cards about these numbered passages."""
    per_passage = -(-count // len(passages))
    return (
        f"Write {count} flashcards about the numbered passages below: at most {per_passage} about any "
        "one passage, each about a different idea.\n\n"
        "Rules:\n"
        "- Test an important idea, definition, cause or fact from the passage. Skip trivia.\n"
        "- The question must make sense on its own. Never mention the passage, document, module, chapter or page.\n"
        "- Ignore page numbers, running headers, course or module titles, author names and reference entries.\n"
        '- "answer" is short: a few words, at most one sentence. The question must not contain the answer.\n'
        '- "quote" is the sentence from the passage that states the answer, copied word for word.\n'
        "- Skip a passage that has no clear idea to test.\n\n"
        "Reply with JSON only, in this form:\n"
        '{"cards": [{"passage": 1, "question": "...", "answer": "...", "quote": "..."}]}\n\n'
        "Passages:\n\n" + numbered_passages(passages)
    )


def _checked_card(item, passage: Chunk) -> tuple[str, str, str] | None:
    """(question, answer, quote) if a model's card is grounded in its passage, else None."""
    if not isinstance(item, dict):
        return None
    question, answer = item.get("question"), item.get("answer")
    if not (isinstance(question, str) and 8 <= len(question.strip()) <= 300) or refers_to_itself(question):
        return None
    if not (isinstance(answer, str) and 1 <= len(answer.split()) <= _MAX_ANSWER_WORDS):
        return None
    quote = verbatim_quote(item.get("quote"), passage)
    if quote is None or _CITATION.search(quote):
        return None
    if _supported(answer, set(tokenize(quote))) < 0.5:
        return None  # the quote doesn't state the answer
    if _supported(answer, set(tokenize(question))) == 1.0:
        return None  # the front gives the answer away
    return question.strip(), answer.strip(), quote


def _written_cards(chunks: list[Chunk], count: int, writer: QuizWriter) -> tuple[list[tuple], str | None]:
    """A model's grounded cards as (passage, question, answer, quote) in document order,
    and, if there are none, why they will be built from the document's sentences."""
    passages = [c for c in body_passages(chunks) if any(_is_statement(s) for s in c.sentences)]
    if not passages:
        return [], None
    wanted = count + SPARE_ITEMS
    picked = _spread(passages, wanted)
    per_passage = per_passage_limit(count, wanted, len(picked))
    built_from = "These cards were built directly from the document's sentences, because"
    try:
        reply = writer.write(cards_prompt(picked, wanted), instruction=CARDS_INSTRUCTION)
    except RuntimeError as e:
        return [], f"{built_from} {writer.name} couldn't write them: {str(e).rstrip('.')}."
    items = (json_object(reply) or {}).get("cards")
    written, used, asked = [], set(), {}
    for item in items if isinstance(items, list) else []:
        index = cited_passage(item, picked)
        if index is None or asked.get(index, 0) >= per_passage:
            continue
        checked = _checked_card(item, picked[index - 1])
        if checked and _norm(checked[2]) not in used:
            used.add(_norm(checked[2]))
            asked[index] = asked.get(index, 0) + 1
            written.append((picked[index - 1], *checked))
    if not written:
        return [], f"{built_from} {writer.name}'s versions couldn't be matched to the document."
    return _spread(sorted(written, key=lambda card: card[0].id), count), None


def _reads_as_prose(sentence: str) -> bool:
    """False for citations, book titles and lists of names."""
    if _CITATION.search(sentence):
        return False
    words = sentence.split()
    return sum(word[0].islower() for word in words) >= len(words) * _MIN_LOWERCASE


def _card_for(sentence: str, rng: random.Random) -> tuple[str, str, str, str] | None:
    """(kind, front, back, quote) for one sentence, or None if it suits neither kind."""
    definition = _DEFINITION.match(sentence)
    if definition:
        term, answer = definition["term"], definition["answer"]
        words = term.split()
        if words[-1].casefold() not in _NOT_TERMS and words[0].casefold() not in _NOT_TERMS and len(answer.split()) >= 3:
            if words[0] in ("The", "A", "An"):
                term = " ".join([words[0].lower(), *words[1:]])
            return "definition", f"What {definition['verb']} {term}?", answer, sentence
    blankable = [text for text, _ in _terms(sentence) if f"[{text}]" not in sentence]  # not reference marks
    rng.shuffle(blankable)
    for answer in blankable:
        statement = sentence.replace(answer, BLANK, 1)
        if len(statement.replace(BLANK, "").split()) >= 4 and answer not in statement:
            return "cloze", f"Fill in the blank: “{statement}”", answer, sentence
    return None
