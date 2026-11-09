import { useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { BrandMark } from '../components/ui';
import { ThemeToggle } from './ThemeToggle';
import type { Capabilities } from '../services/types';

export function TopBar({
  mode,
  capabilities,
  unreachable,
}: {
  mode: 'demo' | 'live';
  capabilities: Capabilities | null;
  unreachable: boolean;
}) {
  const live = mode === 'live';
  const label = live ? (unreachable ? 'Server unreachable' : 'Connected') : 'Demo mode';
  const detailsRef = useRef<HTMLDetailsElement>(null);

  // Close the explanation on Escape (returning focus) or a click elsewhere.
  useEffect(() => {
    const details = detailsRef.current;
    if (!details) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && details.open) {
        details.open = false;
        details.querySelector('summary')?.focus();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (details.open && !details.contains(event.target as Node)) details.open = false;
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, []);

  return (
    <header className="topbar">
      <div className="brand">
        <BrandMark />
        <span>DockBrain</span>
      </div>
      <div className="topbar__actions">
        <ThemeToggle />
        <details ref={detailsRef} className="mode-info" data-mode={live && !unreachable ? 'live' : 'demo'}>
          <summary>
            <span className="mode-info__dot" aria-hidden="true" />
            {label}
            <ChevronDown aria-hidden="true" width={16} height={16} />
          </summary>
          <div className="mode-info__panel">
            {live ? (
              <>
                <p>
                  <strong>Connected to a DockBrain server.</strong> Files you open are uploaded to it for
                  analysis.
                </p>
                {capabilities && <p>Answers: {capabilities.answerEngine}.</p>}
                {unreachable && <p>The server didn’t respond. Check that it is running, then reload.</p>}
              </>
            ) : (
              <>
                <p>
                  <strong>Nothing is analysed in demo mode.</strong> You can choose real files and folders, and
                  DockBrain checks their type and size on this device, but it never uploads or reads them.
                </p>
                <p>
                  Notes, answers, quizzes, memory cards and the codebase overview are built-in samples, labelled as such on each
                  screen.
                </p>
              </>
            )}
          </div>
        </details>
      </div>
    </header>
  );
}
