"""Split a document into overlapping, sentence-aligned chunks that remember
which section each sentence belongs to."""
import re
from dataclasses import dataclass, field

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A full stop after these doesn't end a sentence ("Dr. Rao", "e.g. this", "A. Kumar").
_ABBREVIATION = re.compile(
    r"(?:^|[\s(])(?:dr|mr|mrs|ms|prof|dept|figs?|eq|vs|cf|al|e\.g|i\.e|[a-z])\.$", re.IGNORECASE
)
# Contents-page lines: "Digital Watermarking 16", "Overview ..... 12", "4.1 | Design | 28",
# and "4.2 Database Design ." where dot leaders were cut off at a sentence break.
_TOC_LINE = re.compile(r"^.{1,80}?(?:\s|\.{2,}|…+|\|)\s*\d{1,3}$|^.{1,80}\s\.$")
# Thank-you, certificate and declaration pages: real text, but rarely what a question is after.
_BOILERPLATE = re.compile(
    r"\b(?:thank|thanks|grateful|gratitude|indebted|acknowledge?ments?|this is to certify"
    r"|partial fulfil\w*|we (?:hereby )?(?:declare|affirm)|ethical practices|keen interest)\b",
    re.IGNORECASE,
)
_NUMBERING = re.compile(r"^(?:chapter\s+)?\d+(?:\.\d+)*[.:)]?\s+", re.IGNORECASE)
# "1.5 Significance" is clearly a numbered heading; "12 Apple trees" may be a quantity.
DOTTED_NUMBER = re.compile(r"^\d+(?:\.\d+)+\s+")


@dataclass
class Sentence:
    text: str
    section: str = ""  # the heading this sentence falls under
    is_heading: bool = False


@dataclass
class Chunk:
    id: int
    text: str
    sentences: list[Sentence] = field(default_factory=list)


def split_sentences(text: str) -> list[str]:
    sentences = []
    for paragraph in _PARAGRAPH.split(text):
        pending = ""
        for piece in _SENTENCE_END.split(paragraph):
            pending = f"{pending} {piece}" if pending else piece
            if not _ABBREVIATION.search(pending):
                sentences.append(pending)
                pending = ""
        if pending:
            sentences.append(pending)
    return [" ".join(s.split()) for s in sentences if s.strip()]


def is_noise(text: str) -> bool:
    """Contents-page lines and thank-you/certificate wording."""
    return bool(_TOC_LINE.match(text) or _BOILERPLATE.search(text))


def section_name(heading: str) -> str:
    """'1.2 Problem Statement' -> 'problem statement'."""
    return _NUMBERING.sub("", heading).strip().lower()


def looks_like_heading(text: str) -> bool:
    return (
        len(text.split()) <= 7
        and DOTTED_NUMBER.sub("", text)[:1].isupper()
        and text[-1] not in ".!?:;,"
        and not any(c in text for c in "{}=();|")
        and not _TOC_LINE.match(text)
    )


def _is_banner(text: str) -> bool:
    """Long all-caps lines are cover-page and page-header text, not section titles."""
    return text.isupper() and len(text.split()) > 3


def label_sections(sentences: list[str]) -> list[Sentence]:
    """Tag each sentence with its section. Short lines right after one ending in
    ':' or ',' are list items, not headings, even though they look the same. The
    document's title isn't a section: it would claim to describe everything."""
    labelled, section, in_list = [], "", False
    for text in sentences:
        short = looks_like_heading(text)
        is_heading = short and not in_list
        if is_heading:
            # A heading right under another keeps its parent's meaning:
            # "Types of Watermarks" then "Visible Watermarks".
            parent = labelled[-1].text + " " if labelled and labelled[-1].is_heading else ""
            section = "" if not labelled or _is_banner(text) else parent + text
        labelled.append(Sentence(text, section, is_heading))
        in_list = text.endswith((":", ",")) or (in_list and short)
    return labelled


def _make_chunk(chunk_id: int, sentences: list[Sentence]) -> Chunk:
    return Chunk(chunk_id, " ".join(s.text for s in sentences), list(sentences))


def chunk_text(text: str, max_words: int = 120, overlap_sentences: int = 1) -> list[Chunk]:
    """Greedily pack sentences into chunks of ~max_words, carrying the last
    `overlap_sentences` sentences into the next chunk so context isn't cut mid-thought."""
    chunks, current, count = [], [], 0

    for sent in label_sections(split_sentences(text)):
        n = len(sent.text.split())
        if current and count + n > max_words:
            chunks.append(_make_chunk(len(chunks), current))
            current = current[-overlap_sentences:] if overlap_sentences else []
            count = sum(len(s.text.split()) for s in current)
        current.append(sent)
        count += n

    if current:
        chunks.append(_make_chunk(len(chunks), current))
    return chunks
