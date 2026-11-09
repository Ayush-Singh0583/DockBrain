import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, Folder, RotateCcw, Sparkles } from 'lucide-react';
import { RobotMascot } from '../components/robot/RobotMascot';
import type { RobotPose } from '../components/robot/types';
import { ErrorState, Notice, Skeleton, SpeechBubble } from '../components/ui';
import { LanguageBar } from '../components/LanguageBar';
import { StartOverButton } from '../components/StartOverButton';
import { citationLocation } from '../components/evidence';
import { useScreenHeading, type ScreenProps } from '../app/navigation';
import { useService } from '../services/ServiceContext';
import type { CodebaseOverview, OverviewAnswer, SourceSession } from '../services/types';
import type { CodebaseSelection } from '../lib/folderSelection';
import { useAsyncResource } from '../lib/useAsyncResource';
import { formatBytes, plural } from '../lib/format';
import './codebase.css';

const SHORT_LABELS: Record<OverviewAnswer['id'], string> = {
  about: 'What it is',
  why: 'Why it exists',
  problem: 'The problem',
  how: 'How it works',
};

export function CodebaseScreen({
  dispatch,
  session,
  selection,
}: ScreenProps & { session: SourceSession; selection: CodebaseSelection }) {
  const service = useService();
  const heading = useScreenHeading<HTMLHeadingElement>();
  const load = useCallback((signal: AbortSignal) => service.getCodebaseOverview(session.id, { signal }), [service, session.id]);
  const overview = useAsyncResource(load, true, 'The overview couldn’t be loaded.');

  const [pointing, setPointing] = useState(true);
  useEffect(() => {
    if (!pointing) return;
    const timer = setTimeout(() => setPointing(false), 1800);
    return () => clearTimeout(timer);
  }, [pointing]);

  // A live session can still return a sample overview; label it without saying the folder went unread.
  const sample = session.demo || (overview.status === 'success' && overview.data.demo);
  const pose: RobotPose = overview.status === 'loading' || overview.status === 'idle' ? 'think' : pointing ? 'point' : 'idle';
  const message =
    overview.status === 'success'
      ? sample
        ? 'Here’s a sample overview. Slide through the four questions.'
        : 'Here’s what I found. Slide through the four questions.'
      : overview.status === 'error'
        ? 'I couldn’t put the overview together.'
        : 'Reading the project…';

  return (
    <section className="codebase" aria-labelledby="codebase-title">
      {/* The stage: the robot and the folder on the band, with the overview rising over its edge. */}
      <div className="band band--host">
        <div className="band__inner band-row">
          <div className="host">
            <RobotMascot pose={pose} facing="right" crop="bust" size="sm" />
            <SpeechBubble tail="left" live className="host__bubble">
              <p key={message} className="bubble__text bubble__text--sm bubble__swap">
                {message}
              </p>
            </SpeechBubble>
          </div>
          <div className="source-bar">
            <div className="source-bar__file">
              <span className="source-bar__icon" aria-hidden="true">
                <Folder />
              </span>
              <div className="source-bar__text">
                <h1 id="codebase-title" className="source-bar__name" ref={heading} tabIndex={-1} title={selection.name}>
                  {selection.name}
                </h1>
                <p className="source-bar__meta">
                  {plural(selection.files.length, 'file')} · {formatBytes(selection.totalBytes)}
                  {session.demo && ' · not analysed (demo)'}
                </p>
              </div>
            </div>
            <div className="source-bar__actions">
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => dispatch({ type: 'back' })}>
                <ArrowLeft aria-hidden="true" />
                Change folder
              </button>
              <StartOverButton hasProgress={false} subject={selection.name} onConfirm={() => dispatch({ type: 'startOver' })} icon={<RotateCcw aria-hidden="true" />} />
            </div>
          </div>
        </div>
      </div>

      <div className="stage codebase__layout">
        <aside className="codebase__side">
          <FolderFacts selection={selection} />
        </aside>
        <div className="panel codebase__main">
          {sample && (
            <Notice tone="demo" title="Sample overview">
              {session.demo ? (
                <>
                  It describes the DockBrain project itself and was written by hand. “{selection.name}” wasn’t read or
                  analysed.
                </>
              ) : (
                <>It describes the DockBrain project itself and was written by hand. It’s not an analysis of “{selection.name}”.</>
              )}
            </Notice>
          )}
          {overview.status === 'success' ? (
            <OverviewDeck overview={overview.data} onChange={() => setPointing(true)} />
          ) : overview.status === 'error' ? (
            <ErrorState title="Overview isn’t available" message={overview.message} onRetry={overview.reload} />
          ) : (
            <div className="deck__card deck__card--static">
              <Skeleton lines={5} label="Loading the codebase overview" />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function OverviewDeck({ overview, onChange }: { overview: CodebaseOverview; onChange: () => void }) {
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState<1 | -1>(1);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const swipeStart = useRef<number | null>(null);
  const answers = overview.answers;
  const total = answers.length;
  const current = answers[index]!;

  const go = (next: number, focusTab = false) => {
    const clamped = Math.max(0, Math.min(total - 1, next));
    if (clamped === index) return;
    setDirection(clamped > index ? 1 : -1);
    setIndex(clamped);
    onChange();
    if (focusTab) tabRefs.current[clamped]?.focus();
  };

  const onTabKey = (event: KeyboardEvent) => {
    const target =
      event.key === 'ArrowRight' ? index + 1
      : event.key === 'ArrowLeft' ? index - 1
      : event.key === 'Home' ? 0
      : event.key === 'End' ? total - 1
      : null;
    if (target === null) return;
    event.preventDefault();
    go(target, true);
  };

  const onPointerDown = (event: PointerEvent) => {
    if (event.pointerType === 'touch') swipeStart.current = event.clientX;
  };
  const onPointerUp = (event: PointerEvent) => {
    if (swipeStart.current === null) return;
    const dx = event.clientX - swipeStart.current;
    swipeStart.current = null;
    if (Math.abs(dx) > 50) go(index + (dx < 0 ? 1 : -1));
  };

  return (
    <div className="codebase__content">
      <div className="deck" role="region" aria-roledescription="carousel" aria-label="Four questions about this codebase">
        <div className="deck__tabs" role="tablist" aria-label="Questions">
          {answers.map((answer, i) => (
            <button
              key={answer.id}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`deck-tab-${answer.id}`}
              aria-selected={i === index}
              aria-controls="deck-card"
              tabIndex={i === index ? 0 : -1}
              className="deck__tab"
              onClick={() => go(i)}
              onKeyDown={onTabKey}
            >
              <span className="deck__tab-number" aria-hidden="true">
                {i + 1}
              </span>
              {SHORT_LABELS[answer.id]}
            </button>
          ))}
        </div>

        <div className="deck__stack" onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerCancel={() => (swipeStart.current = null)}>
          <div className="deck__layer deck__layer--2" aria-hidden="true" />
          <div className="deck__layer deck__layer--1" aria-hidden="true" />
          <article
            key={current.id}
            id="deck-card"
            className="deck__card"
            data-direction={direction}
            role="tabpanel"
            aria-labelledby={`deck-tab-${current.id}`}
            aria-roledescription="slide"
          >
            <p className="eyebrow">
              Question {index + 1} of {total}
            </p>
            <h2 className="deck__question">{current.question}</h2>
            <p className="deck__summary">{current.summary}</p>
            {current.details.length > 0 && (
              <ul className="deck__details">
                {current.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            )}
            {current.evidence.length > 0 && (
              <div className="deck__evidence">
                <p className="eyebrow">Where to look</p>
                <ul>
                  {current.evidence.map((ev) => (
                    <li key={ev.index}>
                      {ev.path && <code>{citationLocation({ ...ev, section: undefined, page: undefined })}</code>}
                      <span className="muted">{ev.excerpt}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        </div>

        <div className="deck__controls">
          <button type="button" className="btn btn--secondary btn--sm" onClick={() => go(index - 1)} disabled={index === 0}>
            <ChevronLeft aria-hidden="true" />
            Previous
          </button>
          <span className="deck__count" aria-hidden="true">
            {index + 1} / {total}
          </span>
          <button type="button" className="btn btn--primary btn--sm" onClick={() => go(index + 1)} disabled={index === total - 1}>
            Next
            <ChevronRight aria-hidden="true" />
          </button>
        </div>
      </div>

      {overview.distinctive.length > 0 && (
        <section className="distinctive" aria-labelledby="distinctive-title">
          <h2 id="distinctive-title">
            <Sparkles aria-hidden="true" />
            What makes it distinctive?
          </h2>
          <ul>
            {overview.distinctive.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function FolderFacts({ selection }: { selection: CodebaseSelection }) {
  return (
    <section className="facts" aria-labelledby="facts-title">
      <h2 id="facts-title" className="facts__title">
        Your folder
      </h2>
      <p className="facts__note">Read from file names and sizes on this device.</p>
      <dl className="facts__list">
        <div>
          <dt>Files</dt>
          <dd>{selection.files.length.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd>{formatBytes(selection.totalBytes)}</dd>
        </div>
      </dl>
      {selection.languages.length > 0 ? (
        <LanguageBar languages={selection.languages} limit={3} />
      ) : (
        <p className="facts__note">No source files with a recognised language.</p>
      )}
      {selection.ignoredCount > 0 && (
        <p className="facts__note">Left out {plural(selection.ignoredCount, 'item')} in dependency or build folders.</p>
      )}
    </section>
  );
}
