export type AnswerSegment = { type: 'text'; value: string } | { type: 'cite'; index: number };

/**
 * Text ready to render: each run of citation numbers travels with the word before it
 * and the punctuation after it (rendered without line breaks), so a chip never starts a
 * line on its own.
 */
export type CitedPiece =
  | { type: 'text'; value: string }
  | { type: 'glued'; before: string; cites: number[]; after: string };

const MARKER = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

/**
 * Splits answer text into plain text and citation markers. "[2]" and "[1, 3]" become
 * citations only when every number refers to a known excerpt; anything else stays text.
 */
export function splitCitations(text: string, validIndices: ReadonlySet<number>): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const numbers = match[1]!.split(',').map((n) => Number(n.trim()));
    if (!numbers.every((n) => validIndices.has(n))) continue;
    const start = match.index ?? 0;
    // Drop the space before a marker so "planet [1]." renders as "planet¹."
    const before = text.slice(last, start).replace(/\s+$/, '');
    if (before) segments.push({ type: 'text', value: before });
    for (const index of numbers) segments.push({ type: 'cite', index });
    last = start + match[0].length;
  }
  const rest = text.slice(last);
  if (rest) segments.push({ type: 'text', value: rest });
  return segments;
}

/** Groups each run of citations with its neighbouring word and punctuation. */
export function attachCitations(segments: AnswerSegment[]): CitedPiece[] {
  const pieces: CitedPiece[] = [];
  let pendingText: string | null = null; // text following a chip, minus what was glued to it

  const flushText = () => {
    if (pendingText) pieces.push({ type: 'text', value: pendingText });
    pendingText = null;
  };

  for (let i = 0; i < segments.length; i += 1) {
    const segment = segments[i]!;
    if (segment.type === 'text') {
      pendingText = (pendingText ?? '') + segment.value;
      continue;
    }

    const cites = [segment.index];
    while (segments[i + 1]?.type === 'cite') cites.push((segments[++i] as { index: number }).index);

    let before = '';
    if (pendingText) {
      const word = /\S+$/.exec(pendingText);
      if (word) {
        before = word[0];
        pendingText = pendingText.slice(0, word.index);
      }
    }
    flushText();

    let after = '';
    const next = segments[i + 1];
    if (next?.type === 'text') {
      after = /^\S*/.exec(next.value)![0];
      pendingText = next.value.slice(after.length);
      i += 1;
    }
    pieces.push({ type: 'glued', before, cites, after });
  }
  flushText();
  return pieces;
}
