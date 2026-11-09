import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { App } from '../app/App';
import { ServiceProvider } from '../services/ServiceContext';
import { MockDockBrainService, type MockServiceOptions } from '../services/mockService';
import type { DockBrainService } from '../services/DockBrainService';
import type { Capabilities } from '../services/types';

/**
 * A connected (live) service whose sessions are real but whose features can be
 * individually 'available', 'demo' or 'unavailable', as a partial backend would report.
 * Content still comes from the fixtures; results keep the fixtures' own `demo` flag.
 */
export function liveService(features: Partial<Capabilities> = {}) {
  const mock = new MockDockBrainService({ latencyMs: 0 });
  return {
    mode: 'live' as const,
    getCapabilities: async () => ({ ...(await mock.getCapabilities()), mode: 'live' as const, ask: 'available' as const, ...features }),
    openSource: vi.fn<DockBrainService['openSource']>(async (input, options) => ({ ...(await mock.openSource(input, options)), demo: false })),
    getNotes: vi.fn<DockBrainService['getNotes']>(mock.getNotes.bind(mock)),
    ask: vi.fn<DockBrainService['ask']>(mock.ask.bind(mock)),
    getQuiz: vi.fn<DockBrainService['getQuiz']>(mock.getQuiz.bind(mock)),
    getCards: vi.fn<DockBrainService['getCards']>(mock.getCards.bind(mock)),
    revealCard: vi.fn<DockBrainService['revealCard']>(mock.revealCard.bind(mock)),
    getCodebaseOverview: vi.fn<DockBrainService['getCodebaseOverview']>(mock.getCodebaseOverview.bind(mock)),
    closeSession: vi.fn<DockBrainService['closeSession']>(mock.closeSession.bind(mock)),
  } satisfies DockBrainService;
}

/**
 * Drop a single file into the folder drop zone, where reading it finishes only when the
 * returned function is called, like a slow filesystem read.
 */
export function startSlowFolderDrop(name: string): (file?: File) => void {
  let finish: ((file: File) => void) | undefined;
  const entry = {
    name,
    isFile: true,
    isDirectory: false,
    file: (callback: (file: File) => void) => {
      finish = callback;
    },
  };
  fireEvent.drop(screen.getByRole('group', { name: 'Drop a project folder here' }), {
    dataTransfer: { types: ['Files'], files: [], items: [{ kind: 'file', webkitGetAsEntry: () => entry }] },
  });
  return (file = new File(['print(1)'], name)) => {
    if (!finish) throw new Error('the drop was never read');
    finish(file);
  };
}

export function renderApp(options: MockServiceOptions = {}, service: DockBrainService = new MockDockBrainService({ latencyMs: 0, ...options })) {
  // applyAccept: false so tests can pick files the picker would normally filter out.
  const user = userEvent.setup({ applyAccept: false });
  render(
    <ServiceProvider service={service}>
      <App />
    </ServiceProvider>,
  );
  return { user, service };
}

export const pdf = (name = 'Fruit-Guide.pdf', size = 2048) => new File([new Uint8Array(size)], name, { type: 'application/pdf' });

/** Welcome → choose an activity → select a document → open it. */
export async function openDocument(user: ReturnType<typeof userEvent.setup>, activity: RegExp = /Learn from a document/, file = pdf()) {
  await user.click(screen.getByRole('button', { name: activity }));
  await user.upload(screen.getByTestId('document-input'), file);
  await user.click(screen.getByRole('button', { name: /Open document|Build my quiz|Make my cards/ }));
}
