import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { ArrowUp, RotateCw, X } from 'lucide-react';
import { AnswerText, SourcesList } from '../../components/evidence';
import { ORIGIN_LABELS, OriginBadge } from '../../components/ui';
import { errorMessage } from '../../lib/useAsyncResource';
import { makeId, plural } from '../../lib/format';
import { useService } from '../../services/ServiceContext';
import type { Answer } from '../../services/types';
import type { Say } from './WorkspaceScreen';

const MAX_QUESTION = 1000;

type Turn =
  | { id: string; question: string; status: 'pending' }
  | { id: string; question: string; status: 'error'; message: string }
  | { id: string; question: string; status: 'done'; answer: Answer };

/** One line explaining where the answer came from and how much was searched. */
export function coverageText(answer: Answer): string {
  const cov = answer.coverage;
  const whole = cov && cov.searched >= cov.total;
  const scope = !cov ? 'the sections searched' : whole ? `all ${plural(cov.total, 'section')}` : `${cov.searched} of ${plural(cov.total, 'section')}`;
  const cited = plural(answer.citations.length, 'cited excerpt');
  switch (answer.origin) {
    case 'document':
      return `Supported by ${cited} · searched ${scope}.`;
    case 'mixed':
      return `Partly supported by ${cited}; the marked part is general knowledge · searched ${scope}.`;
    case 'general':
      return cov && !whole
        ? `Not found in the ${cov.searched} of ${cov.total} sections searched, so this is general knowledge. The rest of the document wasn’t checked.`
        : 'Not found in the document, so this is general knowledge. Check it against a reliable source.';
    case 'insufficient':
      return cov && !whole
        ? `Searched ${cov.searched} of ${plural(cov.total, 'section')} without enough evidence. Try different wording.`
        : 'No passage gave enough evidence. The document may use different wording.';
  }
}

const ROBOT_REACTIONS: Record<Answer['origin'], { pose: 'success' | 'idle'; text: string }> = {
  document: { pose: 'success', text: 'Found it in the document. The sources are right below the answer.' },
  mixed: { pose: 'idle', text: 'Part of that came from the document, and part from general knowledge.' },
  general: { pose: 'idle', text: 'That wasn’t in the document, so I answered from general knowledge.' },
  insufficient: { pose: 'idle', text: 'I couldn’t find enough evidence for that one. Try rewording it.' },
};

export function AskView({
  active,
  sessionId,
  documentName,
  suggestions,
  say,
  onProgress,
}: {
  active: boolean;
  sessionId: string;
  documentName: string;
  suggestions: string[];
  say: Say;
  onProgress: () => void;
}) {
  const service = useService();
  const inputId = useId();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  const controllers = useRef(new Map<string, AbortController>());
  const listRef = useRef<HTMLOListElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const pending = turns.some((t) => t.status === 'pending');
  const last = turns[turns.length - 1];

  useEffect(() => {
    const map = controllers.current;
    return () => map.forEach((c) => c.abort());
  }, []);

  // Keep the robot's words in step with the latest turn whenever this view is showing.
  useEffect(() => {
    if (!active) return;
    if (!last) say('point', 'Ask me anything about it. I’ll show you where each answer comes from.');
    else if (last.status === 'pending') say('think', 'Thinking…');
    else if (last.status === 'error') say('idle', 'I couldn’t get an answer. You can try again.');
    else {
      const reaction = ROBOT_REACTIONS[last.answer.origin];
      say(reaction.pose, reaction.text);
    }
  }, [active, last, say]);

  const scrollToTurn = (id: string) => {
    requestAnimationFrame(() => {
      const el = listRef.current?.querySelector(`[data-turn="${id}"]`);
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      el?.scrollIntoView?.({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
    });
  };

  const run = async (id: string, question: string) => {
    const controller = new AbortController();
    controllers.current.set(id, controller);
    try {
      const answer = await service.ask(sessionId, question, { signal: controller.signal });
      setTurns((prev) => prev.map((t) => (t.id === id ? { id, question, status: 'done', answer } : t)));
    } catch (error) {
      if (controller.signal.aborted) return;
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id ? { id, question, status: 'error', message: errorMessage(error, 'The answer service didn’t respond.') } : t,
        ),
      );
    } finally {
      controllers.current.delete(id);
    }
    scrollToTurn(id);
  };

  const ask = (text: string) => {
    const question = text.trim();
    if (!question) {
      setInputError('Type a question first.');
      inputRef.current?.focus();
      return;
    }
    if (pending) return;
    const id = makeId('turn');
    setTurns((prev) => [...prev, { id, question, status: 'pending' }]);
    setDraft('');
    setInputError(null);
    onProgress();
    scrollToTurn(id);
    void run(id, question);
  };

  const retry = (turn: Turn) => {
    setTurns((prev) => prev.map((t) => (t.id === turn.id ? { id: t.id, question: t.question, status: 'pending' } : t)));
    void run(turn.id, turn.question);
  };

  const cancel = (id: string) => {
    controllers.current.get(id)?.abort();
    setTurns((prev) => prev.filter((t) => t.id !== id));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    ask(draft);
  };

  return (
    <div className="ask">
      {turns.length === 0 ? (
        <div className="ask__empty">
          <h2 className="ask__empty-title">Ask about “{documentName}”</h2>
          <p className="muted">
            Answers show whether they came from the document or from general knowledge, with the passages they rely on.
          </p>
          {suggestions.length > 0 && (
            <div className="suggestions">
              <p className="eyebrow">Try one of these</p>
              <ul className="suggestions__list">
                {suggestions.map((s) => (
                  <li key={s}>
                    <button type="button" className="suggestion" onClick={() => ask(s)}>
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <ol className="turns" ref={listRef} aria-live="polite" aria-label="Questions and answers">
          {turns.map((turn) => (
            <li key={turn.id} className="turn" data-turn={turn.id}>
              <p className="turn__question">
                <span className="visually-hidden">You asked: </span>
                {turn.question}
              </p>
              {turn.status === 'pending' && (
                <div className="answer answer--pending" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <span>Looking through the document…</span>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => cancel(turn.id)}>
                    <X aria-hidden="true" />
                    Cancel
                  </button>
                </div>
              )}
              {turn.status === 'error' && (
                <div className="answer answer--error" role="alert">
                  <p className="answer__error-title">Couldn’t get an answer</p>
                  <p className="muted small">{turn.message}</p>
                  <button type="button" className="btn btn--secondary btn--sm" onClick={() => retry(turn)} disabled={pending}>
                    <RotateCw aria-hidden="true" />
                    Try again
                  </button>
                </div>
              )}
              {turn.status === 'done' && <AnswerCard answer={turn.answer} />}
            </li>
          ))}
        </ol>
      )}

      <form className="composer" onSubmit={submit} noValidate>
        <label htmlFor={inputId} className="composer__label">
          Your question
        </label>
        <div className="composer__box" data-invalid={Boolean(inputError)}>
          <textarea
            ref={inputRef}
            id={inputId}
            className="composer__input"
            rows={2}
            maxLength={MAX_QUESTION}
            value={draft}
            placeholder="e.g. What is the main finding?"
            aria-describedby={`${inputId}-hint${inputError ? ` ${inputId}-error` : ''}`}
            aria-invalid={Boolean(inputError)}
            onChange={(event) => {
              setDraft(event.target.value);
              if (inputError && event.target.value.trim()) setInputError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                ask(draft);
              }
            }}
          />
          <button type="submit" className="btn btn--primary composer__send" disabled={pending}>
            {pending ? <span className="spinner spinner--light" aria-hidden="true" /> : <ArrowUp aria-hidden="true" />}
            {pending ? 'Answering…' : 'Ask'}
          </button>
        </div>
        <div className="composer__meta">
          <p id={`${inputId}-hint`}>Enter to ask · Shift+Enter for a new line</p>
          {draft.length > MAX_QUESTION * 0.8 && (
            <p>
              {draft.length} / {MAX_QUESTION}
            </p>
          )}
        </div>
        {inputError && (
          <p id={`${inputId}-error`} className="composer__error" role="alert">
            {inputError}
          </p>
        )}
      </form>
    </div>
  );
}

function AnswerCard({ answer }: { answer: Answer }) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState<{ index: number; nonce: number } | null>(null);
  const reveal = (index: number) => {
    setOpen(true);
    setHighlight({ index, nonce: Date.now() });
  };
  return (
    <article className="answer" aria-label={`Answer, ${ORIGIN_LABELS[answer.origin].toLowerCase()}`}>
      <div className="answer__head">
        <OriginBadge origin={answer.origin} />
        {answer.demo && <span className="answer__demo">Sample answer</span>}
      </div>
      <p className="answer__text">
        <AnswerText text={answer.text} citations={answer.citations} onCite={reveal} markOutside={answer.origin === 'mixed'} />
      </p>
      <p className="answer__coverage">{coverageText(answer)}</p>
      <SourcesList
        citations={answer.citations}
        idPrefix={answer.id}
        open={open}
        onToggle={() => setOpen((o) => !o)}
        highlight={highlight}
      />
    </article>
  );
}
