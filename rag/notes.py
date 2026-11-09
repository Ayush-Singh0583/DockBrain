"""Study notes for a document. The shape is the web app's `Notes` (FRONTEND/API_CONTRACT.md).

With a model (Ollama, Gemini or Claude), it writes the summary, sections and points from
chosen passages. Each point is checked in code: it must give a quote that is word for word
from the passage it cites, and most of its words must be in that passage. Points that fail
are dropped, and so are summary sentences the passages don't support. If nothing is left,
or the model fails, the notes are built offline and `notice` says so.

Offline, every point is a sentence quoted from the document, and cites its passage:

- title: the document's title line, or the file name.
- summary: the opening of its abstract, introduction or overview (as the offline answer
  to "What is this document about?").
- sections: in document order, each section's most informative sentences (rare words
  count most; thank-yous, contents lines and code don't count).
- suggestedQuestions: "What is X?" for terms the document defines ("X is a …"), which
  the offline answers handle well.
"""
import re
from pathlib import PurePath

from .chunker import Chunk, Sentence, is_noise
from .generator import _CODE_LINE, ExtractiveGenerator, _is_statement
from .quiz import (QuizWriter, _spread, _supported, body_passages, cited_passage, json_object, numbered_passages,
                   verbatim_quote, writer_for)
from .retriever import tokenize

MAX_SECTIONS = 8
POINTS_PER_SECTION = 3
SUMMARY_WORDS = 60
MAX_POINT_WORDS = 60
MAX_SUGGESTIONS = 3
UNTITLED_SECTION = "Key points"
MAX_NOTE_PASSAGES = 40  # what a laptop's model can read and answer within its context
MAX_NOTE_CHARS = 28000  # the same limit for documents whose passages run long
MAX_WRITTEN_POINTS = 4  # per section
MAX_HEADING_WORDS = 10
MAX_POINT_CHARS = 400
_MIN_SUPPORT = 0.6  # of a written point's or summary sentence's words found in the passages

NOTES_INSTRUCTION = (
    "You write study notes about a document for someone learning it. Use only what the numbered "
    "passages say, never outside knowledge. Reply with JSON only."
)

_NUMBERING = re.compile(r"^(?:chapter\s+)?\d+(?:\.\d+)*[.:)]?\s+", re.IGNORECASE)
_REFERENCE = re.compile(r"\[\d+\]")  # "Synonyms[2][3]": reference markers in a heading
# "Harbor Lights is a volunteer program …": a term the document defines.
_DEFINES_TERM = re.compile(r"^((?:[A-Z][\w+.-]*)(?:\s+[A-Z][\w+.-]*){0,2})\s+(is|are)\s+(?:a|an|the)\s")
_NOT_TERMS = {"it", "this", "that", "these", "those", "they", "there", "the", "a", "an", "we", "our", "each"}


def make_notes(rag, display_name: str) -> dict:
    """Notes for an indexed document (`rag.RAG`), written by its model if it has one."""
    notes = _offline_notes(rag, display_name)
    writer = writer_for(rag.generator)
    if writer is None:
        return notes
    written, problem = _written_notes(rag.chunks, writer)
    return {**notes, **written} if written else {**notes, "notice": problem}


def notes_prompt(passages: list[Chunk]) -> str:
    """The request for notes about these numbered passages."""
    return (
        "Write study notes about the numbered passages below, which come from one document.\n\n"
        "Rules:\n"
        "- Use only what the passages say. Never add outside knowledge.\n"
        '- "summary": 2 to 4 sentences on what the document is about and its main points.\n'
        f'- "sections": 3 to {MAX_SECTIONS} sections, one for each main topic, named in plain words. '
        "Never name a section after a page, chapter, module or course.\n"
        f"- Each section has 2 to {MAX_WRITTEN_POINTS} points. Each point is one complete idea, at most 30 "
        "words, keeping the document's own terms.\n"
        '- Each point gives "passage", the number of the passage it comes from, and "quote", the sentence '
        "from that passage that supports it, copied word for word.\n"
        "- Ignore page numbers, running headers, course or module titles, author names and reference entries.\n"
        '- "questions": 3 questions a reader could ask that the passages answer.\n\n'
        "Reply with JSON only, in this form:\n"
        '{"summary": "...", "sections": [{"heading": "...", "points": [{"text": "...", "passage": 1, '
        '"quote": "..."}]}], "questions": ["..."]}\n\n'
        "Passages:\n\n" + numbered_passages(passages)
    )


def _checked_point(point, passages: list[Chunk]) -> tuple[str, Chunk] | None:
    """(text, passage) if a model's point is grounded in the passage it cites, else None."""
    index = cited_passage(point, passages)
    if index is None:
        return None
    text, passage = point.get("text"), passages[index - 1]
    if not (isinstance(text, str) and 8 <= len(text.strip()) <= MAX_POINT_CHARS):
        return None
    if verbatim_quote(point.get("quote"), passage) is None:
        return None
    return (text.strip(), passage) if _supported(text, set(tokenize(passage.text))) >= _MIN_SUPPORT else None


def _supported_summary(summary, passages: list[Chunk]) -> str:
    """The summary's sentences that the passages support."""
    if not isinstance(summary, str):
        return ""
    known = {term for passage in passages for term in tokenize(passage.text)}
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+", summary.strip()) if _supported(s, known) >= _MIN_SUPPORT)


def _sampled(passages: list[Chunk]) -> list[Chunk]:
    """Passages spread through the document, as many as fit what the model can read."""
    for count in range(min(len(passages), MAX_NOTE_PASSAGES), 1, -1):
        picked = _spread(passages, count)
        if sum(len(p.text) for p in picked) <= MAX_NOTE_CHARS:
            return picked
    return passages[:1]


def _written_notes(chunks: list[Chunk], writer: QuizWriter) -> tuple[dict | None, str | None]:
    """The fields a model's grounded notes replace, or None and why it couldn't write them."""
    built_from = "These notes were built directly from the document's sentences, because"
    passages = _sampled(body_passages(chunks))
    if not passages:
        return None, None
    try:
        reply = writer.write(notes_prompt(passages), instruction=NOTES_INSTRUCTION)
    except RuntimeError as e:
        return None, f"{built_from} {writer.name} couldn't write them: {str(e).rstrip('.')}."
    data = json_object(reply) or {}
    raw_sections = data.get("sections") if isinstance(data.get("sections"), list) else []

    sources: dict[int, int] = {}  # chunk id -> citation index, in order of first use
    by_id = {chunk.id: chunk for chunk in passages}
    sections = []
    for raw in raw_sections[:MAX_SECTIONS]:
        heading = raw.get("heading") if isinstance(raw, dict) else None
        if not (isinstance(heading, str) and 1 <= len(heading.split()) <= MAX_HEADING_WORDS):
            continue
        raw_points = raw.get("points") if isinstance(raw.get("points"), list) else []
        checked = [c for c in (_checked_point(p, passages) for p in raw_points) if c][:MAX_WRITTEN_POINTS]
        if checked:
            sections.append({
                "id": f"s{len(sections) + 1}",
                "heading": heading.strip(),
                "points": [{"text": text, "citations": [sources.setdefault(chunk.id, len(sources) + 1)]}
                           for text, chunk in checked],
            })
    if not sections:
        return None, f"{built_from} {writer.name}'s notes couldn't be matched to the document."

    written = {"sections": sections, "sources": [_citation(i, by_id[c]) for c, i in sources.items()]}
    summary = _supported_summary(data.get("summary"), passages)
    if summary:
        written["summary"] = summary
    questions = data.get("questions") if isinstance(data.get("questions"), list) else []
    questions = [q.strip() for q in questions if isinstance(q, str) and q.strip().endswith("?") and len(q) <= 150]
    if questions:
        written["suggestedQuestions"] = questions[:MAX_SUGGESTIONS]
    return written, None


def _offline_notes(rag, display_name: str) -> dict:
    ordered = _sentences_in_order(rag.chunks)
    title = _title(ordered, display_name)
    summary = ExtractiveGenerator(max_words=SUMMARY_WORDS)._overview(
        rag.retriever.search("What is this document about?", 4)
    )
    summarised = {s.text for s in summary}

    sources: dict[int, int] = {}  # chunk id -> citation index, in order of first use

    def cite(chunk: Chunk) -> int:
        return sources.setdefault(chunk.id, len(sources) + 1)

    sections = []
    for heading, members in _sections(ordered, title):
        picked = _key_points(members, rag.retriever.idf, summarised)
        if picked:
            sections.append({
                "id": f"s{len(sections) + 1}",
                "heading": heading,
                "points": [{"text": s.text, "citations": [cite(chunk)]} for s, chunk in picked],
            })
        if len(sections) == MAX_SECTIONS:
            break

    chunks = {chunk.id: chunk for chunk in rag.chunks}
    return {
        "title": title,
        "summary": " ".join(s.text for s in summary),
        "sections": sections,
        "sources": [_citation(index, chunks[chunk_id]) for chunk_id, index in sources.items()],
        "suggestedQuestions": _suggestions(ordered),
        "demo": False,
    }


def _sentences_in_order(chunks: list[Chunk]) -> list[tuple[Sentence, Chunk]]:
    """Each sentence once (chunks overlap by a sentence), with the first passage holding it."""
    seen, ordered = set(), []
    for chunk in chunks:
        for sentence in chunk.sentences:
            if sentence.text not in seen:
                seen.add(sentence.text)
                ordered.append((sentence, chunk))
    return ordered


def _title(ordered: list[tuple[Sentence, Chunk]], display_name: str) -> str:
    if ordered and ordered[0][0].is_heading and not is_noise(ordered[0][0].text):
        return ordered[0][0].text
    return PurePath(display_name).stem or display_name


def _sections(ordered: list[tuple[Sentence, Chunk]], title: str):
    """(heading, [(sentence, chunk)]) groups in document order. Text before the first
    heading (after the title) is grouped under "Key points"."""
    heading, members, groups = UNTITLED_SECTION, [], []
    for sentence, chunk in ordered:
        if sentence.is_heading:
            if sentence.text == title and not groups and not members:
                continue  # the title line names the document, not a section
            if members:
                groups.append((heading, members))
            heading, members = _heading(sentence.text), []
        else:
            members.append((sentence, chunk))
    if members:
        groups.append((heading, members))
    return groups


def _heading(text: str) -> str:
    """A heading as shown: without its number or reference markers."""
    return _REFERENCE.sub("", _NUMBERING.sub("", text)).strip() or text


def _key_points(members, idf: dict[str, float], skip: set[str]) -> list[tuple[Sentence, Chunk]]:
    """A section's most informative statements, in document order."""
    scored = []
    for position, (sentence, chunk) in enumerate(members):
        words = len(sentence.text.split())
        if (sentence.text in skip or not _is_statement(sentence) or is_noise(sentence.text)
                or _CODE_LINE.search(sentence.text) or not 4 <= words <= MAX_POINT_WORDS):
            continue
        tokens = tokenize(sentence.text)
        score = sum(idf.get(t, 0.0) for t in set(tokens)) / (1 + len(tokens) / 20)
        scored.append((score, position, sentence, chunk))
    best = sorted(scored, key=lambda x: -x[0])[:POINTS_PER_SECTION]
    return [(sentence, chunk) for _, _, sentence, chunk in sorted(best, key=lambda x: x[1])]


def _suggestions(ordered: list[tuple[Sentence, Chunk]]) -> list[str]:
    questions = []
    for sentence, _ in ordered:
        match = _DEFINES_TERM.match(sentence.text)
        if not match or sentence.is_heading or match[1].split()[0].lower() in _NOT_TERMS:
            continue
        question = f"What {match[2]} {match[1]}?"
        if question not in questions:
            questions.append(question)
        if len(questions) == MAX_SUGGESTIONS:
            break
    return questions


def _citation(index: int, chunk: Chunk) -> dict:
    out = {"index": index, "excerpt": chunk.text, "passageId": chunk.id}
    section = next((s.section for s in chunk.sentences if s.section), None)
    if section:
        out["section"] = section
    return out
