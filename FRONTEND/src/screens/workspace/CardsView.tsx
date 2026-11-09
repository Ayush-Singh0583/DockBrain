import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, Check, CircleHelp, Eye, Layers, RotateCcw, Shuffle, Undo2 } from 'lucide-react';
import { SourcesList } from '../../components/evidence';
import { ErrorState, Notice, Skeleton } from '../../components/ui';
import type { Resource } from '../../lib/useAsyncResource';
import { useStillWorking } from '../../lib/useStillWorking';
import { useService } from '../../services/ServiceContext';
import { ServiceError, type CardAnswer, type CardKind, type CardSet, type MemoryCard } from '../../services/types';
import type { WorkspaceTab } from '../../app/state';
import type { Say } from './WorkspaceScreen';
import './cards.css';

const KIND_LABELS: Record<CardKind, string> = {
  definition: 'Definition',
  cloze: 'Fill in the blank',
  question: 'Question',
};

type Mark = 'know' | 'review';
type Back = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: CardAnswer };
type LastAction = 'start' | 'move' | 'reveal' | 'know' | 'review' | 'shuffle' | 'again';

interface Round {
  /** Card ids in the order this round shows them. */
  deck: string[];
  index: number;
  revealed: boolean;
  /** This round's marks. */
  marks: Record<string, Mark>;
  finished: boolean;
  last: LastAction;
}

function startRound(deck: string[], last: LastAction): Round {
  return { deck, index: 0, revealed: false, marks: {}, finished: false, last };
}

/** A Fisher–Yates shuffle that never returns the same order when another is possible. */
export function shuffled<T>(items: readonly T[], random: () => number = Math.random): T[] {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [result[i], result[j]] = [result[j]!, result[i]!];
  }
  if (result.length > 1 && result.every((item, i) => item === items[i])) result.push(result.shift()!);
  return result;
}

export function CardsView({
  active,
  cards,
  sessionId,
  say,
  available,
  onProgress,
  onNavigate,
  onChangeDocument,
}: {
  active: boolean;
  cards: Resource<CardSet> & { reload: () => void };
  sessionId: string;
  say: Say;
  /** Views this server offers; links to others are left out. */
  available: WorkspaceTab[];
  onProgress: () => void;
  onNavigate: (tab: WorkspaceTab) => void;
  onChangeDocument: () => void;
}) {
  const insufficient =
    (cards.status === 'error' && cards.code === 'insufficient_content') ||
    (cards.status === 'success' && cards.data.cards.length === 0);

  useEffect(() => {
    if (!active) return;
    if (cards.status === 'loading' || cards.status === 'idle') say('think', 'Making some cards for you…');
    else if (insufficient) say('idle', 'There isn’t much here I can turn into cards.');
    else if (cards.status === 'error') say('idle', 'I couldn’t make the cards. Let’s try again.');
  }, [active, cards.status, insufficient, say]);

  useStillWorking(active && (cards.status === 'idle' || cards.status === 'loading'), say);

  if (cards.status === 'idle' || cards.status === 'loading') return <Skeleton lines={4} label="Making memory cards" />;
  if (insufficient) {
    return (
      <div className="state cards-empty">
        <span className="cards-empty__icon" aria-hidden="true">
          <Layers />
        </span>
        <p className="state__title">Not enough here to make cards</p>
        <p className="muted">
          {cards.status === 'error'
            ? cards.message
            : 'This document doesn’t have enough plain statements to make memory cards from.'}
        </p>
        <div className="state__actions">
          <button type="button" className="btn btn--primary btn--sm" onClick={onChangeDocument}>
            Choose another document
          </button>
          {available.includes('notes') && (
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => onNavigate('notes')}>
              Read the notes
            </button>
          )}
        </div>
      </div>
    );
  }
  if (cards.status === 'error') {
    return <ErrorState title="Memory cards aren’t available" message={cards.message} onRetry={cards.reload} />;
  }
  return (
    <CardsRunner
      key={cards.data.id}
      set={cards.data}
      sessionId={sessionId}
      active={active}
      say={say}
      onProgress={onProgress}
      onReviewNotes={available.includes('notes') ? () => onNavigate('notes') : undefined}
    />
  );
}

function CardsRunner({
  set,
  sessionId,
  active,
  say,
  onProgress,
  onReviewNotes,
}: {
  set: CardSet;
  sessionId: string;
  active: boolean;
  say: Say;
  onProgress: () => void;
  onReviewNotes?: () => void;
}) {
  const service = useService();
  const byId = new Map(set.cards.map((c) => [c.id, c]));
  const [round, setRound] = useState<Round>(() => startRound(set.cards.map((c) => c.id), 'start'));
  const [backs, setBacks] = useState<Record<string, Back>>({});
  const requests = useRef(new Map<string, AbortController>());
  const flipRef = useRef<HTMLButtonElement>(null);
  const summaryRef = useRef<HTMLHeadingElement>(null);

  // Cancel any answer still being fetched when the set goes away.
  useEffect(() => {
    const pending = requests.current;
    return () => pending.forEach((controller) => controller.abort());
  }, []);

  const total = round.deck.length;
  const card = byId.get(round.deck[round.index]!)!;
  const back = backs[card.id];
  // Marking needs the answer to have been seen, so a failed or slow reveal can't be marked.
  const answered = round.revealed && back?.status === 'ready';
  const known = round.deck.filter((id) => round.marks[id] === 'know').length;
  const toReview = round.deck.filter((id) => round.marks[id] === 'review').length;

  useEffect(() => {
    if (!active) return;
    if (round.finished) {
      if (known === total) say('success', total === 1 ? 'You knew it!' : `You knew all ${total}!`);
      else say('idle', `You know ${known} of ${total}. Let’s go over the rest.`);
      return;
    }
    const lines: Record<LastAction, [Parameters<Say>[0], string]> = {
      start: ['point', 'Think of the answer, then flip the card.'],
      again: ['point', 'Here are the ones to go over again.'],
      move: ['idle', 'Think of the answer, then flip the card.'],
      reveal: ['idle', 'Did you know it?'],
      know: ['success', 'Nice, you knew that one!'],
      review: ['idle', 'No problem. I’ll keep that one for review.'],
      shuffle: ['idle', 'Shuffled! Starting from the top.'],
    };
    say(...lines[round.last]);
  }, [active, round.finished, round.last, round.index, known, total, say]);

  const fetchBack = useCallback(
    (target: MemoryCard) => {
      requests.current.get(target.id)?.abort();
      const controller = new AbortController();
      requests.current.set(target.id, controller);
      setBacks((b) => ({ ...b, [target.id]: { status: 'loading' } }));
      service.revealCard(sessionId, set.id, target.id, { signal: controller.signal }).then(
        (data) => {
          if (controller.signal.aborted) return;
          requests.current.delete(target.id);
          setBacks((b) => ({ ...b, [target.id]: { status: 'ready', data } }));
        },
        (error: unknown) => {
          if (controller.signal.aborted) return;
          requests.current.delete(target.id);
          const message = error instanceof ServiceError ? error.message : 'The answer couldn’t be loaded.';
          setBacks((b) => ({ ...b, [target.id]: { status: 'error', message } }));
        },
      );
    },
    [service, sessionId, set.id],
  );

  const flip = () => {
    if (!round.revealed && (!back || back.status === 'error')) fetchBack(card);
    setRound((r) => ({ ...r, revealed: !r.revealed, last: r.revealed ? 'move' : 'reveal' }));
  };

  const go = (index: number) => {
    if (index < 0 || index >= total || index === round.index) return;
    setRound((r) => ({ ...r, index, revealed: false, last: 'move' }));
  };

  const mark = (value: Mark) => {
    onProgress();
    const marks = { ...round.marks, [card.id]: value };
    // The next card without a mark: later ones first, then any skipped earlier.
    const order = [...round.deck.keys()].slice(round.index + 1).concat([...round.deck.keys()].slice(0, round.index));
    const next = order.find((i) => !marks[round.deck[i]!]);
    if (next === undefined) {
      setRound((r) => ({ ...r, marks, revealed: false, finished: true, last: value }));
      requestAnimationFrame(() => summaryRef.current?.focus());
      return;
    }
    // The flip button is already on screen, and the marks that held focus are about to go.
    flipRef.current?.focus();
    setRound((r) => ({ ...r, marks, index: next, revealed: false, last: value }));
  };

  const shuffle = () => {
    setRound((r) => ({ ...startRound(shuffled(r.deck), 'shuffle'), marks: r.marks }));
    flipRef.current?.focus(); // ready to flip the new first card, rather than shuffle again
  };

  const restart = (deck: string[], last: LastAction) => {
    setRound(startRound(deck, last));
    requestAnimationFrame(() => flipRef.current?.focus());
  };

  // Shortcuts work wherever focus is on the page, so nobody has to tab into the card
  // first. Re-subscribes each render, so the handler always sees the current card.
  useEffect(() => {
    if (!active || round.finished) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      // Typing and open dialogs are left alone. The tab strip's own arrow keys are too:
      // its handler has already marked them defaultPrevented.
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], dialog')) return;
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      if (key === 'ArrowLeft') go(round.index - 1);
      else if (key === 'ArrowRight') go(round.index + 1);
      else if (event.repeat) return;
      else if (key === ' ' || key === 'Enter') {
        if (target?.closest('button, a, summary')) return; // a focused control acts for itself
        flip();
      } else if (key === 'k' && answered) mark('know');
      else if (key === 'r' && answered) mark('review');
      else return;
      event.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // A click anywhere on a card's front flips it; its own buttons act for themselves. The
  // back stays put, so reading or selecting the quote doesn't turn it over.
  const onCardClick = (event: MouseEvent<HTMLDivElement>) => {
    if (round.revealed || (event.target as HTMLElement).closest('button, a, summary, [role="button"]')) return;
    if (window.getSelection?.()?.toString()) return; // selecting the quote isn't a flip
    flip();
  };

  if (round.finished) {
    const reviewIds = round.deck.filter((id) => round.marks[id] === 'review');
    return (
      <div className="cards-summary">
        <p className="eyebrow">Round complete</p>
        <h2 ref={summaryRef} tabIndex={-1}>
          You know {known} of {total} {total === 1 ? 'card' : 'cards'}
        </h2>
        <p className="muted">
          {reviewIds.length === 0
            ? 'Every card in this round is marked “Know it”.'
            : `${reviewIds.length} ${reviewIds.length === 1 ? 'card is' : 'cards are'} marked “Review again”.`}
        </p>
        <div className="cards-summary__actions">
          {reviewIds.length > 0 && (
            <button type="button" className="btn btn--primary" onClick={() => restart(reviewIds, 'again')}>
              <Undo2 aria-hidden="true" />
              Review the {reviewIds.length} again
            </button>
          )}
          <button
            type="button"
            className={`btn ${reviewIds.length > 0 ? 'btn--secondary' : 'btn--primary'}`}
            onClick={() => restart(set.cards.map((c) => c.id), 'start')}
          >
            <RotateCcw aria-hidden="true" />
            Start over with all {set.cards.length}
          </button>
          {onReviewNotes && (
            <button type="button" className="btn btn--ghost" onClick={onReviewNotes}>
              <BookOpen aria-hidden="true" />
              Review the notes
            </button>
          )}
        </div>
      </div>
    );
  }

  const marked = known + toReview;
  const spokenPrompt = card.prompt.replace(/_{3,}/g, 'blank');
  const announcement =
    answered && back?.status === 'ready'
      ? `Answer: ${back.data.answer}`
      : `Card ${round.index + 1} of ${total}: ${spokenPrompt}`;
  const side = round.revealed ? 'back' : 'front';

  return (
    <div className="cards">
      <p className="visually-hidden cards__announce" role="status">
        {announcement}
      </p>
      {set.notice && (
        <Notice tone="info" role="status">
          {set.notice}
        </Notice>
      )}

      <div className="cards__progress">
        <span className="cards__count">
          Card {round.index + 1} of {total}
        </span>
        <div
          className="progress"
          role="progressbar"
          aria-label="Cards marked"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={marked}
          aria-valuetext={`${marked} of ${total} marked`}
        >
          <span style={{ transform: `scaleX(${marked / total})` }} />
        </div>
        <span className="cards__tally">
          {known} known · {toReview} to review
        </span>
      </div>

      <div className="memory-card" data-side={side} data-mark={round.marks[card.id]} onClick={onCardClick}>
        <div className="memory-card__face" key={`${card.id}-${side}`}>
          <p className="memory-card__eyebrow">
            <span>{round.revealed ? 'Answer' : KIND_LABELS[card.kind]}</span>
            {set.demo && <span className="memory-card__sample">Sample card</span>}
            {round.marks[card.id] && (
              <span className="memory-card__marked">
                Marked “{round.marks[card.id] === 'know' ? 'Know it' : 'Review again'}”
              </span>
            )}
          </p>
          {/* A cloze card's source sentence says the same as its front, so it replaces it. */}
          {!(answered && card.kind === 'cloze') && (
            <p className="memory-card__prompt" data-faded={round.revealed}>
              <Prompt text={card.prompt} />
            </p>
          )}
          {round.revealed && <CardBack card={card} back={back} onRetry={() => fetchBack(card)} />}
        </div>
        <button
          ref={flipRef}
          type="button"
          className={`btn ${round.revealed ? 'btn--secondary' : 'btn--primary'} memory-card__flip`}
          onClick={flip}
          aria-keyshortcuts="Space"
        >
          {round.revealed ? <CircleHelp aria-hidden="true" /> : <Eye aria-hidden="true" />}
          {round.revealed ? 'Show the question' : 'Show answer'}
        </button>
      </div>

      {answered && (
        <div className="cards__marks" role="group" aria-label="How did it go?">
          <button type="button" className="btn btn--secondary" onClick={() => mark('review')} aria-keyshortcuts="R">
            <Undo2 aria-hidden="true" />
            Review again
          </button>
          <button type="button" className="btn btn--primary" onClick={() => mark('know')} aria-keyshortcuts="K">
            <Check aria-hidden="true" />
            Know it
          </button>
        </div>
      )}

      <div className="cards__nav">
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => go(round.index - 1)}
          disabled={round.index === 0}
          aria-keyshortcuts="ArrowLeft"
        >
          <ArrowLeft aria-hidden="true" />
          Previous
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={shuffle} disabled={total < 2}>
          <Shuffle aria-hidden="true" />
          Shuffle
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => go(round.index + 1)}
          disabled={round.index + 1 >= total}
          aria-keyshortcuts="ArrowRight"
        >
          Next
          <ArrowRight aria-hidden="true" />
        </button>
      </div>

      <p className="cards__keys">
        <kbd>Space</kbd> flips the card · <kbd>←</kbd> <kbd>→</kbd> move · after flipping, <kbd>K</kbd> know it ·{' '}
        <kbd>R</kbd> review again
      </p>
    </div>
  );
}

/** A card's front, with its blank drawn as a line and read out as "blank". */
function Prompt({ text }: { text: string }) {
  // The card's label already says "Fill in the blank".
  const parts = text.replace(/^Fill in the blank:\s*/, '').split(/_{3,}/);
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < parts.length - 1 && (
            <span className="memory-card__blank">
              <span className="visually-hidden">blank</span>
            </span>
          )}
        </span>
      ))}
    </>
  );
}

/** The source sentence, with the words that answer the card picked out. */
function Quote({ text, answer }: { text: string; answer: string }) {
  const at = text.indexOf(answer);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="memory-card__filled">{answer}</mark>
      {text.slice(at + answer.length)}
    </>
  );
}

function CardBack({ card, back, onRetry }: { card: MemoryCard; back: Back | undefined; onRetry: () => void }) {
  const [open, setOpen] = useState(false);
  if (!back || back.status === 'loading') {
    return (
      <p className="memory-card__status muted" role="status">
        Turning the card over…
      </p>
    );
  }
  if (back.status === 'error') {
    return (
      <div className="memory-card__status" role="alert">
        <p className="muted">{back.message}</p>
        <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  return (
    <div className="memory-card__back">
      <p className="memory-card__answer">{back.data.answer}</p>
      <figure className="memory-card__quote">
        <blockquote>
          <Quote text={back.data.quote} answer={back.data.answer} />
        </blockquote>
        <figcaption>From the document</figcaption>
      </figure>
      <SourcesList
        citations={[{ ...back.data.citation, index: 1 }]}
        idPrefix={`card-${card.id}`}
        open={open}
        onToggle={() => setOpen((o) => !o)}
        highlight={null}
        label="Passage"
      />
    </div>
  );
}
