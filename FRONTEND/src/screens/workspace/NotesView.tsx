import { useEffect, useState } from 'react';
import { ListChecks, MessageCircleQuestion } from 'lucide-react';
import { CitedText, SourcesList } from '../../components/evidence';
import { ErrorState, Notice, Skeleton } from '../../components/ui';
import type { Resource } from '../../lib/useAsyncResource';
import { useStillWorking } from '../../lib/useStillWorking';
import type { Notes } from '../../services/types';
import type { WorkspaceTab } from '../../app/state';
import type { Say } from './WorkspaceScreen';

export function NotesView({
  active,
  notes,
  say,
  available,
  onNavigate,
}: {
  active: boolean;
  notes: Resource<Notes> & { reload: () => void };
  say: Say;
  /** Views this server offers; links to others are left out. */
  available: WorkspaceTab[];
  onNavigate: (tab: WorkspaceTab) => void;
}) {
  const canAsk = available.includes('ask');
  const canQuiz = available.includes('quiz');
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [highlight, setHighlight] = useState<{ index: number; nonce: number } | null>(null);

  useEffect(() => {
    if (!active) return;
    if (notes.status === 'loading' || notes.status === 'idle') say('think', 'Gathering the key points…');
    else if (notes.status === 'error') say('idle', 'I couldn’t load the notes. Let’s try again.');
    else say('point', 'Here are the key points. Select a number to see where each one comes from.');
  }, [active, notes.status, say]);

  useStillWorking(active && (notes.status === 'idle' || notes.status === 'loading'), say);

  if (notes.status === 'idle' || notes.status === 'loading') return <Skeleton lines={6} label="Loading notes" />;
  if (notes.status === 'error') {
    return <ErrorState title="Notes aren’t available" message={notes.message} onRetry={notes.reload} />;
  }

  const { data } = notes;
  const reveal = (index: number) => {
    setSourcesOpen(true);
    setHighlight({ index, nonce: Date.now() });
  };

  return (
    <article className="notes">
      {data.notice && (
        <Notice tone="info" role="status">
          {data.notice}
        </Notice>
      )}
      <header className="notes__header">
        <h2 className="notes__title">{data.title}</h2>
        <p className="notes__summary">{data.summary}</p>
      </header>

      <div className="notes__sections">
        {data.sections.map((section) => (
          <section key={section.id} className="notes__section" aria-labelledby={`note-${section.id}`}>
            <h3 id={`note-${section.id}`}>{section.heading}</h3>
            <ul>
              {section.points.map((point, i) => (
                <li key={i}>
                  <CitedText
                    segments={[
                      { type: 'text', value: point.text },
                      ...(point.citations ?? []).map((index) => ({ type: 'cite' as const, index })),
                    ]}
                    onCite={reveal}
                  />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <SourcesList
        citations={data.sources}
        idPrefix="notes"
        open={sourcesOpen}
        onToggle={() => setSourcesOpen((open) => !open)}
        highlight={highlight}
      />

      {(canAsk || canQuiz) && (
        <div className="notes__next">
          <p className="muted">Ready to go further?</p>
          <div className="notes__next-actions">
            {canAsk && (
              <button type="button" className="btn btn--secondary btn--sm" onClick={() => onNavigate('ask')}>
                <MessageCircleQuestion aria-hidden="true" />
                Ask a question
              </button>
            )}
            {canQuiz && (
              <button type="button" className="btn btn--secondary btn--sm" onClick={() => onNavigate('quiz')}>
                <ListChecks aria-hidden="true" />
                Take the quiz
              </button>
            )}
          </div>
        </div>
      )}
    </article>
  );
}
