import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowLeft, BookOpen, FileText, Layers, ListChecks, MessageCircleQuestion, RotateCcw } from 'lucide-react';
import { RobotMascot } from '../../components/robot/RobotMascot';
import type { RobotPose } from '../../components/robot/types';
import { ErrorState, Notice, SpeechBubble } from '../../components/ui';
import { useScreenHeading, type ScreenProps } from '../../app/navigation';
import type { WorkspaceTab } from '../../app/state';
import { useService } from '../../services/ServiceContext';
import { offers, type SourceSession } from '../../services/types';
import { useAsyncResource } from '../../lib/useAsyncResource';
import { formatBytes } from '../../lib/format';
import { NotesView } from './NotesView';
import { AskView } from './AskView';
import { QuizView } from './QuizView';
import { CardsView } from './CardsView';
import { StartOverButton } from '../../components/StartOverButton';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { SAMPLE_DOCUMENT_NAME } from '../../fixtures/sampleDocument';
import './workspace.css';

const TABS: { id: WorkspaceTab; label: string; icon: typeof BookOpen }[] = [
  { id: 'notes', label: 'Notes', icon: BookOpen },
  { id: 'ask', label: 'Ask', icon: MessageCircleQuestion },
  { id: 'quiz', label: 'Quiz', icon: ListChecks },
  { id: 'cards', label: 'Cards', icon: Layers },
];

export interface RobotLine {
  pose: RobotPose;
  text: string;
}
export type Say = (pose: RobotPose, text: string) => void;

export function WorkspaceScreen({
  state,
  dispatch,
  capabilities,
  session,
  document,
}: ScreenProps & { session: SourceSession; document: File }) {
  const service = useService();
  const heading = useScreenHeading<HTMLHeadingElement>();
  // Views the server doesn't offer get no tab and no request. If the requested tab isn't
  // offered (e.g. Notes on an ask-only server), open the first one that is.
  const tabs = TABS.filter(({ id }) => offers(capabilities, id));
  const available = tabs.map(({ id }) => id);
  const tab = available.includes(state.tab) ? state.tab : available[0];
  const [visited, setVisited] = useState<Set<WorkspaceTab>>(() => new Set());
  const opened = (id: WorkspaceTab) => id === tab || visited.has(id);
  const [robot, setRobot] = useState<RobotLine>({ pose: 'idle', text: 'Let’s take a look.' });
  const [progress, setProgress] = useState(false);
  const [confirmingChange, setConfirmingChange] = useState(false);
  const tabRefs = useRef<Record<WorkspaceTab, HTMLButtonElement | null>>({ notes: null, ask: null, quiz: null, cards: null });
  const successTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Success is a brief celebration, then the robot settles back to idle with the same words.
  const say = useCallback<Say>((pose, text) => {
    clearTimeout(successTimer.current);
    setRobot({ pose, text });
    if (pose === 'success') {
      successTimer.current = setTimeout(() => setRobot((current) => ({ ...current, pose: 'idle' })), 2200);
    }
  }, []);
  useEffect(() => () => clearTimeout(successTimer.current), []);

  const loadNotes = useCallback((signal: AbortSignal) => service.getNotes(session.id, { signal }), [service, session.id]);
  const notes = useAsyncResource(loadNotes, available.includes('notes') && (opened('notes') || opened('ask')), 'The notes couldn’t be loaded.');
  const loadQuiz = useCallback((signal: AbortSignal) => service.getQuiz(session.id, { signal }), [service, session.id]);
  const quiz = useAsyncResource(loadQuiz, available.includes('quiz') && opened('quiz'), 'The quiz couldn’t be created.');
  const loadCards = useCallback((signal: AbortSignal) => service.getCards(session.id, { signal }), [service, session.id]);
  const cards = useAsyncResource(loadCards, available.includes('cards') && opened('cards'), 'The cards couldn’t be made.');

  const selectTab = (next: WorkspaceTab, focus = false) => {
    dispatch({ type: 'setTab', tab: next });
    if (tab) setVisited((prev) => (prev.has(next) && prev.has(tab) ? prev : new Set(prev).add(next).add(tab)));
    if (focus) tabRefs.current[next]?.focus();
  };

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = tabs.findIndex((t) => t.id === tab);
    const last = tabs.length - 1;
    const target =
      event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : event.key === 'Home' ? 0
      : event.key === 'End' ? last
      : null;
    if (target === null) return;
    event.preventDefault();
    selectTab(tabs[target]!.id, true);
  };

  const leave = () => dispatch({ type: 'back' });
  const changeDocument = () => (progress ? setConfirmingChange(true) : leave());

  const demo = session.demo;
  // Each view is labelled by where its own content came from. A live session can still
  // serve sample notes or a sample quiz; the document was read then, so don't say it wasn't.
  const sample: Record<WorkspaceTab, boolean> = {
    notes: demo || (notes.status === 'success' && notes.data.demo),
    ask: demo || capabilities?.ask === 'demo',
    quiz: demo || (quiz.status === 'success' && quiz.data.demo),
    cards: demo || (cards.status === 'success' && cards.data.demo),
  };
  const sampleSubject: Record<WorkspaceTab, string> = {
    notes: 'These notes are',
    ask: 'Answers here are',
    quiz: 'This quiz is',
    cards: 'These cards are',
  };

  return (
    <section className="workspace" aria-labelledby="workspace-title">
      {/* The stage: the robot and the document on the band, with the work card rising over its edge. */}
      <div className="band band--host">
        <div className="band__inner band-row">
          <div className="host">
            <RobotMascot pose={robot.pose} facing="front" crop="bust" size="sm" />
            <SpeechBubble tail="left" live className="host__bubble">
              <p key={robot.text} className="bubble__text bubble__text--sm bubble__swap">
                {robot.text}
              </p>
            </SpeechBubble>
          </div>
          <div className="source-bar">
            <div className="source-bar__file">
              <span className="source-bar__icon" aria-hidden="true">
                <FileText />
              </span>
              <div className="source-bar__text">
                <h1 id="workspace-title" className="source-bar__name" ref={heading} tabIndex={-1} title={document.name}>
                  {document.name}
                </h1>
                <p className="source-bar__meta">
                  {formatBytes(document.size)}
                  {session.sectionCount !== undefined && !demo && ` · ${session.sectionCount} sections`}
                  {demo && ' · not analysed (demo)'}
                </p>
              </div>
            </div>
            <div className="source-bar__actions">
              <button type="button" className="btn btn--ghost btn--sm" onClick={changeDocument}>
                <ArrowLeft aria-hidden="true" />
                Change document
              </button>
              <StartOverButton
                hasProgress={progress}
                subject={document.name}
                onConfirm={() => dispatch({ type: 'startOver' })}
                icon={<RotateCcw aria-hidden="true" />}
              />
              <ConfirmDialog
                open={confirmingChange}
                title={`Change document and clear “${document.name}”?`}
                confirmLabel="Clear and change document"
                onConfirm={leave}
                onCancel={() => setConfirmingChange(false)}
              >
                Your questions, quiz answers and marked cards will be cleared. This can’t be undone.
              </ConfirmDialog>
            </div>
          </div>
        </div>
      </div>

      <div className="stage workspace__stage">
        <div className="panel workspace__panel">
          {tab === undefined && (
            <ErrorState
              title="Nothing to show for documents"
              message="This DockBrain server doesn’t offer notes, questions, quizzes or memory cards yet."
            />
          )}
          <div className="tabs" role="tablist" aria-label="Workspace views" hidden={tab === undefined}>
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                ref={(el) => {
                  tabRefs.current[id] = el;
                }}
                type="button"
                role="tab"
                id={`tab-${id}`}
                aria-selected={tab === id}
                aria-controls={`panel-${id}`}
                tabIndex={tab === id ? 0 : -1}
                className="tab"
                onClick={() => selectTab(id)}
                onKeyDown={onTabKey}
              >
                <Icon aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>

          {tab && sample[tab] && (
            <div className="workspace__demo">
              <Notice tone="demo" title="Sample content">
                {demo ? (
                  <>
                    {sampleSubject[tab]} about DockBrain’s built-in {SAMPLE_DOCUMENT_NAME}, not “{document.name}”, which
                    wasn’t read.
                  </>
                ) : (
                  <>
                    {sampleSubject[tab]} {tab === 'ask' || tab === 'cards' ? 'built-in samples' : 'a built-in sample'} about DockBrain’s{' '}
                    {SAMPLE_DOCUMENT_NAME}, not about “{document.name}”.
                  </>
                )}
              </Notice>
            </div>
          )}

          {tabs.map(({ id }) => (
            <div
              key={id}
              role="tabpanel"
              id={`panel-${id}`}
              aria-labelledby={`tab-${id}`}
              hidden={tab !== id}
              className="workspace__view"
            >
              {opened(id) && id === 'notes' && (
                <NotesView
                  active={tab === 'notes'}
                  notes={notes}
                  say={say}
                  available={available}
                  onNavigate={(t) => selectTab(t, true)}
                />
              )}
              {opened(id) && id === 'ask' && (
                <AskView
                  active={tab === 'ask'}
                  sessionId={session.id}
                  documentName={document.name}
                  suggestions={notes.status === 'success' ? notes.data.suggestedQuestions : []}
                  say={say}
                  onProgress={() => setProgress(true)}
                />
              )}
              {opened(id) && id === 'quiz' && (
                <QuizView
                  active={tab === 'quiz'}
                  quiz={quiz}
                  say={say}
                  available={available}
                  onProgress={() => setProgress(true)}
                  onNavigate={(t) => selectTab(t, true)}
                  onChangeDocument={changeDocument}
                />
              )}
              {opened(id) && id === 'cards' && (
                <CardsView
                  active={tab === 'cards'}
                  cards={cards}
                  sessionId={session.id}
                  say={say}
                  available={available}
                  onProgress={() => setProgress(true)}
                  onNavigate={(t) => selectTab(t, true)}
                  onChangeDocument={changeDocument}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
