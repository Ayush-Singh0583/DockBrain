import { describe, expect, it } from 'vitest';
import { appReducer, initialState, type AppState } from './state';
import type { CodebaseSelection } from '../lib/folderSelection';
import type { SourceSession } from '../services/types';

const doc = new File(['x'], 'a.pdf');
const folder: CodebaseSelection = {
  name: 'proj', files: [], totalBytes: 0, ignoredCount: 0, truncated: false, languages: [], fromFolder: true,
};
const session = (kind: 'document' | 'codebase'): SourceSession => ({ id: 's1', kind, displayName: 'x', demo: true });

function run(...actions: Parameters<typeof appReducer>[1][]): AppState {
  return actions.reduce(appReducer, initialState);
}

describe('appReducer', () => {
  it('keeps a document when switching between learn and quiz, and opens quiz on the quiz tab', () => {
    const state = run(
      { type: 'chooseActivity', activity: 'learn' },
      { type: 'selectDocument', file: doc },
      { type: 'back' },
      { type: 'chooseActivity', activity: 'quiz' },
    );
    expect(state.document).toBe(doc);
    expect(state.tab).toBe('quiz');
  });

  it('keeps a document for memory cards, and opens them on the cards tab', () => {
    const state = run(
      { type: 'chooseActivity', activity: 'quiz' },
      { type: 'selectDocument', file: doc },
      { type: 'back' },
      { type: 'chooseActivity', activity: 'cards' },
    );
    expect(state.document).toBe(doc);
    expect(state.tab).toBe('cards');
    const ready = appReducer(state, { type: 'sessionReady', session: session('document') });
    expect([ready.screen, ready.tab]).toEqual(['workspace', 'cards']);
    expect(run({ type: 'chooseActivity', activity: 'cards' }, { type: 'back' }, { type: 'chooseActivity', activity: 'learn' }).tab).toBe('notes');
  });

  it('drops a document when switching to the codebase flow, and a folder when leaving it', () => {
    const toCodebase = run({ type: 'chooseActivity', activity: 'learn' }, { type: 'selectDocument', file: doc }, { type: 'back' }, { type: 'chooseActivity', activity: 'codebase' });
    expect(toCodebase.document).toBeNull();
    const toLearn = appReducer(appReducer(appReducer(toCodebase, { type: 'selectCodebase', selection: folder }), { type: 'back' }), { type: 'chooseActivity', activity: 'learn' });
    expect(toLearn.codebase).toBeNull();
  });

  it('ends the session when going back from a workspace, but keeps the file', () => {
    const state = run(
      { type: 'chooseActivity', activity: 'learn' },
      { type: 'selectDocument', file: doc },
      { type: 'sessionReady', session: session('document') },
      { type: 'back' },
    );
    expect(state.screen).toBe('select');
    expect(state.session).toBeNull();
    expect(state.document).toBe(doc);
  });

  it('ignores a session that arrives after the user left the select screen', () => {
    const state = run({ type: 'chooseActivity', activity: 'learn' }, { type: 'back' }, { type: 'sessionReady', session: session('document') });
    expect(state.screen).toBe('welcome');
    expect(state.session).toBeNull();
  });

  it('replaces the file on the select screen; start over clears everything', () => {
    const other = new File(['y'], 'b.pdf');
    const replaced = run({ type: 'chooseActivity', activity: 'learn' }, { type: 'selectDocument', file: doc }, { type: 'selectDocument', file: other });
    expect(replaced.document).toBe(other);
    expect(replaced.session).toBeNull();
    expect(appReducer(replaced, { type: 'startOver' })).toEqual(initialState);
  });

  it('ignores a selection that arrives outside the select screen, keeping the open session', () => {
    const open = run({ type: 'chooseActivity', activity: 'learn' }, { type: 'selectDocument', file: doc }, { type: 'sessionReady', session: session('document') });
    expect(appReducer(open, { type: 'selectDocument', file: new File(['y'], 'b.pdf') })).toBe(open);
    expect(appReducer(open, { type: 'selectCodebase', selection: folder })).toBe(open);
    expect(appReducer(open, { type: 'clearSelection' })).toBe(open);
    expect(appReducer(initialState, { type: 'selectDocument', file: doc })).toBe(initialState);
  });

  it('ignores a selection of the wrong kind for the current activity', () => {
    const learning = run({ type: 'chooseActivity', activity: 'learn' }, { type: 'selectDocument', file: doc });
    expect(appReducer(learning, { type: 'selectCodebase', selection: folder })).toBe(learning);
    const exploring = run({ type: 'chooseActivity', activity: 'codebase' }, { type: 'selectCodebase', selection: folder });
    expect(appReducer(exploring, { type: 'selectDocument', file: doc })).toBe(exploring);
  });
});
