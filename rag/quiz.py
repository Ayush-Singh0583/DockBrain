"""Multiple-choice quizzes about one document, and grading them.

Every question is tied to one passage (a `Chunk`) and to a sentence quoted from it that
states the correct answer, so each answer can be traced back to the document.

Questions come from one of two places:

- **Offline:** a sentence from the document with one name or number blanked out. The
  wrong options are other names or numbers from elsewhere in the document, never words
  from the same sentence. Nothing is invented.
- **A model** (Ollama, Gemini or Claude, when the session uses one): it is shown only the
  chosen passages and asked for questions as JSON. Each question is checked in code: its
  quote must appear word for word in its passage, the quote must support the correct
  option, and no wrong option may be supported by the quote too. A question that fails is
  dropped. If none passes, or the provider fails outright, the quiz is built offline.
  `Quiz.notice` says when either happened.

A reference list isn't used either way: it would crowd out the document's own text.
"""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from .chunker import Chunk, Sentence, is_noise
from .retriever import STOPWORDS, tokenize

MAX_QUESTIONS = 10
BLANK = "_____"
MIN_OPTIONS = 3  # the correct answer and at least two wrong ones
MAX_OPTIONS = 4
SPARE_ITEMS = 3  # asked of a model beyond what's needed, since some will fail their checks
OPTION_IDS = "abcde"
_MIN_WORDS, _MAX_WORDS = 6, 45  # a sentence worth quizzing on

_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?![\w])")
_NAME = re.compile(r"\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+)*\b")
_CODE = re.compile(r"[{};=<>]|\(\)|^\s*(?:import|from|def|class|return|const|let|var|function)\b")
_CALENDAR = set(
    "january february march april may june july august september october november december "
    "monday tuesday wednesday thursday friday saturday sunday".split()
)


# Reference lists end in full stops, so they pass as statements.
_BACK_MATTER = re.compile(r"\b(?:references|bibliography|works cited|further reading|external links|see also)\s*$", re.I)
_REFERENCE_MARK = re.compile(r"\s*\[\d+\]")  # "…of wax.[12][13]"
_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|…)\s*")
_REFERS_TO_ITSELF = re.compile(
    r"\b(?:this|the|above|given)\s+(?:document|passage|text|excerpt)\b"
    r"|\bthis\s+(?:section|module|chapter|unit|lecture|paper|report)\b",
    re.I,
)


class InsufficientContent(ValueError):
    """The document has no plain statements to ask about."""


@dataclass
class Option:
    id: str
    text: str


@dataclass
class QuizQuestion:
    id: str
    prompt: str
    options: list[Option]
    correct_option_id: str
    explanation: str
    passage: Chunk  # where the answer comes from
    quote: str  # the sentence in `passage` that states the answer
    prompt_statement: str | None = None  # offline questions: the quote with the answer blanked


@dataclass
class Quiz:
    id: str
    title: str
    questions: list[QuizQuestion]
    engine: str  # who wrote the questions, e.g. "Gemini gemini-3.6-flash"
    notice: str | None = None  # why there are fewer questions, or why some were rebuilt


@dataclass
class QuestionResult:
    question: QuizQuestion
    selected: str | None  # the chosen option id, or None if unanswered
    correct: bool


@dataclass
class GradeResult:
    correct: int
    total: int
    results: list[QuestionResult] = field(default_factory=list)


class QuizWriter(Protocol):
    """A model that writes quiz questions. `write` raises RuntimeError if the provider fails."""

    name: str

    def write(self, prompt: str, instruction: str = ...) -> str: ...


# ----------------------------------------------------------------- offline questions

def _is_statement(s: Sentence) -> bool:
    words = s.text.split()
    # Headings never end with a full stop, so the punctuation check also leaves them out.
    return (
        _MIN_WORDS <= len(words) <= _MAX_WORDS
        and s.text.rstrip()[-1:] in ".!"
        and not is_noise(s.text)
        and not _CODE.search(s.text)
    )


def _norm(text: str) -> str:
    for fancy, plain in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")):
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _terms(sentence: str) -> list[tuple[str, str]]:
    """Names and numbers in a sentence that could be blanked: (text, kind)."""
    found = []
    for m in _NUMBER.finditer(sentence):
        value = m.group().replace(",", "")
        is_year = len(value) == 4 and value.isdigit() and 1000 <= int(value) <= 2100
        found.append((m.group(), "year" if is_year else "number"))
    for m in _NAME.finditer(sentence):
        name = m.group()
        words = name.split()
        # A sentence's first word is capitalised anyway, so there it takes two capitalised
        # words ("Ruth Adeyemi", not "The Orchard") to suggest a name.
        if m.start() == 0 and (len(words) < 2 or words[0].casefold() in STOPWORDS):
            continue
        if name.casefold() in _CALENDAR or not tokenize(name):
            continue
        found.append((name, "name"))
    return found


def _magnitude(text: str) -> float:
    try:
        return math.log10(float(text.replace(",", "")) + 1)
    except ValueError:
        return 0.0


class _OfflineBuilder:
    """Fill-in-the-blank questions from the document's own sentences."""

    def __init__(self, chunks: list[Chunk], rng: random.Random):
        self.rng = rng
        self.pool: dict[str, list[str]] = {"name": [], "number": [], "year": []}
        seen: set[str] = set()
        for chunk in chunks:
            for s in chunk.sentences:
                if not _is_statement(s):
                    continue
                for text, kind in _terms(s.text):
                    if _norm(text) not in seen:
                        seen.add(_norm(text))
                        self.pool[kind].append(text)

    def _distractors(self, answer: str, kind: str, sentence: str) -> list[str]:
        here = _norm(sentence)
        others = [t for t in self.pool[kind] if _norm(t) != _norm(answer) and _norm(t) not in here]
        if kind == "name":
            words = len(answer.split())
            self.rng.shuffle(others)
            others.sort(key=lambda t: abs(len(t.split()) - words))  # similar-looking names first
        else:
            others.sort(key=lambda t: abs(_magnitude(t) - _magnitude(answer)))
        return others[: MAX_OPTIONS - 1]

    def question(self, chunk: Chunk, sentence: str) -> tuple[str, str, list[str], str] | None:
        """(statement with a blank, answer, wrong options, quote), or None if nothing fits."""
        candidates = []
        for answer, kind in _terms(sentence):
            wrong = self._distractors(answer, kind, sentence)
            statement = sentence.replace(answer, BLANK)
            if len(wrong) + 1 >= MIN_OPTIONS and len(statement.replace(BLANK, "").split()) >= 4:
                candidates.append((statement, answer, wrong, sentence))
        return self.rng.choice(candidates) if candidates else None

    def questions_in(self, chunk: Chunk, used: set[str]):
        """Every offline question one passage allows, skipping sentences already used."""
        for s in chunk.sentences:
            if _is_statement(s) and _norm(s.text) not in used:
                q = self.question(chunk, s.text)
                if q:
                    yield q


def _spread(items: list, count: int) -> list:
    """`count` items evenly spaced through the list, keeping its order."""
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[0]]
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


# ------------------------------------------------------------------- model questions

QUIZ_INSTRUCTION = (
    "You write multiple-choice quiz questions for someone studying a document. Use only facts "
    "stated in the numbered passages you are given, never outside knowledge. Reply with JSON only."
)


def numbered_passages(passages: list[Chunk]) -> str:
    """The passages as a model sees them: "[1] Section: …" then the text."""
    blocks = []
    for i, chunk in enumerate(passages, start=1):
        section = next((s.section for s in chunk.sentences if s.section), "")
        blocks.append(f"[{i}]" + (f" Section: {section}" if section else "") + f"\n{chunk.text}")
    return "\n\n".join(blocks)


def quiz_prompt(passages: list[Chunk], count: int | None = None) -> str:
    """The request for `count` questions (default: one per passage) about these passages."""
    count = count or len(passages)
    per_passage = -(-count // len(passages))
    if per_passage == 1:
        task = f"Write {count} multiple-choice questions: one about each numbered passage below."
    else:
        task = (f"Write {count} multiple-choice questions about the numbered passages below: at most "
                f"{per_passage} about any one passage, each about a different fact.")
    return (
        f"{task}\n\n"
        "Rules:\n"
        "- Ask about a fact the passage states. Never use outside knowledge.\n"
        "- The question must make sense on its own. Never mention the passage, document, module, chapter or page.\n"
        "- Ignore page numbers, running headers, course or module titles, author names and reference entries.\n"
        f"- Give exactly {MAX_OPTIONS} short options. Exactly one is correct according to the passage; "
        "the others must be wrong according to it.\n"
        '- "quote" is the sentence from the passage that states the correct answer, copied word for word.\n'
        '- "answer" is the 0-based position of the correct option.\n'
        "- Skip a passage that has no clear fact to ask about.\n\n"
        "Reply with JSON only, in this form:\n"
        '{"questions": [{"passage": 1, "question": "...", "options": ["...", "...", "...", "..."], '
        '"answer": 0, "quote": "..."}]}\n\n'
        "Passages:\n\n" + numbered_passages(passages)
    )


def json_object(reply: str) -> dict | None:
    """The JSON object in a model's reply, or None if it hasn't sent one."""
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(reply[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _parse_reply(reply: str) -> list | None:
    questions = (json_object(reply) or {}).get("questions")
    return questions if isinstance(questions, list) else None


def passage_number(item, total: int) -> int | None:
    """Which of `total` numbered passages a model's item cites (1-based), if a valid one."""
    index = item.get("passage") if isinstance(item, dict) else None
    index = int(index) if isinstance(index, str) and index.isdigit() else index
    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= total:
        return None
    return index


def _comparable(text: str) -> str:
    return " ".join(re.findall(r"\w+", _REFERENCE_MARK.sub("", text).casefold()))


def verbatim_quote(quote, passage: Chunk) -> str | None:
    """A model's quote, tidied, if it really is word for word from the passage. Punctuation
    and reference marks don't count, and a quote shortened with "…" passes if each piece is
    there, in order."""
    if not isinstance(quote, str):
        return None
    quote = quote.strip().strip("\"'“”‘’").strip()
    if len(quote.split()) < 4:
        return None
    source, position = _comparable(passage.text), 0
    for piece in filter(None, map(_comparable, _ELLIPSIS.split(quote))):
        found = source.find(piece, position)
        if found < 0:
            return None
        position = found + len(piece)
    return quote


def per_passage_limit(count: int, wanted: int, passages: int) -> int:
    """How many items one passage may give: one each when there are enough passages, so a
    set stays spread out; on a short document, enough that the spares can still be used."""
    return 1 if passages >= count else -(-wanted // passages)


def cited_passage(item, passages: list[Chunk]) -> int | None:
    """Which passage a model's item comes from (1-based), if it gave a valid number. The
    number is corrected if the quote is really in another of these passages: where the
    quote is found is what grounds the item."""
    index = passage_number(item, len(passages))
    if index is None or verbatim_quote(item.get("quote"), passages[index - 1]):
        return index
    return next((n for n, p in enumerate(passages, start=1) if verbatim_quote(item.get("quote"), p)), index)


def refers_to_itself(question: str) -> bool:
    """True for "… in this module?": a question that makes no sense away from the document."""
    return bool(_REFERS_TO_ITSELF.search(question))


def _supported(option: str, quote_terms: set[str]) -> float:
    """The share of an option's words that the quote contains."""
    terms = set(tokenize(option))
    return len(terms & quote_terms) / len(terms) if terms else 0.0


def _checked(item, passage: Chunk) -> tuple[str, list[str], int, str] | None:
    """(question, options, answer index, quote) if a model's question is grounded, else None."""
    if not isinstance(item, dict):
        return None
    question, options, answer, quote = item.get("question"), item.get("options"), item.get("answer"), item.get("quote")
    if not (isinstance(question, str) and 5 <= len(question.strip()) <= 300) or refers_to_itself(question):
        return None
    if not (isinstance(options, list) and MIN_OPTIONS <= len(options) <= len(OPTION_IDS)):
        return None
    if not all(isinstance(o, str) and 0 < len(o.strip()) <= 200 for o in options):
        return None
    options = [o.strip() for o in options]
    if len({_norm(o) for o in options}) != len(options):
        return None
    if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer < len(options):
        return None
    quote = verbatim_quote(quote, passage)
    if quote is None:
        return None
    quote_terms = set(tokenize(quote))
    if _supported(options[answer], quote_terms) < 0.5:
        return None  # the quote doesn't state the answer
    for i, option in enumerate(options):
        if i != answer and tokenize(option) and _supported(option, quote_terms) == 1.0:
            return None  # the quote would support a wrong option too
    return question.strip(), options, answer, quote


class _GeminiWriter:
    def __init__(self, generator):
        self.generator = generator
        self.name = f"Gemini {generator.model}"

    def write(self, prompt: str, instruction: str = QUIZ_INSTRUCTION) -> str:
        from .generator import QUESTION_ATTEMPTS

        g = self.generator
        g._attempts_left = QUESTION_ATTEMPTS  # the same budget as one question
        return g._read_text(g._post({
            "model": g.model,
            "input": prompt,
            "system_instruction": instruction,
            "generation_config": {"thinking_level": "low"},
            "store": False,
        }))


class _ClaudeWriter:
    def __init__(self, generator):
        self.generator = generator
        self.name = "Claude"

    def write(self, prompt: str, instruction: str = QUIZ_INSTRUCTION) -> str:
        from .generator import _claude_errors

        client = self.generator.client
        if hasattr(client, "with_options"):
            client = client.with_options(max_retries=1)
        try:
            response = client.beta.messages.create(
                model=self.generator.model,
                max_tokens=16000,
                system=instruction,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            )
        except _claude_errors() as e:
            raise RuntimeError(f"Claude couldn't be reached ({e})") from None
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to write this quiz")
        return "".join(b.text for b in response.content if b.type == "text")


class _OllamaWriter:
    def __init__(self, generator):
        self.generator = generator
        self.name = f"Ollama {generator.model}"

    def write(self, prompt: str, instruction: str = QUIZ_INSTRUCTION) -> str:
        return self.generator.chat(instruction, prompt, as_json=True)


def writer_for(generator) -> QuizWriter | None:
    """The quiz writer for a session's answer generator, or None for offline answers.

    A generator can supply its own by having a `quiz_writer` attribute (tests use this).
    """
    custom = getattr(generator, "quiz_writer", None)
    if custom is not None:
        return custom
    from .generator import ClaudeGenerator, GeminiGenerator, OllamaGenerator

    if isinstance(generator, OllamaGenerator):
        return _OllamaWriter(generator)
    if isinstance(generator, GeminiGenerator):
        return _GeminiWriter(generator)
    if isinstance(generator, ClaudeGenerator):
        return _ClaudeWriter(generator)
    return None


# --------------------------------------------------------------------------- quiz

OFFLINE_ENGINE = "Built from the document's sentences"


def body_sentences(chunks: list[Chunk]) -> list[tuple[Chunk, Sentence]]:
    """Each (passage, sentence) of the document's text, without its reference list.

    A reference list is recognised by its heading. From one in the second half of the
    document, everything to the end is left out, because the entries that follow are often
    mistaken for more headings. One earlier on, such as a line in a table of contents,
    leaves out only its own section.
    """
    pairs = [(chunk, sentence) for chunk in chunks for sentence in chunk.sentences]
    in_list = [bool(_BACK_MATTER.search(sentence.section or "")) for _, sentence in pairs]
    end = next((i for i, listed in enumerate(in_list) if listed and i >= len(pairs) / 2), len(pairs))
    return [pair for pair, listed in zip(pairs[:end], in_list) if not listed]


def body_passages(chunks: list[Chunk]) -> list[Chunk]:
    """The passages that hold the document's own text, in order, each without any
    sentences of a reference list that it runs into."""
    kept: dict[int, list[Sentence]] = {}
    for chunk, sentence in body_sentences(chunks):
        kept.setdefault(chunk.id, []).append(sentence)
    return [Chunk(chunk_id, " ".join(s.text for s in sentences), sentences) for chunk_id, sentences in kept.items()]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def build_quiz(chunks: list[Chunk], count: int, *, title: str, seed=None,
               writer: QuizWriter | None = None, quiz_id: str = "quiz") -> Quiz:
    """A quiz of up to `count` questions spread through the document.

    Raises InsufficientContent if not even one grounded question can be made, and
    ValueError if `count` is outside 1..MAX_QUESTIONS.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_QUESTIONS:
        raise ValueError(f"A quiz has 1 to {MAX_QUESTIONS} questions.")
    rng = random.Random(seed)
    chunks = body_passages(chunks)
    offline = _OfflineBuilder(chunks, rng)
    used: set[str] = set()

    # A model can ask about any passage with a statement in it.
    writable = [c for c in chunks if any(_is_statement(s) for s in c.sentences)]
    notices: list[str] = []
    drafts: list[tuple[Chunk, tuple]] = []  # (passage, ("model", ...) | ("offline", ...))

    if writer is not None and writable:
        wanted = count + SPARE_ITEMS
        passages = _spread(writable, wanted)
        per_passage = per_passage_limit(count, wanted, len(passages))
        written: list[tuple[Chunk, tuple]] = []
        asked: dict[int, int] = {}
        provider_failed = False
        try:
            items = _parse_reply(writer.write(quiz_prompt(passages, wanted)))
        except RuntimeError as e:
            items, provider_failed = None, True
            notices.append(f"The questions were built directly from the document's sentences, because "
                           f"{writer.name} couldn't write them: {str(e).rstrip('.')}.")
        for item in items or []:
            index = cited_passage(item, passages)
            if index is None or asked.get(index, 0) >= per_passage:
                continue
            checked = _checked(item, passages[index - 1])
            if checked and _norm(checked[3]) not in used:
                written.append((passages[index - 1], ("model", *checked)))
                asked[index] = asked.get(index, 0) + 1
                used.add(_norm(checked[3]))
        # With nothing usable from the model, build the quiz from the passages' own sentences,
        # taking turns between passages so it stays spread out, then from the rest of the
        # document. A shorter quiz of the model's questions beats padding it with blanks.
        filled: list[tuple[Chunk, tuple]] = []
        sources = [(p, offline.questions_in(p, used)) for p in passages + [c for c in writable if c not in passages]]
        while not written and len(filled) < count and sources:
            remaining = []
            for passage, questions in sources:
                if len(filled) >= count:
                    break
                q = next(questions, None)
                if q:
                    used.add(_norm(q[3]))
                    filled.append((passage, ("offline", *q)))
                    remaining.append((passage, questions))
            sources = remaining
        if filled and not provider_failed:
            notices.append(f"{_plural(len(filled), 'question')} of {len(filled)} rebuilt from the "
                           f"document's sentences, because {writer.name}'s version couldn't be matched to its passage.")
        drafts = _spread(sorted(written + filled, key=lambda draft: draft[0].id), count)  # in document order
    else:
        candidates = []
        for chunk in chunks:
            # Passages overlap by a sentence; questions_in skips sentences already used.
            for q in offline.questions_in(chunk, used):
                used.add(_norm(q[3]))
                candidates.append((chunk, ("offline", *q)))
        drafts = _spread(candidates, count)

    if not drafts:
        raise InsufficientContent(
            "This document doesn't have enough plain statements with names or numbers to build a quiz from."
        )
    if len(drafts) < count:
        notices.append(f"Only {_plural(len(drafts), 'question')} could be written from this document.")

    questions = []
    for n, (passage, draft) in enumerate(drafts, start=1):
        if draft[0] == "model":
            _, prompt, texts, answer, quote = draft
            statement = None
        else:
            _, statement, answer_text, wrong, quote = draft
            texts = [answer_text, *wrong]
            rng.shuffle(texts)
            answer = texts.index(answer_text)
            prompt = f"Fill in the blank, from the document: “{statement}”"
        options = [Option(OPTION_IDS[i], text) for i, text in enumerate(texts)]
        questions.append(QuizQuestion(
            id=f"q{n}",
            prompt=prompt,
            options=options,
            correct_option_id=options[answer].id,
            explanation=f"The document says: “{quote}”",
            passage=passage,
            quote=quote,
            prompt_statement=statement,
        ))
    return Quiz(id=quiz_id, title=title, questions=questions,
                engine=writer.name if writer is not None else OFFLINE_ENGINE,
                notice=" ".join(notices) or None)


def grade(quiz: Quiz, answers: list[tuple[str, str]]) -> GradeResult:
    """Score answers given as (question id, option id) pairs. Unanswered questions count as wrong.

    Raises ValueError for an unknown question or option, or a question answered twice.
    """
    by_id = {q.id: q for q in quiz.questions}
    chosen: dict[str, str] = {}
    for question_id, option_id in answers:
        question = by_id.get(question_id)
        if question is None:
            raise ValueError(f"This quiz has no question '{question_id}'.")
        if question_id in chosen:
            raise ValueError(f"Question '{question_id}' was answered more than once.")
        if option_id not in {o.id for o in question.options}:
            raise ValueError(f"Question '{question_id}' has no option '{option_id}'.")
        chosen[question_id] = option_id
    results = [
        QuestionResult(q, chosen.get(q.id), chosen.get(q.id) == q.correct_option_id)
        for q in quiz.questions
    ]
    return GradeResult(correct=sum(r.correct for r in results), total=len(results), results=results)
