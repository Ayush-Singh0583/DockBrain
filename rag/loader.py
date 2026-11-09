"""Document loading. Each file type registers a loader keyed by extension."""
import logging
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .chunker import DOTTED_NUMBER, looks_like_heading

LOADERS = {}


def register(*extensions):
    def wrap(fn):
        for ext in extensions:
            LOADERS[ext] = fn
        return fn
    return wrap


@register(".txt", ".md", ".markdown")
def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_SKIP = {_MC_FALLBACK, _W + "pPr", _W + "rPr"}  # duplicate copies / formatting only


def _paragraph(p) -> list[str]:
    """Text of one paragraph, followed by any text boxes anchored inside it."""
    parts, boxes = [], []

    def walk(el):
        for child in el:
            tag = child.tag
            if tag in _SKIP:
                continue
            if tag == _W + "t":
                parts.append(child.text or "")
            elif tag == _W + "tab":
                parts.append("\t")
            elif tag in (_W + "br", _W + "cr"):
                parts.append("\n")
            elif tag == _W + "noBreakHyphen":
                parts.append("-")
            elif tag == _W + "txbxContent":
                boxes.extend(_blocks(child))
            else:
                walk(child)

    walk(p)
    text = "".join(parts).strip()
    return ([text] if text else []) + boxes


def _table(tbl) -> list[str]:
    """One block per row, cells separated by ' | ' so a row stays together."""
    rows = []
    for tr in tbl.findall(_W + "tr"):
        cells = [" ".join(_blocks(tc)) for tc in tr.findall(_W + "tc")]
        row = " | ".join(c for c in cells if c)
        if row:
            rows.append(row)
    return rows


def _blocks(el) -> list[str]:
    """Paragraphs and table rows in document order, descending into
    content controls and other wrappers."""
    out = []
    for child in el:
        tag = child.tag
        if tag in _SKIP:
            continue
        if tag == _W + "p":
            out.extend(_paragraph(child))
        elif tag == _W + "tbl":
            out.extend(_table(child))
        else:
            out.extend(_blocks(child))
    return out


@register(".docx")
def load_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise ValueError(
            f"{path.name} isn't a readable .docx file. "
            "If it's an old .doc file, open it in Word and save it as .docx."
        ) from None
    # Blank lines between blocks let the chunker treat headings and
    # table rows as their own units instead of gluing them to the next line.
    return "\n\n".join(_blocks(root))


_PAGE_NUMBER = re.compile(r"^(?:page\s+)?(\d{1,4})(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE)
_PAGE_WORD = re.compile(r"\b(?:page|pg)\b", re.IGNORECASE)
_TRAILING_NUMBER = re.compile(r"(.*\S)\s+(\d{1,4})")
_BULLET = re.compile(r"^(?:[•▪◦‣·*]|[–—-](?!\s*\d))\s+")  # a dash before a digit may be a minus sign
_UNFINISHED = set("a an and are as at but by for from in is of on or that the to was were which with".split())


def _page_lines(text: str) -> list[str]:
    """A page's lines, with ligatures like 'ﬁ' spelled out so words can be searched."""
    return [line.strip() for line in unicodedata.normalize("NFKC", text).strip().splitlines()]


def _edge_key(line: str) -> str:
    """What a line is compared by when looking for repeats. Digits are ignored only in a
    line that names a page, so 'Handbook page 3' matches 'Handbook page 4'."""
    return re.sub(r"\d+", "#", line) if _PAGE_WORD.search(line) else line


def _ends_sentence(text: str | None) -> bool:
    """True at the start of the document or after a finished sentence."""
    return not text or text[-1] in ".!?:"


def _strip_page_edges(pages: list[list[str]]) -> list[list[str]]:
    """Remove running headers, footers, and page numbers, but only with positive evidence,
    since clutter is better than a lost fact. A line counts as a header or footer if it repeats
    on many pages; one kept copy stays searchable. A line ending in a number ('Department of
    ISE 7') also needs that number to advance with the pages. A number on its own line counts
    as a page number only if it advances with the pages and either follows a finished
    sentence, interrupts one that carries on in lowercase after it, or belongs to numbering
    found on most pages of a longer document without following an unfinished phrase."""
    def edges(lines):
        return {*lines[:2], *lines[-2:]}

    def trailing(line, index):
        match = _TRAILING_NUMBER.fullmatch(line)
        return (match[1], int(match[2]) - index) if match and len(match[1].split()) >= 3 else None

    counts, prefixes, numbered_counts = Counter(), Counter(), Counter()
    for index, lines in enumerate(pages):
        counts.update({_edge_key(line) for line in edges(lines) if line})
        keys = {key for line in edges(lines) if line and (key := trailing(line, index))}
        numbered_counts.update(keys)
        prefixes.update({prefix for prefix, _ in keys})
    enough = max(3, len(pages) / 2)
    # A line ending mid-phrase ("The count was") is content even when it repeats.
    repeated = {line for line, count in counts.items()
                if count >= enough and line.split()[-1].lower() not in _UNFINISHED}
    numbered = {key for key, count in numbered_counts.items() if count >= 3 and prefixes[key[0]] >= enough}

    def furniture(line, index):
        """The key a running header or footer is known by, or None for content."""
        if _edge_key(line) in repeated:
            return _edge_key(line)
        key = trailing(line, index)
        return key[0] if key in numbered else None

    def text_lines(index):
        return [line for line in pages[index] if line and not furniture(line, index) and not _PAGE_NUMBER.match(line)]

    offsets = Counter()
    for index, lines in enumerate(pages):
        body = [line for line in lines if line and not furniture(line, index)]
        offsets.update({int(match[1]) - index for line in {*body[:1], *body[-1:]} if (match := _PAGE_NUMBER.match(line))})
    numbering = {offset for offset, count in offsets.items() if count >= max(2, min(3, len(pages)))}
    # Numbering on most pages of a longer document is strong evidence on its own.
    pagination = {offset for offset, count in offsets.items() if count >= max(5, 0.75 * len(pages))}

    def is_edge(line, index, before, after):
        if not line or furniture(line, index):
            return True
        match = _PAGE_NUMBER.match(line)
        if not match or int(match[1]) - index not in numbering:
            return False
        interrupts = bool(after) and after[0].islower()
        unfinished = bool(before) and (before.split()[-1].lower() in _UNFINISHED or before.endswith(","))
        strong = int(match[1]) - index in pagination and not unfinished
        return _ends_sentence(before) or interrupts or strong

    seen = set()

    def kept_once(lines, index):
        kept = []
        for line in lines:
            key = line and furniture(line, index)
            if key and key not in seen:
                seen.add(key)
                kept.append(line)
        return kept

    stripped = []
    for index, lines in enumerate(pages):
        this_page = text_lines(index)
        previous_page = text_lines(index - 1) if index else []
        next_page = text_lines(index + 1) if index + 1 < len(pages) else []
        before_page = previous_page[-1] if previous_page else None
        start, end = 0, len(lines)
        while start < end and is_edge(lines[start], index, before_page, this_page[0] if this_page else None):
            start += 1
        while end > start:
            above = [line for line in lines[start:end - 1] if line and not furniture(line, index)
                     and not _PAGE_NUMBER.match(line)]
            if not is_edge(lines[end - 1], index, above[-1] if above else before_page, next_page[0] if next_page else None):
                break
            end -= 1
        stripped.append(kept_once(lines[:start], index) + lines[start:end] + kept_once(lines[end:], index))
    return stripped


def _rejoin_hyphens(text: str) -> str:
    """Rejoin words split at a line end, unless the document writes them with a hyphen
    elsewhere ('fine-tuning') or they're part of a longer compound ('state-of-the-art')."""
    lowered = text.lower()

    def rejoin(match):
        compound = f"{match[1]}-{match[2]}"
        in_longer_compound = match.start() > 0 and text[match.start() - 1] == "-"
        return compound if in_longer_compound or compound.lower() in lowered else match[1] + match[2]

    return re.sub(r"([A-Za-z]*[a-z])-\n([a-z]+)", rejoin, text)


def _title_like(text: str) -> bool:
    """Headings are short or mostly capitalized, unlike a line of wrapped prose."""
    long_words = [word for word in text.split() if len(word) > 3]
    return len(text.split()) <= 3 or sum(word[0].isupper() for word in long_words) >= 0.6 * len(long_words)


def _join_pdf_lines(lines: list[str]) -> str:
    """PDFs store text one printed line at a time. Rejoin hyphenated words, and give
    headings and bullets their own blocks so the chunker can see them. Ambiguous short
    lines stay part of the surrounding text. Other single line breaks are harmless: the
    chunker reads them as spaces, so sentences stay whole."""
    lines = _rejoin_hyphens("\n".join(lines)).split("\n")
    typical = sorted(map(len, lines))[len(lines) * 3 // 4]  # not the longest: one wide line skews it
    parts, after_heading = [], False
    for i, line in enumerate(lines):
        previous = lines[i - 1] if i else ""
        following = lines[i + 1] if i + 1 < len(lines) else ""
        title = DOTTED_NUMBER.sub("", line)
        # A line well short of the usual width ends its paragraph or list item.
        starts_block = (
            title != line  # a number like "1.5" is a strong sign on its own
            or not previous
            or previous[-1] in ".!?:"
            or after_heading
            or len(previous) < 0.6 * typical
        )
        after_heading = bool(
            title
            and looks_like_heading(line)
            and _title_like(title)
            and title.split()[-1].lower() not in _UNFINISHED
            and starts_block
            and not following[:1].islower()
        )
        if _BULLET.match(line):
            parts.append(f"\n\n{_BULLET.sub('', line)}\n")
        elif after_heading:
            parts.append(f"\n\n{line}\n\n")
        else:
            parts.append(f"{line}\n")
    return "".join(parts).strip()


@register(".pdf")
def load_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # optional: only PDFs need it
        from pypdf.errors import DependencyError
    except ImportError:
        raise ValueError("Reading PDFs needs the 'pypdf' package. Install it with: pip install 'pypdf[crypto]'") from None

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # problems are reported below, in plain words

    def page_text(page):
        try:
            return page.extract_text() or ""
        except DependencyError:
            raise
        except Exception:  # one damaged page shouldn't lose the rest; it's reported as unreadable
            return ""

    try:
        reader = PdfReader(path)
        locked = reader.is_encrypted and not reader.decrypt("")
        pages = [] if locked else _strip_page_edges([_page_lines(page_text(page)) for page in reader.pages])
    except DependencyError:
        raise ValueError(
            f"{path.name} is encrypted in a way that needs another package. "
            "Install it with: pip install 'pypdf[crypto]'"
        ) from None
    except Exception:  # damaged files fail in many different ways inside the parser
        raise ValueError(f"{path.name} isn't a readable PDF.") from None

    if locked:
        raise ValueError(f"{path.name} is password-protected. Remove the password and try again.")
    blank = sum(not lines for lines in pages)
    if blank == len(pages):
        raise ValueError(f"{path.name} has no readable text. It may be scanned images, which DockBrain can't read.")
    if blank:
        print(
            f"Note: {blank} of {len(pages)} pages in {path.name} had no readable text and were skipped. "
            "They may be images.",
            file=sys.stderr,
        )
    return _join_pdf_lines([line for lines in pages for line in lines])


def load_document(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    loader = LOADERS.get(p.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported file type '{p.suffix}'. Supported: {sorted(LOADERS)}")
    return loader(p)
