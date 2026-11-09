import { Fragment, useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { attachCitations, splitCitations, type AnswerSegment } from '../lib/citations';
import type { Citation } from '../services/types';
import './evidence.css';

/** "Section “Results” · Page 4" or "rag/loader.py, lines 10–24"; only fields that are supplied. */
export function citationLocation(citation: Citation): string {
  const parts: string[] = [];
  if (citation.path) {
    const lines =
      citation.lineStart !== undefined
        ? `, ${citation.lineEnd !== undefined && citation.lineEnd !== citation.lineStart ? `lines ${citation.lineStart}–${citation.lineEnd}` : `line ${citation.lineStart}`}`
        : '';
    parts.push(`${citation.path}${lines}`);
  }
  if (citation.section) parts.push(`Section “${citation.section}”`);
  if (citation.page !== undefined) parts.push(`Page ${citation.page}`);
  return parts.join(' · ');
}

export function CiteButton({ index, onClick }: { index: number; onClick: (index: number) => void }) {
  return (
    <button type="button" className="cite" onClick={() => onClick(index)} aria-label={`Show source ${index}`}>
      {index}
    </button>
  );
}

/** Text with citation chips that stay on the same line as their word and punctuation. */
export function CitedText({ segments, onCite }: { segments: AnswerSegment[]; onCite: (index: number) => void }) {
  return (
    <>
      {attachCitations(segments).map((piece, i) =>
        piece.type === 'text' ? (
          <Fragment key={i}>{piece.value}</Fragment>
        ) : (
          <span key={i} className="cite-group">
            {piece.before}
            {piece.cites.map((index) => (
              <CiteButton key={index} index={index} onClick={onCite} />
            ))}
            {piece.after}
          </span>
        ),
      )}
    </>
  );
}

/** Backend wording that introduces general-knowledge content (rag/generator.py). */
const OUTSIDE_LABEL =
  /\b(?:It|The rest) wasn['’]t in the information I was given|\bI searched \d+ of \d+ sections of the document and didn['’]t find|\bNo section of the document matched/;

/**
 * Answer text with [n] markers as source buttons. Text from the backend's
 * general-knowledge label onward is set apart, so a mixed answer shows which part
 * came from outside the document.
 */
export function AnswerText({
  text,
  citations,
  onCite,
  markOutside = true,
}: {
  text: string;
  citations: Citation[];
  onCite: (index: number) => void;
  /** Set apart the general-knowledge part; only useful when the answer is mixed. */
  markOutside?: boolean;
}) {
  const valid = new Set(citations.map((c) => c.index));
  const label = markOutside ? OUTSIDE_LABEL.exec(text) : null;
  const documentPart = label ? text.slice(0, label.index) : text;
  const outsidePart = label ? text.slice(label.index) : '';

  const render = (part: string) => <CitedText segments={splitCitations(part, valid)} onCite={onCite} />;

  return (
    <>
      {render(documentPart)}
      {outsidePart && (
        <span className="answer-outside">
          <span className="visually-hidden">General knowledge: </span>
          {render(outsidePart)}
        </span>
      )}
    </>
  );
}

/**
 * A disclosure listing numbered excerpts. `highlight` scrolls to and focuses one
 * excerpt (used when a citation number is pressed).
 */
export function SourcesList({
  citations,
  idPrefix,
  open,
  onToggle,
  highlight,
  label = 'Sources',
}: {
  citations: Citation[];
  idPrefix: string;
  open: boolean;
  onToggle: () => void;
  highlight: { index: number; nonce: number } | null;
  label?: string;
}) {
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!open || !highlight) return;
    const item = listRef.current?.querySelector<HTMLElement>(`[data-index="${highlight.index}"]`);
    if (!item) return;
    item.focus({ preventScroll: true });
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    item.scrollIntoView?.({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
  }, [open, highlight]);

  if (citations.length === 0) return null;
  const listId = `${idPrefix}-sources`;

  return (
    <div className="sources">
      <button type="button" className="sources__toggle" aria-expanded={open} aria-controls={listId} onClick={onToggle}>
        <ChevronDown aria-hidden="true" className="sources__chevron" />
        {label} ({citations.length})
      </button>
      <ol id={listId} className="sources__list" hidden={!open} ref={listRef}>
        {citations.map((citation) => {
          const location = citationLocation(citation);
          return (
            <li
              key={citation.index}
              className="source"
              data-index={citation.index}
              data-highlight={highlight?.index === citation.index}
              tabIndex={-1}
            >
              <span className="source__number" aria-label={`Source ${citation.index}`}>
                {citation.index}
              </span>
              <div className="source__body">
                {location && <p className="source__location">{location}</p>}
                <blockquote className="source__excerpt">{citation.excerpt}</blockquote>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
