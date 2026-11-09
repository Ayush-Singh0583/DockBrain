import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, BookOpen, Check, RotateCcw, X } from 'lucide-react';
import { SourcesList } from '../../components/evidence';
import { ErrorState, Skeleton } from '../../components/ui';
import type { Resource } from '../../lib/useAsyncResource';
import { useStillWorking } from '../../lib/useStillWorking';
import type { Quiz, QuizQuestion } from '../../services/types';
import type { WorkspaceTab } from '../../app/state';
import type { Say } from './WorkspaceScreen';

const LETTERS = 'ABCDEFGH';

interface Progress {
  index: number;
  /** Option chosen for the current question, before checking. */
  selected: string | null;
  checked: boolean;
  /** Checked answers by question id. */
  answers: Record<string, string>;
  finished: boolean;
}

const START: Progress = { index: 0, selected: null, checked: false, answers: {}, finished: false };

export function QuizView({
  active,
  quiz,
  say,
  available,
  onProgress,
  onNavigate,
  onChangeDocument,
}: {
  active: boolean;
  quiz: Resource<Quiz> & { reload: () => void };
  say: Say;
  /** Views this server offers; links to others are left out. */
  available: WorkspaceTab[];
  onProgress: () => void;
  onNavigate: (tab: WorkspaceTab) => void;
  onChangeDocument: () => void;
}) {
  const canReadNotes = available.includes('notes');
  // No retry here: the same document would give the same result.
  const insufficient =
    (quiz.status === 'error' && quiz.code === 'insufficient_content') ||
    (quiz.status === 'success' && quiz.data.questions.length === 0);

  useEffect(() => {
    if (!active) return;
    if (quiz.status === 'loading' || quiz.status === 'idle') say('think', 'Writing some questions for you…');
    else if (insufficient) say('idle', 'There isn’t much here I can ask about.');
    else if (quiz.status === 'error') say('idle', 'I couldn’t put the quiz together. Let’s try again.');
  }, [active, quiz.status, insufficient, say]);

  useStillWorking(active && (quiz.status === 'idle' || quiz.status === 'loading'), say);

  if (quiz.status === 'idle' || quiz.status === 'loading') return <Skeleton lines={5} label="Preparing the quiz" />;
  if (insufficient) {
    return (
      <div className="state">
        <p className="state__title">Not enough here to write a quiz</p>
        <p className="muted">{quiz.status === 'error' ? quiz.message : 'There wasn’t enough material to write a quiz.'}</p>
        <div className="state__actions">
          <button type="button" className="btn btn--primary btn--sm" onClick={onChangeDocument}>
            Choose another document
          </button>
          {canReadNotes && (
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => onNavigate('notes')}>
              Read the notes
            </button>
          )}
        </div>
      </div>
    );
  }
  if (quiz.status === 'error') return <ErrorState title="Quiz isn’t available" message={quiz.message} onRetry={quiz.reload} />;
  return (
    <QuizRunner
      quiz={quiz.data}
      active={active}
      say={say}
      onProgress={onProgress}
      onReviewNotes={canReadNotes ? () => onNavigate('notes') : undefined}
    />
  );
}

function QuizRunner({
  quiz,
  active,
  say,
  onProgress,
  onReviewNotes,
}: {
  quiz: Quiz;
  active: boolean;
  say: Say;
  onProgress: () => void;
  /** Absent when the server offers no notes. */
  onReviewNotes?: () => void;
}) {
  const [progress, setProgress] = useState<Progress>(START);
  const [needsChoice, setNeedsChoice] = useState(false);
  const feedbackRef = useRef<HTMLDivElement>(null);
  const promptRef = useRef<HTMLLegendElement>(null);
  const resultsRef = useRef<HTMLHeadingElement>(null);
  const formId = useId();

  const total = quiz.questions.length;
  const question = quiz.questions[progress.index]!;
  const score = quiz.questions.filter((q) => progress.answers[q.id] === q.correctOptionId).length;

  useEffect(() => {
    if (!active) return;
    if (progress.finished) {
      if (score / total >= 0.8) say('success', `You got ${score} of ${total}. Great work!`);
      else say('idle', `You got ${score} of ${total}. The explanations show where each answer comes from.`);
    } else if (progress.checked) {
      if (progress.answers[question.id] === question.correctOptionId) say('success', 'That’s right!');
      else say('idle', 'Not quite. The explanation is just below.');
    } else {
      say('point', progress.index === 0 ? 'Pick an answer, then check it.' : 'Here’s the next one.');
    }
    // `say` is stable; score/total change only with progress.
  }, [active, progress, question, score, total, say]);

  const check = (event: FormEvent) => {
    event.preventDefault();
    if (!progress.selected) {
      setNeedsChoice(true);
      return;
    }
    setNeedsChoice(false);
    onProgress();
    setProgress((p) => ({ ...p, checked: true, answers: { ...p.answers, [question.id]: p.selected! } }));
    requestAnimationFrame(() => feedbackRef.current?.focus());
  };

  const next = () => {
    if (progress.index + 1 >= total) {
      setProgress((p) => ({ ...p, finished: true }));
      requestAnimationFrame(() => resultsRef.current?.focus());
      return;
    }
    setProgress((p) => ({ ...p, index: p.index + 1, selected: null, checked: false }));
    requestAnimationFrame(() => promptRef.current?.focus());
  };

  const retry = () => {
    setProgress(START);
    setNeedsChoice(false);
    requestAnimationFrame(() => promptRef.current?.focus());
  };

  if (progress.finished) {
    return (
      <div className="quiz-results">
        <div className="quiz-results__score">
          <p className="eyebrow">Quiz complete</p>
          <h2 ref={resultsRef} tabIndex={-1}>
            You got {score} of {total} right
          </h2>
          <p className="muted">
            {score === total
              ? 'A perfect score.'
              : score / total >= 0.6
                ? 'Solid work. Review the ones you missed below.'
                : 'Reviewing the notes, then trying again, usually helps.'}
          </p>
        </div>
        <ol className="review">
          {quiz.questions.map((q) => (
            <ReviewItem key={q.id} question={q} chosen={progress.answers[q.id]} />
          ))}
        </ol>
        <div className="quiz-results__actions">
          <button type="button" className="btn btn--primary" onClick={retry}>
            <RotateCcw aria-hidden="true" />
            Retry quiz
          </button>
          {onReviewNotes && (
            <button type="button" className="btn btn--secondary" onClick={onReviewNotes}>
              <BookOpen aria-hidden="true" />
              Review the notes
            </button>
          )}
        </div>
      </div>
    );
  }

  const chosen = progress.answers[question.id];
  const correct = progress.checked && chosen === question.correctOptionId;
  const isLast = progress.index + 1 >= total;

  return (
    <div className="quiz">
      <div className="quiz__progress">
        <span className="quiz__count">
          Question {progress.index + 1} of {total}
        </span>
        <div
          className="progress"
          role="progressbar"
          aria-label="Quiz progress"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={progress.index + (progress.checked ? 1 : 0)}
        >
          <span style={{ transform: `scaleX(${(progress.index + (progress.checked ? 1 : 0)) / total})` }} />
        </div>
      </div>

      <form id={formId} onSubmit={check} noValidate>
        <fieldset className="quiz__question" key={question.id}>
          <legend ref={promptRef} tabIndex={-1} className="quiz__prompt">
            {question.prompt}
          </legend>
          <div className="options">
            {question.options.map((option, i) => {
              const state = !progress.checked
                ? 'open'
                : option.id === question.correctOptionId
                  ? 'correct'
                  : option.id === chosen
                    ? 'incorrect'
                    : 'muted';
              return (
                <label key={option.id} className="option" data-state={state}>
                  <input
                    type="radio"
                    name={`q-${question.id}`}
                    value={option.id}
                    checked={(progress.checked ? chosen : progress.selected) === option.id}
                    disabled={progress.checked}
                    onChange={() => {
                      setProgress((p) => ({ ...p, selected: option.id }));
                      setNeedsChoice(false);
                    }}
                  />
                  <span className="option__letter" aria-hidden="true">
                    {LETTERS[i]}
                  </span>
                  <span className="option__text">{option.text}</span>
                  {state === 'correct' && (
                    <span className="option__mark">
                      <Check aria-hidden="true" />
                      <span className="visually-hidden">(correct answer)</span>
                    </span>
                  )}
                  {state === 'incorrect' && (
                    <span className="option__mark">
                      <X aria-hidden="true" />
                      <span className="visually-hidden">(your answer, incorrect)</span>
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>

        {needsChoice && (
          <p className="quiz__hint" role="alert">
            Choose an answer first.
          </p>
        )}

        {progress.checked && (
          <div
            ref={feedbackRef}
            tabIndex={-1}
            className="feedback"
            data-correct={correct}
          >
            <p className="feedback__title">{correct ? 'Correct!' : 'Not quite.'}</p>
            {!correct && (
              <p className="feedback__answer">
                The answer is <strong>{question.options.find((o) => o.id === question.correctOptionId)?.text}</strong>.
              </p>
            )}
            <p>{question.explanation}</p>
            {question.citation && <QuestionSource question={question} />}
          </div>
        )}

        <div className="quiz__actions">
          {progress.checked ? (
            <button type="button" className="btn btn--primary" onClick={next}>
              {isLast ? 'See results' : 'Next question'}
              <ArrowRight aria-hidden="true" />
            </button>
          ) : (
            <button type="submit" className="btn btn--primary">
              Check answer
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

function QuestionSource({ question }: { question: QuizQuestion }) {
  const [open, setOpen] = useState(false);
  if (!question.citation) return null;
  return (
    <SourcesList
      citations={[{ ...question.citation, index: 1 }]}
      idPrefix={`quiz-${question.id}`}
      open={open}
      onToggle={() => setOpen((o) => !o)}
      highlight={null}
      label="Source"
    />
  );
}

function ReviewItem({ question, chosen }: { question: QuizQuestion; chosen?: string }) {
  const right = chosen === question.correctOptionId;
  const text = (id?: string) => question.options.find((o) => o.id === id)?.text ?? '—';
  return (
    <li className="review__item" data-correct={right}>
      <span className="review__mark" aria-hidden="true">
        {right ? <Check /> : <X />}
      </span>
      <div>
        <p className="review__prompt">
          <span className="visually-hidden">{right ? 'Correct: ' : 'Incorrect: '}</span>
          {question.prompt}
        </p>
        <p className="small muted">
          {right ? `Your answer: ${text(chosen)}` : `Your answer: ${text(chosen)} · Correct: ${text(question.correctOptionId)}`}
        </p>
      </div>
    </li>
  );
}
