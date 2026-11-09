import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, ShieldCheck } from 'lucide-react';
import { RobotMascot } from '../components/robot/RobotMascot';
import type { RobotPose } from '../components/robot/types';
import { Notice } from '../components/ui';
import { useScreenHeading, type ScreenProps } from '../app/navigation';
import { useService } from '../services/ServiceContext';
import { ServiceError, type ProcessingProgress, type SourceInput } from '../services/types';
import { DEFAULT_MAX_DOCUMENT_BYTES, DOCUMENT_EXTENSIONS } from '../lib/fileValidation';
import { DocumentPicker, type PickerMessage } from './select/DocumentPicker';
import { FolderPicker } from './select/FolderPicker';
import './select.css';

type Phase =
  | { kind: 'choosing' }
  | { kind: 'processing'; progress: ProcessingProgress }
  | { kind: 'failed'; message: string; retryable: boolean };

const COPY = {
  learn: {
    eyebrow: 'Learn from a document',
    title: 'Put your document here',
    lede: 'Choose a PDF, Word, text or Markdown file. I’ll get notes and answers ready.',
    action: 'Open document',
  },
  quiz: {
    eyebrow: 'Quiz yourself',
    title: 'Put your document here',
    lede: 'Choose a document and I’ll write questions from it.',
    action: 'Build my quiz',
  },
  cards: {
    eyebrow: 'Memory cards',
    title: 'Put your document here',
    lede: 'Choose a document and I’ll turn it into cards to flip through.',
    action: 'Make my cards',
  },
  codebase: {
    eyebrow: 'Understand a codebase',
    title: 'Put your project folder here',
    lede: 'Choose a project folder and I’ll explain what it does and why.',
    action: 'Explore codebase',
  },
} as const;

export function SelectScreen({ state, dispatch, capabilities }: ScreenProps) {
  const service = useService();
  const heading = useScreenHeading<HTMLHeadingElement>();
  const activity = state.activity ?? 'learn';
  const copy = COPY[activity];
  const isCodebase = activity === 'codebase';
  const demo = service.mode === 'demo';

  const [phase, setPhase] = useState<Phase>({ kind: 'choosing' });
  const [message, setMessage] = useState<PickerMessage>(null);
  const [justSelected, setJustSelected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const hasSelection = isCodebase ? Boolean(state.codebase) : Boolean(state.document);
  const busy = phase.kind === 'processing';

  // Cancel any in-flight processing if the screen goes away.
  useEffect(() => () => abortRef.current?.abort(), []);

  // A dropped file that misses the drop zone would otherwise open in the tab, losing the app.
  useEffect(() => {
    const block = (event: DragEvent) => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
    };
    window.addEventListener('dragover', block);
    window.addEventListener('drop', block);
    return () => {
      window.removeEventListener('dragover', block);
      window.removeEventListener('drop', block);
    };
  }, []);

  useEffect(() => {
    if (!justSelected) return;
    const timer = setTimeout(() => setJustSelected(false), 1600);
    return () => clearTimeout(timer);
  }, [justSelected]);

  const rules = {
    maxBytes: capabilities?.maxDocumentBytes ?? DEFAULT_MAX_DOCUMENT_BYTES,
    extensions: capabilities?.documentExtensions ?? DOCUMENT_EXTENSIONS,
  };

  const start = async () => {
    let input: SourceInput;
    if (isCodebase && state.codebase) {
      input = { kind: 'codebase', name: state.codebase.name, files: state.codebase.files };
    } else if (!isCodebase && state.document) {
      input = { kind: 'document', file: state.document };
    } else {
      setMessage({ tone: 'error', text: isCodebase ? 'Choose a project folder first.' : 'Choose a document first.' });
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setMessage(null);
    setPhase({ kind: 'processing', progress: { stage: 'reading', message: 'Starting…' } });
    try {
      const session = await service.openSource(input, {
        signal: controller.signal,
        onProgress: (progress) => {
          if (!controller.signal.aborted) setPhase({ kind: 'processing', progress });
        },
      });
      if (!controller.signal.aborted) dispatch({ type: 'sessionReady', session });
    } catch (error) {
      if (controller.signal.aborted) return;
      setPhase({
        kind: 'failed',
        message: error instanceof ServiceError ? error.message : 'Something went wrong while opening this. Try again.',
        retryable: error instanceof ServiceError ? error.retryable : true,
      });
    }
  };

  const cancel = () => {
    abortRef.current?.abort();
    setPhase({ kind: 'choosing' });
  };

  const pose: RobotPose = busy ? 'think' : justSelected ? 'success' : 'point';

  return (
    <section className="select" aria-labelledby="select-title">
      <div className="band">
        <div className="band__inner select__band">
          <button
            type="button"
            className="btn btn--ghost btn--sm back-button"
            onClick={() => {
              abortRef.current?.abort();
              dispatch({ type: 'back' });
            }}
          >
            <ArrowLeft aria-hidden="true" />
            Back
          </button>

          <div className="select__host">
            <RobotMascot pose={pose} facing="right" size="lg" />
            <div className="select__intro">
              <p className="eyebrow">{copy.eyebrow}</p>
              <h1 id="select-title" className="select__title" ref={heading} tabIndex={-1}>
                {copy.title}
              </h1>
              <p className="select__lede">{copy.lede}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="stage">
        <div className="select__panel">

          {phase.kind === 'processing' ? (
            <div className="processing" role="status" aria-live="polite">
              <div className="processing__row">
                <span className="spinner" aria-hidden="true" />
                <div>
                  <p className="processing__stage">{stageLabel(phase.progress, demo)}</p>
                  <p className="muted small">{phase.progress.message}</p>
                </div>
              </div>
              {phase.progress.fraction !== undefined && (
                <div className="progress" aria-hidden="true">
                  <span style={{ transform: `scaleX(${phase.progress.fraction})` }} />
                </div>
              )}
              <button type="button" className="btn btn--secondary btn--sm" onClick={cancel}>
                Cancel
              </button>
            </div>
          ) : (
            <>
              {isCodebase ? (
                <FolderPicker
                  selection={state.codebase}
                  disabled={busy}
                  onSelect={(selection) => {
                    dispatch({ type: 'selectCodebase', selection });
                    setPhase({ kind: 'choosing' });
                    setJustSelected(true);
                  }}
                  onRemove={() => {
                    dispatch({ type: 'clearSelection' });
                    setMessage(null);
                  }}
                  onMessage={setMessage}
                />
              ) : (
                <DocumentPicker
                  file={state.document}
                  rules={rules}
                  disabled={busy}
                  onSelect={(file) => {
                    dispatch({ type: 'selectDocument', file });
                    setPhase({ kind: 'choosing' });
                    setJustSelected(true);
                  }}
                  onRemove={() => {
                    dispatch({ type: 'clearSelection' });
                    setMessage(null);
                  }}
                  onMessage={setMessage}
                />
              )}

              <div aria-live="polite">
                {message && (
                  <Notice tone={message.tone} role={message.tone === 'error' ? 'alert' : undefined}>
                    {message.text}
                  </Notice>
                )}
                {phase.kind === 'failed' && (
                  <Notice tone="error" title="Couldn’t open this" role="alert">
                    {phase.message}
                  </Notice>
                )}
              </div>
            </>
          )}

          <div className="select__footer">
            <p className="select__privacy">
              <ShieldCheck aria-hidden="true" />
              {demo
                ? isCodebase
                  ? 'Demo mode: only file names and sizes are used, on this device. Nothing is uploaded.'
                  : 'Demo mode: your file stays on this device and isn’t uploaded or read.'
                : 'Selected files stay on this device until you continue; then they’re uploaded to your DockBrain server.'}
            </p>
            {!busy && (
              <button type="button" className="btn btn--primary" onClick={start} aria-disabled={!hasSelection}>
                {phase.kind === 'failed' && phase.retryable ? 'Try again' : copy.action}
                <ArrowRight aria-hidden="true" />
              </button>
            )}
          </div>
          {demo && !busy && hasSelection && (
            <p className="select__demo-hint">
              {isCodebase
                ? 'Next you’ll see a sample overview of the DockBrain project, not an analysis of this folder.'
                : 'Next you’ll see sample results about DockBrain’s built-in Solar System document, not this file.'}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function stageLabel(progress: ProcessingProgress, demo: boolean): string {
  if (demo) return 'Preparing the demo workspace';
  switch (progress.stage) {
    case 'uploading':
      return 'Uploading';
    case 'reading':
      return 'Reading the text';
    case 'indexing':
      return 'Indexing sections';
    case 'ready':
      return 'Ready';
  }
}
