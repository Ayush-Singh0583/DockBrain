/**
 * App navigation and selection state. Rules that keep state consistent:
 * - A document selection survives switching between "learn", "quiz" and "cards"; a
 *   folder survives only within "codebase". Incompatible selections are dropped.
 * - A selection is accepted only on the select screen, and only of the kind the activity
 *   uses; anything else is a late result from a picker the person already left.
 * - Changing or removing the selection ends the current session.
 * - Leaving a workspace (back / change document) ends its session; results are
 *   requested again for the next one.
 * - Start over clears everything.
 */
import type { CodebaseSelection } from '../lib/folderSelection';
import type { Activity, SourceSession } from '../services/types';

export type Screen = 'welcome' | 'select' | 'workspace' | 'codebase';
export type WorkspaceTab = 'notes' | 'ask' | 'quiz' | 'cards';

export interface AppState {
  screen: Screen;
  activity: Activity | null;
  document: File | null;
  codebase: CodebaseSelection | null;
  session: SourceSession | null;
  tab: WorkspaceTab;
}

export type AppAction =
  | { type: 'chooseActivity'; activity: Activity }
  | { type: 'selectDocument'; file: File }
  | { type: 'selectCodebase'; selection: CodebaseSelection }
  | { type: 'clearSelection' }
  | { type: 'sessionReady'; session: SourceSession }
  | { type: 'back' }
  | { type: 'startOver' }
  | { type: 'setTab'; tab: WorkspaceTab };

export const initialState: AppState = {
  screen: 'welcome',
  activity: null,
  document: null,
  codebase: null,
  session: null,
  tab: 'notes',
};

export function sourceKindFor(activity: Activity): 'document' | 'codebase' {
  return activity === 'codebase' ? 'codebase' : 'document';
}

/** The workspace tab an activity opens on. */
function firstTab(activity: Activity | null): WorkspaceTab {
  return activity === 'quiz' || activity === 'cards' ? activity : 'notes';
}

function accepts(state: AppState, kind: 'document' | 'codebase'): boolean {
  return state.screen === 'select' && state.activity !== null && sourceKindFor(state.activity) === kind;
}

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'chooseActivity': {
      const kind = sourceKindFor(action.activity);
      return {
        ...state,
        screen: 'select',
        activity: action.activity,
        document: kind === 'document' ? state.document : null,
        codebase: kind === 'codebase' ? state.codebase : null,
        session: null,
        tab: firstTab(action.activity),
      };
    }
    // Selections come from pickers on the select screen. One that arrives anywhere else,
    // or is the wrong kind for the activity, is a late result from an abandoned picker.
    case 'selectDocument':
      if (!accepts(state, 'document')) return state;
      return { ...state, document: action.file, codebase: null, session: null };
    case 'selectCodebase':
      if (!accepts(state, 'codebase')) return state;
      return { ...state, codebase: action.selection, document: null, session: null };
    case 'clearSelection':
      if (state.screen !== 'select') return state;
      return { ...state, document: null, codebase: null, session: null };
    case 'sessionReady':
      if (state.screen !== 'select') return state; // a late result after navigating away
      return {
        ...state,
        session: action.session,
        screen: action.session.kind === 'codebase' ? 'codebase' : 'workspace',
        tab: firstTab(state.activity),
      };
    case 'back':
      if (state.screen === 'select') return { ...state, screen: 'welcome', session: null };
      if (state.screen === 'workspace' || state.screen === 'codebase') return { ...state, screen: 'select', session: null };
      return state;
    case 'startOver':
      return initialState;
    case 'setTab':
      return { ...state, tab: action.tab };
  }
}
